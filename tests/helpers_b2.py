"""Helpers shared by the B2 tests: Kyiv time, simulator pages, runs, feed.

No module-level import of ``spm``: the system is reached through the
fixtures in ``conftest.py`` (``app.state.updates``, ``spm.storage``) and HTTP.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from helpers import API, all_pages, create_material, create_supplier, link

KYIV = ZoneInfo("Europe/Kyiv")

# Ukrainian texts of the run log (REQ-F-032, REQ-F-033, Д.7, Д.8).
STATUS_TEXT = {
    "success": "успіх",
    "partial": "частково",
    "error": "помилка",
    "interrupted": "перервано",
    "in_progress": "триває",
    "not_finished": "не завершено",
}
TRIGGER_TEXT = {
    "scheduled": "за розкладом",
    "manual": "вручну",
    "catch_up": "доганяння",
}
REASON_TEXT = {
    "unavailable": "сторінка недоступна",
    "timeout": "перевищено час очікування 30 с",
    "unparsable": "сторінку не розібрано",
}
DASH = "—"
RUN_IN_PROGRESS = "оновлення вже триває"
NO_ACTIVE = "немає активних постачальників"
NEVER_UPDATED = "ще не оновлювався"


# --- time ---------------------------------------------------------------------


def kyiv(y: int, mo: int, d: int, h: int = 3, mi: int = 30, s: int = 0, fold: int = 0):
    """A moment given by Kyiv wall-clock time, as an aware UTC datetime.

    ``fold=1`` picks the second occurrence of an hour repeated in autumn.
    """
    return datetime(y, mo, d, h, mi, s, tzinfo=KYIV, fold=fold).astimezone(UTC)


def move_to(clock, moment: datetime) -> None:
    """Move the controlled clock forward to the moment."""
    clock.advance(moment - clock.now())


def iso_kyiv(moment: datetime) -> str:
    return moment.astimezone(KYIV).isoformat(timespec="seconds")


def parse_dt(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.utcoffset() is not None, text
    return value


# --- simulator pages ------------------------------------------------------------


def item(sku: str, price: str | None = "100.00", unit: str = "шт", name: str = ""):
    return {"sku": sku, "name": name or f"Позиція {sku}", "unit": unit, "price": price}


def items(prefix: str, count: int, price: str = "100.00", unit: str = "шт"):
    return [item(f"{prefix}-{n}", price, unit) for n in range(1, count + 1)]


# --- runs through the API -----------------------------------------------------------


def get_run(client, run_id: int) -> dict:
    resp = client.get(f"{API}/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def wait_run(client, run_id: int, timeout: float = 15) -> dict:
    """Wait until the run is no longer ``in_progress``; return it."""
    deadline = time.monotonic() + timeout
    while True:
        run = get_run(client, run_id)
        if run["status"] != "in_progress":
            return run
        assert time.monotonic() < deadline, f"run {run_id} did not finish"
        time.sleep(0.05)


def wait_until(predicate, timeout: float = 15, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)


def start_manual(client) -> dict:
    """``POST /runs``; the run is started and keeps running in the background."""
    resp = client.post(f"{API}/runs")
    assert resp.status_code == 202, resp.text
    return resp.json()


def log_entries(client) -> list[dict]:
    """All run log entries, newest first."""
    return all_pages(client, f"{API}/run-log-entries")


def runs_in_log(client) -> list[dict]:
    return [e["run"] for e in log_entries(client) if e["kind"] == "run"]


def latest_run(client) -> dict | None:
    runs = runs_in_log(client)
    return runs[0] if runs else None


def row(run: dict, supplier_name: str) -> dict:
    """The supplier's row (status in the run) by supplier name."""
    (found,) = [
        r
        for r in run["supplier_run_statuses"]
        if r["supplier"]["name"] == supplier_name
    ]
    return found


def supplier_written(client, supplier_name: str):
    """Predicate: the latest run has a status for the supplier (its data written)."""

    def check():
        run = latest_run(client)
        return run if run and row(run, supplier_name)["status"] is not None else None

    return check


def update_statuses(client) -> dict[str, str | None]:
    """Screen "стан оновлення постачальників" through the API: name -> date."""
    rows = all_pages(client, f"{API}/supplier-update-statuses")
    return {r["supplier"]["name"]: r["last_update_date"] for r in rows}


def d(text: str) -> date:
    return date.fromisoformat(text)


def money(text: str) -> Decimal:
    return Decimal(text)


# --- a scenario: suppliers on the simulator, runs, links, prices, events -----------


class World:
    """Suppliers served by the simulator, created in the system through the API.

    Runs are started from code: ``run()`` calls ``app.state.updates.run`` and
    returns the run as ``GET /runs/{id}`` shows it.
    """

    def __init__(self, *, app, admin, sim, updates, clock, storage, config) -> None:
        self.app = app
        self.admin = admin
        self.sim = sim
        self.updates = updates
        self.clock = clock
        self.storage = storage
        self.config = config
        self.supplier_ids: dict[str, int] = {}
        self.slugs: dict[str, str] = {}
        self.item_ids: dict[str, int] = {}
        self.material_ids: dict[str, int] = {}

    # suppliers and pages
    def supplier(
        self,
        name: str,
        slug: str,
        page: list[dict],
        *,
        layout: str = "table",
        parser: str = "table_layout",
        active: bool = True,
    ) -> int:
        self.sim.put(slug, page, name=name, layout=layout)
        body = create_supplier(
            self.admin,
            name,
            catalog_url=self.sim.url(slug),
            parser=parser,
            active=active,
        )
        self.supplier_ids[name] = body["id"]
        self.slugs[name] = slug
        return body["id"]

    def page(self, name: str, page: list[dict], **fields) -> None:
        slug = self.slugs[name]
        current = self.sim.suppliers[slug]
        self.sim.put(
            slug,
            page,
            name=current["name"],
            layout=current["layout"],
            mode=fields.pop("mode", "normal"),
            **fields,
        )

    def mode(self, name: str, mode: str, **fields) -> None:
        self.sim.mode(self.slugs[name], mode, **fields)

    def set_active(self, name: str, active: bool) -> None:
        resp = self.admin.patch(
            f"{API}/suppliers/{self.supplier_ids[name]}", json={"active": active}
        )
        assert resp.status_code == 200, resp.text

    # time
    def at(self, y: int, mo: int, d: int, h: int = 3, mi: int = 30, s: int = 0):
        move_to(self.clock, kyiv(y, mo, d, h, mi, s))

    # runs
    def run(self, trigger: str = "scheduled", started_by: str | None = None) -> dict:
        if trigger == "manual" and started_by is None:
            started_by = "admin"
        run_id = self.updates.run(trigger, started_by=started_by)
        assert run_id is not None, "the run did not start"
        self._remember_items()
        return get_run(self.admin, run_id)

    def _remember_items(self) -> None:
        for entry in self.unlinked():
            self.item_ids.setdefault(entry["sku"], entry["id"])

    def unlinked(self) -> list[dict]:
        """``GET /unlinked-items``: the supplier items of every page."""
        rows = all_pages(self.admin, f"{API}/unlinked-items")
        return [r["supplier_item"] for r in rows]

    # materials and links
    def material(self, name: str, unit: str = "шт") -> int:
        body = create_material(self.admin, name, unit=unit)
        self.material_ids[name] = body["id"]
        return body["id"]

    def link(self, sku: str, material: str) -> None:
        resp = link(self.admin, self.item_ids[sku], self.material_ids[material])
        assert resp.status_code in (200, 201), resp.text

    def unlink(self, sku: str) -> None:
        resp = self.admin.delete(f"{API}/supplier-items/{self.item_ids[sku]}/link")
        assert resp.status_code == 204, resp.text

    def settings(self, **values) -> None:
        resp = self.admin.patch(f"{API}/settings", json=values)
        assert resp.status_code == 200, resp.text

    # stored data
    def prices(self, sku: str) -> list:
        """Daily prices of the item, oldest date first."""
        item_id = self.item_ids[sku]
        rows = [
            p
            for p in self.storage.daily_prices(self.config.database_path)
            if p.supplier_item_id == item_id
        ]
        return sorted(rows, key=lambda p: p.price_date)

    def price_on(self, sku: str, day: date):
        found = [p for p in self.prices(sku) if p.price_date == day]
        assert len(found) <= 1, f"{len(found)} daily prices of {sku} for {day}"
        return found[0] if found else None

    def events(self, sku: str | None = None, kind: str | None = None) -> list:
        """Events in the order of creation."""
        rows = list(self.storage.events(self.config.database_path))
        if sku is not None:
            rows = [e for e in rows if e.supplier_item_id == self.item_ids[sku]]
        if kind is not None:
            rows = [e for e in rows if e.kind == kind]
        return rows

    # a linked item with a feed base: seen unlinked, linked, then "appeared"
    def linked_with_base(
        self, supplier: str, slug: str, page: list[dict], links: dict[str, str]
    ) -> None:
        """Supplier with ``page``; each ``sku -> material`` linked, base set.

        Two runs on 2026-10-01 and 2026-10-02; the second creates "appeared"
        with the price on the page, which becomes the feed base (REQ-F-046).
        """
        self.supplier(supplier, slug, page)
        self.at(2026, 10, 1)
        self.run()
        for sku, material in links.items():
            if material not in self.material_ids:
                unit = next(i["unit"] for i in page if i["sku"] == sku)
                self.material(material, unit=unit)
            self.link(sku, material)
        self.at(2026, 10, 2)
        self.run()
        for sku in links:
            assert [e.kind for e in self.events(sku)] == ["appeared"]

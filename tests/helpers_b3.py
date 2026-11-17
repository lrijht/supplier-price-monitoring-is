"""Helpers shared by the B3 tests: a market of linked items with daily prices,
the view operations (18–21, 15) and the screens of block B3.

No module-level import of ``spm``: the system is reached through HTTP and the
fixtures in ``conftest.py`` (``world`` — suppliers on the simulator, runs from
code through ``app.state.updates``).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from helpers import API, all_pages, data_table, forms, normalize, page_text
from helpers_b2 import item

# Screen texts of block B3 (REQ-F-036, REQ-F-038, REQ-F-040, REQ-F-049,
# REQ-F-011, REQ-F-017).
CHEAPEST = "найдешевша"
STALE = "застаріла"
NO_PRICE_YET = "ціни ще немає"
UNIT_MISMATCH = "одиниця не збігається"
AT_PERIOD_START = "чинна на початок періоду"
MATERIAL_DEACTIVATED = "матеріал деактивовано"
SUPPLIER_INACTIVE = "постачальник неактивний"
SHOW_INACTIVE = "показати неактивні"
KIND_TEXT = {
    "price_change": "зміна ціни",
    "appeared": "з'явився",
    "disappeared": "зник",
}

SLUGS = {
    "Альфа": "alfa",
    "Бета": "beta",
    "Вега": "vega",
    "Гама": "gama",
    "Ірпінь": "irpin",
}

# The 11 screens of REQ-NF-003 by their entry address (the material comparison
# needs a material: ``/material-comparisons/{id}``).
MANAGER_SCREENS = [
    "/material-comparisons",
    "/material-comparisons/{material}",
    "/price-history",
    "/events",
    "/supplier-update-statuses",
]
ADMIN_ONLY_SCREENS = [
    "/suppliers",
    "/materials",
    "/unlinked-items",
    "/attention-items",
    "/run-log-entries",
    "/settings",
]


def D(day: int, month: int = 10) -> date:
    return date(2026, month, day)


# --- a market: suppliers, linked items, prices per day ------------------------------------


def page_of(prices: dict[str, object]) -> list[dict]:
    """``{sku: price}`` or ``{sku: (price, unit)}`` -> simulator page items."""
    page = []
    for sku, value in prices.items():
        price, unit = value if isinstance(value, tuple) else (value, "шт")
        page.append(item(sku, price, unit))
    return page


class Market:
    """Suppliers on the simulator whose items are linked to materials.

    ``Market(world, {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М1"}})`` creates
    the suppliers (in the given order), runs once on ``start`` so the items
    are seen unlinked, creates the materials (unit "шт") and links the items.
    No price is stored by that run (REQ-F-012). ``day()`` then runs with the
    given prices: a supplier left out of the mapping is "сторінка недоступна"
    in that run (status "помилка", no daily price, REQ-F-026).
    """

    def __init__(
        self,
        world,
        links: dict[str, dict[str, str]],
        *,
        start: date | None = None,
        units: dict[str, str] | None = None,
    ) -> None:
        self.world = world
        self.links = links
        units = units or {}
        start = start or D(1)
        for supplier, skus in links.items():
            page = [item(sku, "100.00", units.get(sku, "шт")) for sku in skus]
            world.supplier(supplier, SLUGS[supplier], page)
        world.at(start.year, start.month, start.day)
        world.run()
        for skus in links.values():
            for sku, material in skus.items():
                if material not in world.material_ids:
                    world.material(material, unit=units.get(sku, "шт"))
                world.link(sku, material)

    def day(
        self,
        when: date,
        prices: dict[str, dict[str, object]],
        *,
        hour: int = 3,
        minute: int = 30,
        trigger: str = "scheduled",
    ) -> dict:
        """One run at ``when`` with the given pages; returns the run."""
        for supplier in self.links:
            if supplier in prices:
                self.world.page(supplier, page_of(prices[supplier]))
            else:
                self.world.mode(supplier, "unavailable")
        self.world.at(when.year, when.month, when.day, hour, minute)
        return self.world.run(trigger)

    def mid(self, material: str) -> int:
        return self.world.material_ids[material]

    def sid(self, supplier: str) -> int:
        return self.world.supplier_ids[supplier]


# --- view operations through the API ------------------------------------------------------


def comparison(client, material_id: int) -> dict:
    resp = client.get(f"{API}/material-comparisons/{material_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def comparison_rows(client, material_id: int) -> dict[str, dict]:
    """Rows of the material comparison by supplier name."""
    return {r["supplier"]["name"]: r for r in comparison(client, material_id)["items"]}


def comparison_list(client, q: str | None = None) -> list[dict]:
    path = f"{API}/material-comparisons"
    if q is not None:
        path += f"?q={q}"
    return all_pages(client, path)


def list_row(client, material: str) -> dict:
    (found,) = [r for r in comparison_list(client) if r["material"]["name"] == material]
    return found


def history(client, material_id: int, period: str = "all") -> list[dict]:
    resp = client.get(f"{API}/materials/{material_id}/price-history?period={period}")
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def history_rows(client, material_id: int, period: str = "all") -> list[tuple]:
    """``(date, supplier, price, unit_mismatch, effective_at_period_start)``."""
    return [
        (
            r["date"],
            r["supplier"]["name"],
            r["price"],
            r["unit_mismatch"],
            r["effective_at_period_start"],
        )
        for r in history(client, material_id, period)
    ]


def feed(client, **filters) -> list[dict]:
    query = "&".join(f"{k}={v}" for k, v in filters.items())
    return all_pages(client, f"{API}/events" + (f"?{query}" if query else ""))


def feed_keys(events: list[dict]) -> list[tuple]:
    return [
        (e["kind"], e["material"]["id"], e["supplier"]["id"], e["date"]) for e in events
    ]


def stored_feed_keys(world) -> list[tuple]:
    """Stored events, newest created first (REQ-F-057: later created — higher)."""
    rows = list(world.storage.events(world.config.database_path))
    return [
        (e.kind, e.material_id, e.supplier_id, e.event_date.isoformat())
        for e in reversed(rows)
    ]


def attention(client) -> list[dict]:
    return all_pages(client, f"{API}/attention-items")


def money(text: str) -> Decimal:
    return Decimal(text)


# --- screens --------------------------------------------------------------------------------


def compact(text: str) -> str:
    """Text without any spaces: "1 000,00 грн" -> "1000,00грн"."""
    return re.sub(r"\s+", "", normalize(text))


def row_text(row: list[str]) -> str:
    return " ".join(row)


def hrefs(html: str) -> list[str]:
    """``href`` values of the page's links."""
    return [normalize(h) for h in re.findall(r"<a\b[^>]*\bhref=\"([^\"]*)\"", html)]


def path_of(href: str) -> str:
    return href.split("?", 1)[0].split("#", 1)[0]


def select_options(html: str, name: str) -> list[tuple[str, str]]:
    """``(value, text)`` of the options of ``<select name=...>`` in any form,
    without an empty "all" option."""
    found = []
    for form in forms(html):
        for option in form["selects"].get(name, []):
            if option["value"] not in ("", None):
                found.append((option["value"], option["text"]))
    return found


def get_form_fields(html: str) -> set[str]:
    """Names of the fields of the page's GET forms."""
    names: set[str] = set()
    for form in forms(html):
        if form["method"] == "get":
            names |= {i.get("name") for i in form["inputs"] if i.get("name")}
            names |= set(form["selects"])
    return names


def post_forms(html: str) -> list[dict]:
    return [f for f in forms(html) if f["method"] == "post"]


def screen(client, path: str) -> str:
    """A screen as the browser gets it: 200, text/html; returns the HTML."""
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.text[:300])
    assert resp.headers["content-type"].startswith("text/html")
    return resp.text


def screen_rows(client, path: str) -> list[list[str]]:
    _, rows = data_table(screen(client, path))
    return rows


def all_screen_rows(client, path: str) -> list[list[str]]:
    """Rows of every page of a paged screen (``page`` parameter)."""
    sep = "&" if "?" in path else "?"
    rows: list[list[str]] = []
    page = 1
    while True:
        html = screen(client, f"{path}{sep}page={page}")
        _, found = data_table(html)
        rows.extend(found)
        if f"page={page + 1}" not in html:
            return rows
        page += 1


def lower_headers(html: str) -> list[str]:
    headers, _ = data_table(html)
    return [
        normalize(h).lower().replace("«", "").replace("»", "").replace('"', "")
        for h in headers
    ]


def text_of(client, path: str) -> str:
    return page_text(screen(client, path))

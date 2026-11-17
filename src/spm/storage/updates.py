"""Repositories of update data: runs, supplier statuses, the run log, accepted
volumes, daily prices, events and the feed state of supplier items.

Every function takes an open connection from ``Database.transaction``. Moments
are kept in UTC ISO 8601 with microseconds (``moment_text``), so text order is
time order; Kyiv dates are ``YYYY-MM-DD``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from spm.clock import to_kyiv

# Values of the kind and status columns (storage/schema.py) that code compares
# and writes; the SQL of this module uses the same values in its text.
ENTRY_RUN = "run"
ENTRY_SKIPPED = "skipped"
ENTRY_NO_ACTIVE_SUPPLIERS = "no_active_suppliers"
ENTRY_VOLUME_ACCEPTANCE = "volume_acceptance"
EVENT_PRICE_CHANGE = "price_change"
EVENT_APPEARED = "appeared"
EVENT_DISAPPEARED = "disappeared"
RUN_INTERRUPTED = "interrupted"

# --- moments ---------------------------------------------------------------------------


def moment_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text is not None else None


def _date(text: str | None) -> date | None:
    return date.fromisoformat(text) if text is not None else None


def _decimal(text: str | None) -> Decimal | None:
    return Decimal(text) if text is not None else None


# --- runs and supplier statuses (Д.7, Д.8) ------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRow:
    id: int
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    started_by: str | None
    status: str
    price_date: date


@dataclass(frozen=True, slots=True)
class StatusRow:
    run_id: int
    supplier_id: int
    supplier_name: str
    status: str | None
    parsed_items_count: int | None
    reason_code: str | None
    error_reason: str | None
    warnings: list[dict]
    volume_acceptance_available: bool


_RUN_COLUMNS = "id, trigger, started_at, finished_at, started_by, status, price_date"


def _run(row: sqlite3.Row) -> RunRow:
    return RunRow(
        row["id"],
        row["trigger"],
        moment(row["started_at"]),
        moment(row["finished_at"]),
        row["started_by"],
        row["status"],
        date.fromisoformat(row["price_date"]),
    )


def insert_run(
    conn: sqlite3.Connection,
    *,
    trigger: str,
    started_at: datetime,
    started_by: str | None,
    price_date: date,
    supplier_ids: list[int],
) -> int:
    cur = conn.execute(
        "INSERT INTO runs (trigger, started_at, started_by, status, price_date)"
        " VALUES (?, ?, ?, 'in_progress', ?)",
        (trigger, moment_text(started_at), started_by, price_date.isoformat()),
    )
    run_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO supplier_run_statuses (run_id, supplier_id) VALUES (?, ?)",
        [(run_id, sid) for sid in supplier_ids],
    )
    return run_id


def get_run(conn: sqlite3.Connection, run_id: int) -> RunRow | None:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    return _run(row) if row is not None else None


def runs_in_progress(conn: sqlite3.Connection) -> list[RunRow]:
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE status = 'in_progress' ORDER BY id"
    ).fetchall()
    return [_run(r) for r in rows]


def last_run(conn: sqlite3.Connection) -> RunRow | None:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return _run(row) if row is not None else None


def finish_run(
    conn: sqlite3.Connection, run_id: int, status: str, finished_at: datetime
) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
        (status, moment_text(finished_at), run_id),
    )


def interrupt_run(conn: sqlite3.Connection, run_id: int) -> None:
    """REQ-F-024: the run is "перервано"; suppliers without data "не завершено"."""
    conn.execute("UPDATE runs SET status = 'interrupted' WHERE id = ?", (run_id,))
    conn.execute(
        "UPDATE supplier_run_statuses SET status = 'not_finished'"
        " WHERE run_id = ? AND status IS NULL",
        (run_id,),
    )


def set_supplier_status(
    conn: sqlite3.Connection,
    run_id: int,
    supplier_id: int,
    *,
    status: str,
    parsed_items_count: int | None = None,
    reason_code: str | None = None,
    error_reason: str | None = None,
    warnings: list[dict] | None = None,
) -> None:
    conn.execute(
        "UPDATE supplier_run_statuses SET status = ?, parsed_items_count = ?,"
        " reason_code = ?, error_reason = ?, warnings = ?"
        " WHERE run_id = ? AND supplier_id = ?",
        (
            status,
            parsed_items_count,
            reason_code,
            error_reason,
            json.dumps(warnings or [], ensure_ascii=False),
            run_id,
            supplier_id,
        ),
    )


# The button «прийняти новий обсяг» (REQ-F-031): "частково" in the supplier's last
# run that has a status for it; a later run where its data is not written yet
# does not remove the button.
_AVAILABLE = (
    "(s.status = 'partial' AND NOT EXISTS (SELECT 1 FROM supplier_run_statuses s2"
    " WHERE s2.supplier_id = s.supplier_id AND s2.status IS NOT NULL"
    " AND s2.run_id > s.run_id))"
)


def supplier_statuses(
    conn: sqlite3.Connection, run_ids: list[int]
) -> dict[int, list[StatusRow]]:
    """Supplier rows of the runs, keyed by run id (any order inside)."""
    found: dict[int, list[StatusRow]] = {run_id: [] for run_id in run_ids}
    if not run_ids:
        return found
    marks = ", ".join("?" for _ in run_ids)
    rows = conn.execute(
        "SELECT s.run_id, s.supplier_id, p.name, s.status, s.parsed_items_count,"
        f" s.reason_code, s.error_reason, s.warnings, {_AVAILABLE} AS available"
        " FROM supplier_run_statuses s JOIN suppliers p ON p.id = s.supplier_id"
        f" WHERE s.run_id IN ({marks})",
        run_ids,
    ).fetchall()
    for r in rows:
        found[r["run_id"]].append(
            StatusRow(
                r["run_id"],
                r["supplier_id"],
                r["name"],
                r["status"],
                r["parsed_items_count"],
                r["reason_code"],
                r["error_reason"],
                json.loads(r["warnings"]),
                bool(r["available"]),
            )
        )
    return found


def status_of(
    conn: sqlite3.Connection, run_id: int, supplier_id: int
) -> StatusRow | None:
    return next(
        (
            s
            for s in supplier_statuses(conn, [run_id])[run_id]
            if s.supplier_id == supplier_id
        ),
        None,
    )


def last_update_dates(conn: sqlite3.Connection) -> dict[int, date]:
    """REQ-F-034: per supplier, the price date of its last "успіх" or "частково"."""
    rows = conn.execute(
        "SELECT s.supplier_id, MAX(r.price_date) AS last_date"
        " FROM supplier_run_statuses s JOIN runs r ON r.id = s.run_id"
        " WHERE s.status IN ('success', 'partial') GROUP BY s.supplier_id"
    ).fetchall()
    return {r["supplier_id"]: date.fromisoformat(r["last_date"]) for r in rows}


# --- the run log (Д.7а) ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcceptanceRow:
    id: int
    run_id: int
    supplier_id: int
    supplier_name: str
    accepted_by: str
    accepted_at: datetime
    volume_baseline: int


@dataclass(frozen=True, slots=True)
class LogEntryRow:
    id: int
    kind: str
    occurred_at: datetime
    trigger: str | None
    run_id: int | None
    volume_acceptance_id: int | None


def insert_log_entry(
    conn: sqlite3.Connection,
    *,
    kind: str,
    occurred_at: datetime,
    day: date,
    trigger: str | None = None,
    run_id: int | None = None,
    volume_acceptance_id: int | None = None,
    counts_as_scheduled: bool = False,
) -> int:
    cur = conn.execute(
        "INSERT INTO run_log_entries (kind, occurred_at, day, trigger, run_id,"
        " volume_acceptance_id, counts_as_scheduled) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            kind,
            moment_text(occurred_at),
            day.isoformat(),
            trigger,
            run_id,
            volume_acceptance_id,
            int(counts_as_scheduled),
        ),
    )
    return int(cur.lastrowid)


def day_has_scheduled_run(conn: sqlite3.Connection, day: date) -> bool:
    """REQ-F-055: the day's scheduled run is used up (by a run, a catch-up for a
    missed time, "пропущено", "немає активних постачальників" or a time changed
    to one already past)."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM run_log_entries"
        " WHERE day = ? AND counts_as_scheduled = 1)"
        " OR EXISTS (SELECT 1 FROM schedule_waivers WHERE day = ?)",
        (day.isoformat(), day.isoformat()),
    ).fetchone()
    return bool(row[0])


def set_schedule_waiver(conn: sqlite3.Connection, day: date, waived: bool) -> None:
    if waived:
        conn.execute(
            "INSERT OR IGNORE INTO schedule_waivers (day) VALUES (?)",
            (day.isoformat(),),
        )
    else:
        conn.execute("DELETE FROM schedule_waivers WHERE day = ?", (day.isoformat(),))


def count_log_entries(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM run_log_entries").fetchone()[0]


_ENTRY_SELECT = (
    "SELECT id, kind, occurred_at, trigger, run_id, volume_acceptance_id"
    " FROM run_log_entries"
)


def _entry(r: sqlite3.Row) -> LogEntryRow:
    return LogEntryRow(
        r["id"],
        r["kind"],
        moment(r["occurred_at"]),
        r["trigger"],
        r["run_id"],
        r["volume_acceptance_id"],
    )


def log_entries(
    conn: sqlite3.Connection, *, limit: int, offset: int
) -> list[LogEntryRow]:
    """Entries newest first (REQ-F-057); the same moment — the later entry first."""
    rows = conn.execute(
        f"{_ENTRY_SELECT} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [_entry(r) for r in rows]


def get_log_entry(conn: sqlite3.Connection, entry_id: int) -> LogEntryRow:
    return _entry(conn.execute(f"{_ENTRY_SELECT} WHERE id = ?", (entry_id,)).fetchone())


def runs_by_id(conn: sqlite3.Connection, run_ids: list[int]) -> dict[int, RunRow]:
    if not run_ids:
        return {}
    marks = ", ".join("?" for _ in run_ids)
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE id IN ({marks})", run_ids
    ).fetchall()
    return {r["id"]: _run(r) for r in rows}


def insert_acceptance(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    supplier_id: int,
    accepted_by: str,
    accepted_at: datetime,
    volume_baseline: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO volume_acceptances (run_id, supplier_id, accepted_by,"
        " accepted_at, volume_baseline) VALUES (?, ?, ?, ?, ?)",
        (run_id, supplier_id, accepted_by, moment_text(accepted_at), volume_baseline),
    )
    return int(cur.lastrowid)


def acceptances_by_id(
    conn: sqlite3.Connection, ids: list[int]
) -> dict[int, AcceptanceRow]:
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT a.id, a.run_id, a.supplier_id, p.name, a.accepted_by, a.accepted_at,"
        " a.volume_baseline FROM volume_acceptances a"
        f" JOIN suppliers p ON p.id = a.supplier_id WHERE a.id IN ({marks})",
        ids,
    ).fetchall()
    return {
        r["id"]: AcceptanceRow(
            r["id"],
            r["run_id"],
            r["supplier_id"],
            r["name"],
            r["accepted_by"],
            moment(r["accepted_at"]),
            r["volume_baseline"],
        )
        for r in rows
    }


# --- volume base and the feed state of items ------------------------------------------------


def volume_base(conn: sqlite3.Connection, supplier_id: int) -> int | None:
    row = conn.execute(
        "SELECT volume_base FROM suppliers WHERE id = ?", (supplier_id,)
    ).fetchone()
    return row["volume_base"] if row is not None else None


def set_volume_base(conn: sqlite3.Connection, supplier_id: int, base: int) -> None:
    conn.execute(
        "UPDATE suppliers SET volume_base = ? WHERE id = ?", (base, supplier_id)
    )


def restart_absence_count(conn: sqlite3.Connection, supplier_id: int) -> None:
    """REQ-F-047: after accepting a new volume the count starts again."""
    conn.execute(
        "UPDATE supplier_items SET absence_before = 0, absence_date = NULL,"
        " absence_on_date = 0, absence_by_success = 0 WHERE supplier_id = ?",
        (supplier_id,),
    )


def reset_item_feed(conn: sqlite3.Connection, item_id: int) -> None:
    """REQ-F-045, REQ-F-047: a new link, a relink or an unlink — no feed base,
    the absence count and the mark "зник" start again."""
    conn.execute(
        "UPDATE supplier_items SET feed_base = NULL, absence_before = 0,"
        " absence_date = NULL, absence_on_date = 0, absence_by_success = 0,"
        " disappeared = 0 WHERE id = ?",
        (item_id,),
    )


def last_price_without_mark(
    conn: sqlite3.Connection, item_id: int, material_id: int
) -> Decimal | None:
    """The last daily price of the item for the material without the mark
    «одиниця не збігається» (REQ-F-051, REQ-F-056)."""
    row = conn.execute(
        "SELECT price FROM daily_prices WHERE supplier_item_id = ?"
        " AND material_id = ? AND unit_mismatch = 0"
        " ORDER BY price_date DESC, id DESC LIMIT 1",
        (item_id, material_id),
    ).fetchone()
    return Decimal(row["price"]) if row is not None else None


def rebase_item_feed(
    conn: sqlite3.Connection, item_id: int, material_id: int | None
) -> None:
    """The feed base becomes the last price without the mark for the material
    (none — no base); the absence count and the mark "зник" start again."""
    base = (
        last_price_without_mark(conn, item_id, material_id)
        if material_id is not None
        else None
    )
    conn.execute(
        "UPDATE supplier_items SET feed_base = ?, absence_before = 0,"
        " absence_date = NULL, absence_on_date = 0, absence_by_success = 0,"
        " disappeared = 0 WHERE id = ?",
        (str(base) if base is not None else None, item_id),
    )


def rebase_material_feed(conn: sqlite3.Connection, material_id: int) -> None:
    """REQ-F-051: activation of a material, for each of its linked items."""
    rows = conn.execute(
        "SELECT id FROM supplier_items WHERE material_id = ?", (material_id,)
    ).fetchall()
    for r in rows:
        rebase_item_feed(conn, r["id"], material_id)


def reset_supplier_feed(conn: sqlite3.Connection, supplier_id: int) -> None:
    """REQ-F-056: activation of a supplier, a new catalogue address or parser —
    no volume base, and every item of the supplier is rebased."""
    conn.execute("UPDATE suppliers SET volume_base = NULL WHERE id = ?", (supplier_id,))
    rows = conn.execute(
        "SELECT id, material_id FROM supplier_items WHERE supplier_id = ?",
        (supplier_id,),
    ).fetchall()
    for r in rows:
        rebase_item_feed(conn, r["id"], r["material_id"])


@dataclass(slots=True)
class FeedState:
    """The feed state of an item (Д.3): base, absences, the mark "зник".

    The absence count is kept per date (REQ-F-047): ``before`` is the count
    from earlier dates, ``on_date`` the last date that changed it,
    ``absent`` whether the item is absent on that date and ``by_success``
    whether a run with status "успіх" decided it.
    """

    item_id: int
    base: Decimal | None
    before: int
    on_date: date | None
    absent: bool
    by_success: bool
    disappeared: bool

    @property
    def absences(self) -> int:
        if self.on_date is None or not self.absent:
            return 0
        return self.before + 1


def upsert_item(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    sku: str,
    name: str,
    unit: str,
    seen: date,
) -> int:
    """Create the item or update its name, unit and last seen date (REQ-F-012)."""
    row = conn.execute(
        "SELECT id FROM supplier_items WHERE supplier_id = ? AND sku = ?",
        (supplier_id, sku),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO supplier_items (supplier_id, sku, name, unit, last_seen_date)"
            " VALUES (?, ?, ?, ?, ?)",
            (supplier_id, sku, name, unit, seen.isoformat()),
        )
        return int(cur.lastrowid)
    conn.execute(
        "UPDATE supplier_items SET name = ?, unit = ?, last_seen_date = ? WHERE id = ?",
        (name, unit, seen.isoformat(), row["id"]),
    )
    return int(row["id"])


def feed_state(conn: sqlite3.Connection, item_id: int) -> FeedState:
    r = conn.execute(
        "SELECT feed_base, absence_before, absence_date, absence_on_date,"
        " absence_by_success, disappeared FROM supplier_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    return FeedState(
        item_id,
        _decimal(r["feed_base"]),
        r["absence_before"],
        _date(r["absence_date"]),
        bool(r["absence_on_date"]),
        bool(r["absence_by_success"]),
        bool(r["disappeared"]),
    )


def save_feed_state(conn: sqlite3.Connection, state: FeedState) -> None:
    conn.execute(
        "UPDATE supplier_items SET feed_base = ?, absence_before = ?,"
        " absence_date = ?, absence_on_date = ?, absence_by_success = ?,"
        " disappeared = ? WHERE id = ?",
        (
            str(state.base) if state.base is not None else None,
            state.before,
            state.on_date.isoformat() if state.on_date is not None else None,
            int(state.absent),
            int(state.by_success),
            int(state.disappeared),
            state.item_id,
        ),
    )


@dataclass(frozen=True, slots=True)
class LinkSnapshot:
    item_id: int
    supplier_id: int
    material_id: int
    material_unit: str
    material_active: bool


def links(conn: sqlite3.Connection) -> list[LinkSnapshot]:
    rows = conn.execute(
        "SELECT i.id, i.supplier_id, m.id AS material_id, m.unit, m.active"
        " FROM supplier_items i JOIN materials m ON m.id = i.material_id"
    ).fetchall()
    return [
        LinkSnapshot(
            r["id"], r["supplier_id"], r["material_id"], r["unit"], bool(r["active"])
        )
        for r in rows
    ]


# --- daily prices (Д.5) and events (Д.6) ----------------------------------------------------


def has_daily_price(conn: sqlite3.Connection, item_id: int, day: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM daily_prices WHERE supplier_item_id = ? AND price_date = ?",
        (item_id, day.isoformat()),
    ).fetchone()
    return row is not None


def put_daily_price(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    day: date,
    price: Decimal,
    unit: str,
    material_id: int,
    unit_mismatch: bool,
) -> None:
    """REQ-F-028: one price per item and date; a new price replaces the record."""
    conn.execute(
        "DELETE FROM daily_prices WHERE supplier_item_id = ? AND price_date = ?",
        (item_id, day.isoformat()),
    )
    conn.execute(
        "INSERT INTO daily_prices (supplier_item_id, price_date, price, unit,"
        " material_id, unit_mismatch) VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, day.isoformat(), str(price), unit, material_id, int(unit_mismatch)),
    )


def insert_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    event_date: date,
    created_at: datetime,
    material_id: int,
    supplier_id: int,
    item_id: int,
    old_price: Decimal | None = None,
    new_price: Decimal | None = None,
    change_percent: Decimal | None = None,
    price: Decimal | None = None,
) -> None:
    def text(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    conn.execute(
        "INSERT INTO events (kind, event_date, created_at, material_id, supplier_id,"
        " supplier_item_id, old_price, new_price, change_percent, price)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            kind,
            event_date.isoformat(),
            to_kyiv(created_at).isoformat(),  # Д.6: Kyiv time of creation
            material_id,
            supplier_id,
            item_id,
            text(old_price),
            text(new_price),
            text(change_percent),
            text(price),
        ),
    )


@dataclass(frozen=True, slots=True)
class DailyPriceRow:
    supplier_item_id: int
    material_id: int
    price_date: date
    price: Decimal
    unit: str
    unit_mismatch: bool


@dataclass(frozen=True, slots=True)
class EventRow:
    kind: str
    event_date: date
    created_at: datetime
    material_id: int
    supplier_id: int
    supplier_item_id: int
    old_price: Decimal | None
    new_price: Decimal | None
    change_percent: Decimal | None
    price: Decimal | None


def all_daily_prices(conn: sqlite3.Connection) -> list[DailyPriceRow]:
    rows = conn.execute(
        "SELECT supplier_item_id, material_id, price_date, price, unit, unit_mismatch"
        " FROM daily_prices ORDER BY id"
    ).fetchall()
    return [
        DailyPriceRow(
            r["supplier_item_id"],
            r["material_id"],
            date.fromisoformat(r["price_date"]),
            Decimal(r["price"]),
            r["unit"],
            bool(r["unit_mismatch"]),
        )
        for r in rows
    ]


def all_events(conn: sqlite3.Connection) -> list[EventRow]:
    rows = conn.execute(
        "SELECT kind, event_date, created_at, material_id, supplier_id,"
        " supplier_item_id, old_price, new_price, change_percent, price"
        " FROM events ORDER BY id"
    ).fetchall()
    return [
        EventRow(
            r["kind"],
            date.fromisoformat(r["event_date"]),
            datetime.fromisoformat(r["created_at"]),
            r["material_id"],
            r["supplier_id"],
            r["supplier_item_id"],
            _decimal(r["old_price"]),
            _decimal(r["new_price"]),
            _decimal(r["change_percent"]),
            _decimal(r["price"]),
        )
        for r in rows
    ]

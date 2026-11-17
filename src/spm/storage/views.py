"""Read queries of the views: comparison, history, the feed and the items that
need attention (block B3).

Every function takes an open connection from ``Database.transaction``. Rows are
returned unordered unless stated; ordering by the alphabet (REQ-F-057) is done
in ``services``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# --- comparison (REQ-F-035…REQ-F-038, REQ-F-065) -------------------------------------------


@dataclass(frozen=True, slots=True)
class LinkedPriceRow:
    """A daily price of an item for the material it is linked to now; an item
    without such prices has one row with ``price_date`` None."""

    material_id: int
    item_id: int
    supplier_id: int
    supplier_name: str
    supplier_active: bool
    price_date: date | None
    price: Decimal | None
    unit_mismatch: bool


def linked_prices(
    conn: sqlite3.Connection, material_ids: list[int] | None = None
) -> list[LinkedPriceRow]:
    """Prices of items linked now, for their current material (REQ-F-036)."""
    sql = (
        "SELECT i.material_id, i.id AS item_id, s.id AS supplier_id, s.name,"
        " s.active, p.price_date, p.price, p.unit_mismatch"
        " FROM supplier_items i JOIN suppliers s ON s.id = i.supplier_id"
        " LEFT JOIN daily_prices p"
        " ON p.supplier_item_id = i.id AND p.material_id = i.material_id"
        " WHERE i.material_id IS NOT NULL"
    )
    params: list[int] = []
    if material_ids is not None:
        if not material_ids:
            # Still touch the tables, so a broken storage fails the same way.
            sql += " AND 0"
        else:
            sql += f" AND i.material_id IN ({', '.join('?' for _ in material_ids)})"
            params = material_ids
    rows = conn.execute(sql, params).fetchall()
    return [
        LinkedPriceRow(
            r["material_id"],
            r["item_id"],
            r["supplier_id"],
            r["name"],
            bool(r["active"]),
            date.fromisoformat(r["price_date"]) if r["price_date"] else None,
            Decimal(r["price"]) if r["price"] is not None else None,
            bool(r["unit_mismatch"]),
        )
        for r in rows
    ]


# --- history (REQ-F-040, REQ-F-016) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HistoryPriceRow:
    id: int
    supplier_id: int
    supplier_name: str
    price_date: date
    price: Decimal
    unit_mismatch: bool


def material_prices(
    conn: sqlite3.Connection, material_id: int
) -> list[HistoryPriceRow]:
    """Every daily price stored for the material, of any supplier and item."""
    rows = conn.execute(
        "SELECT p.id, s.id AS supplier_id, s.name, p.price_date, p.price,"
        " p.unit_mismatch FROM daily_prices p"
        " JOIN supplier_items i ON i.id = p.supplier_item_id"
        " JOIN suppliers s ON s.id = i.supplier_id WHERE p.material_id = ?",
        (material_id,),
    ).fetchall()
    return [
        HistoryPriceRow(
            r["id"],
            r["supplier_id"],
            r["name"],
            date.fromisoformat(r["price_date"]),
            Decimal(r["price"]),
            bool(r["unit_mismatch"]),
        )
        for r in rows
    ]


# --- the feed (REQ-F-042, REQ-F-057, REQ-F-058) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class FeedEventRow:
    id: int
    kind: str
    event_date: date
    created_at: datetime
    material_id: int
    material_name: str
    supplier_id: int
    supplier_name: str
    old_price: Decimal | None
    new_price: Decimal | None
    change_percent: Decimal | None
    price: Decimal | None


def _decimal(text: str | None) -> Decimal | None:
    return Decimal(text) if text is not None else None


def feed_events(
    conn: sqlite3.Connection,
    *,
    material_id: int | None = None,
    supplier_id: int | None = None,
    kind: str | None = None,
) -> list[FeedEventRow]:
    """Events matching the filters, in any order."""
    sql = (
        "SELECT e.id, e.kind, e.event_date, e.created_at, m.id AS material_id,"
        " m.name AS material_name, s.id AS supplier_id, s.name AS supplier_name,"
        " e.old_price, e.new_price, e.change_percent, e.price FROM events e"
        " JOIN materials m ON m.id = e.material_id"
        " JOIN suppliers s ON s.id = e.supplier_id WHERE 1 = 1"
    )
    params: list[object] = []
    for column, value in (
        ("e.material_id", material_id),
        ("e.supplier_id", supplier_id),
        ("e.kind", kind),
    ):
        if value is not None:
            sql += f" AND {column} = ?"
            params.append(value)
    rows = conn.execute(sql, params).fetchall()
    return [
        FeedEventRow(
            r["id"],
            r["kind"],
            date.fromisoformat(r["event_date"]),
            datetime.fromisoformat(r["created_at"]),
            r["material_id"],
            r["material_name"],
            r["supplier_id"],
            r["supplier_name"],
            _decimal(r["old_price"]),
            _decimal(r["new_price"]),
            _decimal(r["change_percent"]),
            _decimal(r["price"]),
        )
        for r in rows
    ]


# --- items that need attention (REQ-F-017, REQ-F-066, REQ-F-068) ------------------------------


@dataclass(frozen=True, slots=True)
class MismatchRow:
    item_id: int
    supplier_id: int
    supplier_name: str
    supplier_active: bool
    sku: str
    name: str
    unit: str
    material_id: int
    material_name: str
    material_unit: str
    last_unit_mismatch_date: date


def linked_items_with_marked_prices(conn: sqlite3.Connection) -> list[MismatchRow]:
    """Linked items with a daily price "одиниця не збігається" for their current
    material, with the date of the last such price."""
    rows = conn.execute(
        "SELECT i.id, s.id AS supplier_id, s.name AS supplier_name, s.active,"
        " i.sku, i.name, i.unit, m.id AS material_id, m.name AS material_name,"
        " m.unit AS material_unit, MAX(p.price_date) AS last_date"
        " FROM supplier_items i JOIN suppliers s ON s.id = i.supplier_id"
        " JOIN materials m ON m.id = i.material_id"
        " JOIN daily_prices p ON p.supplier_item_id = i.id"
        " AND p.material_id = i.material_id AND p.unit_mismatch = 1"
        " GROUP BY i.id"
    ).fetchall()
    return [
        MismatchRow(
            r["id"],
            r["supplier_id"],
            r["supplier_name"],
            bool(r["active"]),
            r["sku"],
            r["name"],
            r["unit"],
            r["material_id"],
            r["material_name"],
            r["material_unit"],
            date.fromisoformat(r["last_date"]),
        )
        for r in rows
    ]

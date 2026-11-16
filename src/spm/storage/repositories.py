"""Repositories: reading and writing rows inside a transaction.

Every function takes an open connection from ``Database.transaction``; the
caller decides where the transaction begins and ends.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

# --- accounts and sessions (Д.10) ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccountRow:
    id: int
    login: str
    role: str
    password_hash: str


def _account(row: sqlite3.Row | None) -> AccountRow | None:
    if row is None:
        return None
    return AccountRow(row["id"], row["login"], row["role"], row["password_hash"])


def find_account_by_login(conn: sqlite3.Connection, login: str) -> AccountRow | None:
    """The login is compared without regard to case (the column is NOCASE)."""
    row = conn.execute(
        "SELECT id, login, role, password_hash FROM accounts WHERE login = ?",
        (login,),
    ).fetchone()
    return _account(row)


def insert_account(
    conn: sqlite3.Connection, login: str, role: str, password_hash: str
) -> int:
    cur = conn.execute(
        "INSERT INTO accounts (login, role, password_hash) VALUES (?, ?, ?)",
        (login, role, password_hash),
    )
    return int(cur.lastrowid)


@dataclass(frozen=True, slots=True)
class SessionRow:
    id: int
    account: AccountRow
    last_seen_at: str


def find_session(conn: sqlite3.Connection, token_hash: str) -> SessionRow | None:
    row = conn.execute(
        "SELECT s.id, s.last_seen_at, a.id AS account_id, a.login, a.role,"
        " a.password_hash"
        " FROM sessions s JOIN accounts a ON a.id = s.account_id"
        " WHERE s.token_hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    account = AccountRow(
        row["account_id"], row["login"], row["role"], row["password_hash"]
    )
    return SessionRow(row["id"], account, row["last_seen_at"])


def insert_session(
    conn: sqlite3.Connection, token_hash: str, account_id: int, last_seen_at: str
) -> None:
    conn.execute(
        "INSERT INTO sessions (token_hash, account_id, last_seen_at) VALUES (?, ?, ?)",
        (token_hash, account_id, last_seen_at),
    )


def touch_session(conn: sqlite3.Connection, session_id: int, last_seen_at: str) -> None:
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (last_seen_at, session_id)
    )


def delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# --- suppliers (Д.1) ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierRow:
    id: int
    name: str
    catalog_url: str
    parser: str
    active: bool


_SUPPLIER_COLUMNS = "id, name, catalog_url, parser, active"


def _supplier(row: sqlite3.Row) -> SupplierRow:
    return SupplierRow(
        row["id"], row["name"], row["catalog_url"], row["parser"], bool(row["active"])
    )


def all_suppliers(conn: sqlite3.Connection) -> list[SupplierRow]:
    rows = conn.execute(f"SELECT {_SUPPLIER_COLUMNS} FROM suppliers").fetchall()
    return [_supplier(r) for r in rows]


def get_supplier(conn: sqlite3.Connection, supplier_id: int) -> SupplierRow | None:
    row = conn.execute(
        f"SELECT {_SUPPLIER_COLUMNS} FROM suppliers WHERE id = ?", (supplier_id,)
    ).fetchone()
    return _supplier(row) if row is not None else None


def find_supplier_by_name_key(
    conn: sqlite3.Connection, name_key: str
) -> SupplierRow | None:
    row = conn.execute(
        f"SELECT {_SUPPLIER_COLUMNS} FROM suppliers WHERE name_key = ?", (name_key,)
    ).fetchone()
    return _supplier(row) if row is not None else None


def insert_supplier(
    conn: sqlite3.Connection,
    *,
    name: str,
    name_key: str,
    catalog_url: str,
    parser: str,
    active: bool,
) -> int:
    cur = conn.execute(
        "INSERT INTO suppliers (name, name_key, catalog_url, parser, active)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, name_key, catalog_url, parser, int(active)),
    )
    return int(cur.lastrowid)


def update_supplier(
    conn: sqlite3.Connection,
    supplier_id: int,
    *,
    name: str,
    name_key: str,
    catalog_url: str,
    parser: str,
    active: bool,
) -> None:
    conn.execute(
        "UPDATE suppliers SET name = ?, name_key = ?, catalog_url = ?, parser = ?,"
        " active = ? WHERE id = ?",
        (name, name_key, catalog_url, parser, int(active), supplier_id),
    )


# --- materials (Д.2) ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaterialRow:
    id: int
    name: str
    unit: str
    active: bool
    linked_items_count: int


_MATERIAL_SELECT = (
    "SELECT m.id, m.name, m.unit, m.active,"
    " (SELECT COUNT(*) FROM supplier_items i WHERE i.material_id = m.id)"
    " AS linked_items_count FROM materials m"
)


def _material(row: sqlite3.Row) -> MaterialRow:
    return MaterialRow(
        row["id"],
        row["name"],
        row["unit"],
        bool(row["active"]),
        int(row["linked_items_count"]),
    )


def all_materials(conn: sqlite3.Connection) -> list[MaterialRow]:
    return [_material(r) for r in conn.execute(_MATERIAL_SELECT).fetchall()]


def get_material(conn: sqlite3.Connection, material_id: int) -> MaterialRow | None:
    row = conn.execute(f"{_MATERIAL_SELECT} WHERE m.id = ?", (material_id,)).fetchone()
    return _material(row) if row is not None else None


def find_material_by_name_key(
    conn: sqlite3.Connection, name_key: str
) -> MaterialRow | None:
    row = conn.execute(
        f"{_MATERIAL_SELECT} WHERE m.name_key = ?", (name_key,)
    ).fetchone()
    return _material(row) if row is not None else None


def insert_material(
    conn: sqlite3.Connection, *, name: str, name_key: str, unit: str, active: bool
) -> int:
    cur = conn.execute(
        "INSERT INTO materials (name, name_key, unit, active) VALUES (?, ?, ?, ?)",
        (name, name_key, unit, int(active)),
    )
    return int(cur.lastrowid)


def update_material(
    conn: sqlite3.Connection,
    material_id: int,
    *,
    name: str,
    name_key: str,
    unit: str,
    active: bool,
) -> None:
    conn.execute(
        "UPDATE materials SET name = ?, name_key = ?, unit = ?, active = ?"
        " WHERE id = ?",
        (name, name_key, unit, int(active), material_id),
    )


def material_has_daily_prices(conn: sqlite3.Connection, material_id: int) -> bool:
    """Daily prices (Д.5) are written by update runs, block B2; none exist yet."""
    return False


# --- supplier items and links (Д.3, Д.4) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierItemRow:
    id: int
    supplier: SupplierRow
    sku: str
    name: str
    unit: str
    last_seen_date: date
    material_id: int | None


_ITEM_SELECT = (
    "SELECT i.id, i.sku, i.name, i.unit, i.last_seen_date, i.material_id,"
    " s.id AS supplier_id, s.name AS supplier_name, s.catalog_url, s.parser,"
    " s.active AS supplier_active"
    " FROM supplier_items i JOIN suppliers s ON s.id = i.supplier_id"
)


def _item(row: sqlite3.Row) -> SupplierItemRow:
    supplier = SupplierRow(
        row["supplier_id"],
        row["supplier_name"],
        row["catalog_url"],
        row["parser"],
        bool(row["supplier_active"]),
    )
    return SupplierItemRow(
        row["id"],
        supplier,
        row["sku"],
        row["name"],
        row["unit"],
        date.fromisoformat(row["last_seen_date"]),
        row["material_id"],
    )


def get_supplier_item(conn: sqlite3.Connection, item_id: int) -> SupplierItemRow | None:
    row = conn.execute(f"{_ITEM_SELECT} WHERE i.id = ?", (item_id,)).fetchone()
    return _item(row) if row is not None else None


def unlinked_items(conn: sqlite3.Connection) -> list[SupplierItemRow]:
    rows = conn.execute(f"{_ITEM_SELECT} WHERE i.material_id IS NULL").fetchall()
    return [_item(r) for r in rows]


def linked_items(conn: sqlite3.Connection, material_id: int) -> list[SupplierItemRow]:
    rows = conn.execute(
        f"{_ITEM_SELECT} WHERE i.material_id = ?", (material_id,)
    ).fetchall()
    return [_item(r) for r in rows]


def item_of_supplier_linked_to(
    conn: sqlite3.Connection, material_id: int, supplier_id: int
) -> SupplierItemRow | None:
    row = conn.execute(
        f"{_ITEM_SELECT} WHERE i.material_id = ? AND i.supplier_id = ?",
        (material_id, supplier_id),
    ).fetchone()
    return _item(row) if row is not None else None


def set_item_material(
    conn: sqlite3.Connection, item_id: int, material_id: int | None
) -> None:
    conn.execute(
        "UPDATE supplier_items SET material_id = ? WHERE id = ?",
        (material_id, item_id),
    )


def insert_supplier_item(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    sku: str,
    name: str,
    unit: str,
    last_seen_date: date,
) -> int:
    cur = conn.execute(
        "INSERT INTO supplier_items (supplier_id, sku, name, unit, last_seen_date)"
        " VALUES (?, ?, ?, ?, ?)",
        (supplier_id, sku, name, unit, last_seen_date.isoformat()),
    )
    return int(cur.lastrowid)


# --- settings (Д.9) -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SettingsRow:
    update_time: str
    notification_threshold_tenths: int


def get_settings(conn: sqlite3.Connection) -> SettingsRow:
    row = conn.execute(
        "SELECT update_time, notification_threshold_tenths FROM settings WHERE id = 1"
    ).fetchone()
    return SettingsRow(row["update_time"], row["notification_threshold_tenths"])


def save_settings(conn: sqlite3.Connection, settings: SettingsRow) -> None:
    conn.execute(
        "UPDATE settings SET update_time = ?, notification_threshold_tenths = ?"
        " WHERE id = 1",
        (settings.update_time, settings.notification_threshold_tenths),
    )

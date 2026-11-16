"""Database schema.

Block B1.1 created the accounts table (data dictionary Д.10); block B1.2 adds
sessions, suppliers (Д.1), materials (Д.2), supplier items with their link to a
material (Д.3, Д.4) and settings (Д.9). No account is created here: accounts
come only from the set-up command (REQ-F-006, REQ-NF-022).

SQLite ``COLLATE NOCASE`` folds only ASCII letters, so names that must be unique
without regard to case (REQ-F-007, REQ-F-008) keep a folded copy in ``name_key``.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

DEFAULT_UPDATE_TIME = "03:30"  # REQ-F-043
DEFAULT_THRESHOLD_TENTHS = 10  # 1 %, REQ-F-043

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL CHECK (role IN ('manager', 'admin')),
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL REFERENCES accounts (id),
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    catalog_url TEXT NOT NULL,
    parser TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    unit TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS supplier_items (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    last_seen_date TEXT NOT NULL,
    material_id INTEGER REFERENCES materials (id),
    UNIQUE (supplier_id, sku)
);

-- REQ-F-048: one item of each supplier per material.
CREATE UNIQUE INDEX IF NOT EXISTS supplier_items_one_per_material
    ON supplier_items (material_id, supplier_id) WHERE material_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    update_time TEXT NOT NULL,
    notification_threshold_tenths INTEGER NOT NULL
        CHECK (notification_threshold_tenths BETWEEN 1 AND 500)
);

INSERT OR IGNORE INTO settings (id, update_time, notification_threshold_tenths)
    VALUES (1, '{DEFAULT_UPDATE_TIME}', {DEFAULT_THRESHOLD_TENTHS});
"""


def init_database(path: Path) -> None:
    """Create the database file and the schema if they do not exist yet."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.commit()

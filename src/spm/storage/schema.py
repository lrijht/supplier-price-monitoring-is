"""Database schema.

Block B1.1 created the accounts table (data dictionary Д.10); block B1.2 adds
sessions, suppliers (Д.1), materials (Д.2), supplier items with their link to a
material (Д.3, Д.4) and settings (Д.9). Block B2 adds update runs and their
supplier statuses (Д.7, Д.8), the run log (Д.7а), daily prices (Д.5), events
(Д.6), the volume base of a supplier and the feed state of an item. No account
is created here: accounts come only from the set-up command (REQ-F-006,
REQ-NF-022).

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
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    volume_base INTEGER
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
    feed_base TEXT,
    absence_before INTEGER NOT NULL DEFAULT 0,
    absence_date TEXT,
    absence_on_date INTEGER NOT NULL DEFAULT 0,
    absence_by_success INTEGER NOT NULL DEFAULT 0,
    disappeared INTEGER NOT NULL DEFAULT 0,
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

-- Kyiv dates on which the update time was changed to a time already past
-- (REQ-F-055): no scheduled run and no catch-up (a) on that day.
CREATE TABLE IF NOT EXISTS schedule_waivers (
    day TEXT PRIMARY KEY
);

-- Moments are stored in UTC, ISO 8601 with microseconds, so text order is time
-- order; Kyiv dates (price date, day of an entry) are stored as YYYY-MM-DD.
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    trigger TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual', 'catch_up')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    started_by TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('in_progress', 'success', 'partial', 'error', 'interrupted')
    ),
    price_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_run_statuses (
    run_id INTEGER NOT NULL REFERENCES runs (id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    status TEXT CHECK (status IN ('success', 'partial', 'error', 'not_finished')),
    parsed_items_count INTEGER,
    reason_code TEXT,
    error_reason TEXT,
    warnings TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, supplier_id)
);

CREATE TABLE IF NOT EXISTS volume_acceptances (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    accepted_by TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    volume_baseline INTEGER NOT NULL
);

-- The run log (REQ-F-033): runs, "пропущено", "немає активних постачальників",
-- accepted volumes. counts_as_scheduled marks what uses up the day's scheduled
-- run (REQ-F-055).
CREATE TABLE IF NOT EXISTS run_log_entries (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (
        kind IN ('run', 'skipped', 'no_active_suppliers', 'volume_acceptance')
    ),
    occurred_at TEXT NOT NULL,
    day TEXT NOT NULL,
    trigger TEXT,
    run_id INTEGER REFERENCES runs (id),
    volume_acceptance_id INTEGER REFERENCES volume_acceptances (id),
    counts_as_scheduled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_prices (
    id INTEGER PRIMARY KEY,
    supplier_item_id INTEGER NOT NULL REFERENCES supplier_items (id),
    price_date TEXT NOT NULL,
    price TEXT NOT NULL,
    unit TEXT NOT NULL,
    material_id INTEGER NOT NULL REFERENCES materials (id),
    unit_mismatch INTEGER NOT NULL CHECK (unit_mismatch IN (0, 1)),
    UNIQUE (supplier_item_id, price_date)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('price_change', 'appeared', 'disappeared')),
    event_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    material_id INTEGER NOT NULL REFERENCES materials (id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    supplier_item_id INTEGER NOT NULL REFERENCES supplier_items (id),
    old_price TEXT,
    new_price TEXT,
    change_percent TEXT,
    price TEXT
);
"""

# Columns added in block B2 to tables of block B1: a database created before
# B2 gets them on start (CREATE TABLE IF NOT EXISTS does not change a table).
_ADDED_COLUMNS = {
    "suppliers": ["volume_base INTEGER"],
    "supplier_items": [
        "feed_base TEXT",
        "absence_before INTEGER NOT NULL DEFAULT 0",
        "absence_date TEXT",
        "absence_on_date INTEGER NOT NULL DEFAULT 0",
        "absence_by_success INTEGER NOT NULL DEFAULT 0",
        "disappeared INTEGER NOT NULL DEFAULT 0",
    ],
}


def _add_missing_columns(db: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column.split()[0] not in present:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")


def init_database(path: Path) -> None:
    """Create the database file and the schema if they do not exist yet."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        _add_missing_columns(db)
        db.commit()

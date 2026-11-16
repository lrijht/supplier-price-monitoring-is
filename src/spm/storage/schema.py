"""Database schema.

Block B1.1 creates only the accounts table (data dictionary Д.10). No account
is created here: accounts come only from the set-up command (REQ-F-006,
REQ-NF-022).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL CHECK (role IN ('manager', 'admin')),
    password_hash TEXT NOT NULL
);
"""


def init_database(path: Path) -> None:
    """Create the database file and the schema if they do not exist yet."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.commit()

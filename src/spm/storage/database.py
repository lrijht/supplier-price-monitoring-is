"""Connections and transactions."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path


class Database:
    """The SQLite database file; every unit of work gets its own connection."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A connection inside one transaction: committed on success,
        rolled back on any exception."""
        with closing(sqlite3.connect(self.path, isolation_level=None)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            # IMMEDIATE takes the write lock up front, so a check and the write
            # that depends on it (unique names, one link per item) cannot
            # interleave with another request.
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

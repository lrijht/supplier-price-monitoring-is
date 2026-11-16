"""SQLite storage: schema, repositories, transactions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from spm.storage import repositories
from spm.storage.database import Database
from spm.storage.schema import init_database

__all__ = ["Database", "add_supplier_item", "init_database", "repositories"]


def add_supplier_item(
    database_path: Path,
    *,
    supplier_id: int,
    sku: str,
    name: str,
    unit: str,
    last_seen_date: date,
) -> int:
    """Create a supplier item without a link and return its id.

    Supplier items come from update runs (block B2); until then this is how
    tests (T-15) put items into storage. No price is written.
    """
    with Database(database_path).transaction() as conn:
        return repositories.insert_supplier_item(
            conn,
            supplier_id=supplier_id,
            sku=sku,
            name=name,
            unit=unit,
            last_seen_date=last_seen_date,
        )

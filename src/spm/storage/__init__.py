"""SQLite storage: schema, repositories, transactions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from spm.storage import repositories, updates, views
from spm.storage.database import Database
from spm.storage.schema import init_database
from spm.storage.updates import DailyPriceRow, EventRow

__all__ = [
    "Database",
    "DailyPriceRow",
    "EventRow",
    "add_supplier_item",
    "daily_prices",
    "events",
    "init_database",
    "repositories",
    "updates",
    "views",
]


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


def daily_prices(database_path: Path) -> list[DailyPriceRow]:
    """All daily prices (Д.5).

    The history screen is block B3; until then this is how tests read them.
    """
    with Database(database_path).transaction() as conn:
        return updates.all_daily_prices(conn)


def events(database_path: Path) -> list[EventRow]:
    """All events (Д.6) in the order of creation; the feed screen is block B3."""
    with Database(database_path).transaction() as conn:
        return updates.all_events(conn)

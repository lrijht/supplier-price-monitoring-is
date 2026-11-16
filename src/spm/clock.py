"""Clock: the system clock in production, a controlled clock in tests.

Kyiv local time (with the summer time switch) is derived from the clock's
moment, so tests can move time without waiting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


class Clock(Protocol):
    def now(self) -> datetime:
        """Current moment, timezone-aware."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """A clock that moves only when told to."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("ManualClock needs a timezone-aware start moment")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("ManualClock moves only forward")
        self._now += delta


def to_kyiv(moment: datetime) -> datetime:
    return moment.astimezone(KYIV)

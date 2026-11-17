"""Clock: the system clock in production, a controlled clock in tests.

Kyiv local time (with the summer time switch) is derived from the clock's
moment, so tests can move time without waiting. The scheduled moment of a day
(REQ-F-018, REQ-F-054) is computed here too.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
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


def kyiv_date(moment: datetime) -> date:
    return moment.astimezone(KYIV).date()


# The spring switch moves the clocks by one hour; a wider search is a guard.
_MAX_GAP = timedelta(hours=3)


def _exists(wall: datetime) -> bool:
    back = wall.replace(tzinfo=KYIV).astimezone(UTC).astimezone(KYIV)
    return back.replace(tzinfo=None) == wall


def scheduled_moment(day: date, update_time: str) -> datetime:
    """The moment of ``update_time`` (ГГ:ХХ) on the Kyiv ``day``, in UTC.

    A time that does not exist that day (spring switch) moves to the first
    minute after the switch; a time that comes twice (autumn) is its first
    occurrence (REQ-F-054).
    """
    hours, minutes = (int(part) for part in update_time.split(":"))
    wall = datetime.combine(day, time(hours, minutes))
    limit = wall + _MAX_GAP
    while not _exists(wall) and wall < limit:
        wall += timedelta(minutes=1)
    return wall.replace(tzinfo=KYIV, fold=0).astimezone(UTC)

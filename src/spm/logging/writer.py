"""JSON Lines log file writer.

Every record is one line of JSON with the common fields (Р-126): time with the
Kyiv offset, level, event code, login, role, request identifier, result; event
fields follow. A failed write is swallowed (REQ-NF-033, Р-127).
"""

from __future__ import annotations

import json
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from spm.clock import Clock, to_kyiv

_request_id: ContextVar[str | None] = ContextVar("spm_request_id", default=None)


def current_request_id() -> str | None:
    """Identifier of the HTTP request being served, if any."""
    return _request_id.get()


def set_request_id(value: str | None):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


class JsonLinesLog:
    def __init__(self, path: Path, clock: Clock) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def write(
        self,
        *,
        level: str,
        event: str,
        result: str | None = None,
        login: str | None = None,
        role: str | None = None,
        **fields: Any,
    ) -> None:
        """Append one record; never raises (REQ-NF-033)."""
        try:
            record: dict[str, Any] = {
                "time": to_kyiv(self._clock.now()).isoformat(timespec="seconds"),
                "level": level,
                "event": event,
                "login": login,
                "role": role,
                "request_id": current_request_id(),
                "result": result,
            }
            record.update(fields)
            line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as file:
                    file.write(line)
        except Exception:  # noqa: BLE001 - a log failure must not change the action
            pass

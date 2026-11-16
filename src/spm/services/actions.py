"""Who acts, and the action log records of state changes (REQ-NF-032)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Actor:
    """The user on whose behalf a service acts."""

    login: str
    role: str


class ActionLog(Protocol):
    def write(self, *, level: str, event: str, **fields: object) -> None: ...


class ActionRecorder:
    """Writes one record per state-changing action: success or rejected."""

    def __init__(self, log: ActionLog) -> None:
        self._log = log

    def success(
        self, actor: Actor, action: str, object_type: str, object_id: int | None
    ) -> None:
        self._log.write(
            level="info",
            event=action,
            result="success",
            login=actor.login,
            role=actor.role,
            object_type=object_type,
            object_id=object_id,
        )

    def rejected(
        self,
        actor: Actor,
        action: str,
        object_type: str,
        object_id: int | None,
        reason_code: str,
    ) -> None:
        self._log.write(
            level="warning",
            event=action,
            result="rejected",
            login=actor.login,
            role=actor.role,
            object_type=object_type,
            object_id=object_id,
            reason_code=reason_code,
        )

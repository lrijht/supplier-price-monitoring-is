"""Settings: daily update time and notification threshold (REQ-F-019, REQ-F-043).

The threshold is kept in tenths of a percent, so the step 0.1 is exact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from spm.services.actions import ActionRecorder, Actor
from spm.services.errors import (
    REQUIRED,
    THRESHOLD_OUT_OF_RANGE,
    UPDATE_TIME_INVALID,
    FieldError,
    ValidationFailed,
)
from spm.storage import Database, repositories

SETTINGS = "settings"
UPDATE_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
MIN_TENTHS, MAX_TENTHS = 1, 500  # 0.1 … 50 %


@dataclass(frozen=True, slots=True)
class Settings:
    update_time: str
    threshold_tenths: int

    @property
    def threshold(self) -> int | float:
        """The threshold in percent as a number: 1, 0.5, 2.5."""
        whole, tenth = divmod(self.threshold_tenths, 10)
        return whole if tenth == 0 else self.threshold_tenths / 10

    @property
    def threshold_text(self) -> str:
        """The threshold with a decimal comma (REQ-F-019): «1», «0,5»."""
        whole, tenth = divmod(self.threshold_tenths, 10)
        return str(whole) if tenth == 0 else f"{whole},{tenth}"


def threshold_tenths(value: Decimal | str) -> int | None:
    """Tenths of a percent, or None when the value is not 0.1…50 with step 0.1.

    Text accepts both a decimal comma and a point (REQ-F-019).
    """
    if isinstance(value, str):
        try:
            value = Decimal(value.strip().replace(",", "."))
        except InvalidOperation:
            return None
    if not value.is_finite():
        return None
    tenths = value * 10
    if tenths != tenths.to_integral_value():
        return None
    tenths = int(tenths)
    return tenths if MIN_TENTHS <= tenths <= MAX_TENTHS else None


class SettingsService:
    def __init__(self, database: Database, recorder: ActionRecorder) -> None:
        self._db = database
        self._record = recorder

    def get(self) -> Settings:
        with self._db.transaction() as conn:
            row = repositories.get_settings(conn)
        return Settings(row.update_time, row.notification_threshold_tenths)

    def update(
        self,
        actor: Actor,
        *,
        update_time: str | None = None,
        threshold: Decimal | str | None = None,
    ) -> Settings:
        """Change any of the two values; one wrong value saves nothing."""
        errors: list[FieldError] = []
        if threshold is not None:
            if isinstance(threshold, str) and not threshold.strip():
                errors.append(
                    FieldError("notification_threshold", "required", REQUIRED)
                )
            else:
                tenths = threshold_tenths(threshold)
                if tenths is None:
                    errors.append(
                        FieldError(
                            "notification_threshold",
                            "notification_threshold_out_of_range",
                            THRESHOLD_OUT_OF_RANGE,
                        )
                    )
        if update_time is not None and not UPDATE_TIME.fullmatch(update_time):
            errors.append(
                FieldError("update_time", "update_time_invalid", UPDATE_TIME_INVALID)
            )
        if errors:
            self._record.rejected(
                actor, "settings_update", SETTINGS, None, ValidationFailed.code
            )
            raise ValidationFailed(errors)
        with self._db.transaction() as conn:
            current = repositories.get_settings(conn)
            new = repositories.SettingsRow(
                update_time if update_time is not None else current.update_time,
                tenths
                if threshold is not None
                else current.notification_threshold_tenths,
            )
            repositories.save_settings(conn, new)
        self._record.success(actor, "settings_update", SETTINGS, None)
        return Settings(new.update_time, new.notification_threshold_tenths)

    def reject(self, actor: Actor, reason_code: str) -> None:
        """Record a settings request refused before it reached ``update``."""
        self._record.rejected(actor, "settings_update", SETTINGS, None, reason_code)

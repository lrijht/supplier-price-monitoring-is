"""Runs seen by users: the manual run, one run, the run log, the update status
of suppliers, accepting a new volume (REQ-F-020, REQ-F-021, REQ-F-031,
REQ-F-033, REQ-F-034, REQ-F-063).

The run itself is performed by the ``update`` component. Services declare the
port ``RunLauncher``; ``update`` implements it and the implementation is
connected when the application is assembled (docs/architecture.md, section 5),
so services do not depend on ``update``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from spm.clock import Clock, to_kyiv
from spm.services.actions import ActionRecorder, Actor
from spm.services.errors import (
    REFERENCE_NOT_FOUND,
    Conflict,
    FieldError,
    NotFound,
    ServiceError,
    ValidationFailed,
)
from spm.services.ordering import PAGE_SIZE, Page, paginate, sort_by
from spm.storage import Database, repositories, updates

RUN = "run"
VOLUME_ACCEPTANCE = "volume_acceptance"
RUN_IN_PROGRESS = "оновлення вже триває"
VOLUME_ACCEPTANCE_UNAVAILABLE = (
    "Новий обсяг можна прийняти лише в останньому запуску постачальника зі статусом "
    "«частково»."
)


# --- the port that ``update`` implements -------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """What pressing the manual run button gave: a run, the entry «немає
    активних постачальників», or nothing because a run is going (``busy``)."""

    run_id: int | None = None
    log_entry_id: int | None = None
    busy: bool = False


class RunLauncher(Protocol):
    def launch_manual(self, started_by: str) -> LaunchResult:
        """Start a manual run in the background and return at once."""
        ...


# --- read models --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierRef:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class SupplierRunStatus:
    supplier: SupplierRef
    status: str | None
    parsed_items_count: int | None
    reason_code: str | None
    error_reason: str | None
    warnings: list[dict]
    volume_acceptance_available: bool


@dataclass(frozen=True, slots=True)
class Run:
    id: int
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    started_by: str | None
    status: str
    supplier_run_statuses: list[SupplierRunStatus]


@dataclass(frozen=True, slots=True)
class VolumeAcceptance:
    id: int
    run_id: int
    supplier: SupplierRef
    accepted_by: str
    accepted_at: datetime
    volume_baseline: int


@dataclass(frozen=True, slots=True)
class RunLogEntry:
    kind: str
    occurred_at: datetime
    trigger: str | None
    run: Run | None
    volume_acceptance: VolumeAcceptance | None


@dataclass(frozen=True, slots=True)
class SupplierUpdateStatus:
    supplier: SupplierRef
    last_update_date: date | None


def _run(row: updates.RunRow, statuses: list[updates.StatusRow]) -> Run:
    rows = [
        SupplierRunStatus(
            SupplierRef(s.supplier_id, s.supplier_name),
            s.status,
            s.parsed_items_count,
            s.reason_code,
            s.error_reason,
            s.warnings,
            s.volume_acceptance_available,
        )
        for s in statuses
    ]
    return Run(
        row.id,
        row.trigger,
        row.started_at,
        row.finished_at,
        row.started_by,
        row.status,
        sort_by(rows, lambda r: r.supplier.name),  # REQ-F-057, П-29
    )


def _acceptance(row: updates.AcceptanceRow) -> VolumeAcceptance:
    return VolumeAcceptance(
        row.id,
        row.run_id,
        SupplierRef(row.supplier_id, row.supplier_name),
        row.accepted_by,
        row.accepted_at,
        row.volume_baseline,
    )


class Runs:
    def __init__(
        self,
        database: Database,
        recorder: ActionRecorder,
        clock: Clock,
        launcher: RunLauncher,
    ) -> None:
        self._db = database
        self._record = recorder
        self._clock = clock
        self._launcher = launcher

    # --- the manual run (REQ-F-020, REQ-F-021, REQ-F-063) -----------------------------------

    def start_manual(self, actor: Actor) -> Run | RunLogEntry:
        """The started run (``in_progress``) or the entry «немає активних
        постачальників»; a run already going — Conflict ``run_in_progress``."""
        result = self._launcher.launch_manual(actor.login)
        if result.busy:
            self._record.rejected(actor, "manual_run", RUN, None, "run_in_progress")
            raise Conflict("run_in_progress", RUN_IN_PROGRESS)
        self._record.success(actor, "manual_run", RUN, result.run_id)
        if result.run_id is not None:
            return self.get_run(result.run_id)
        return self._entry(result.log_entry_id)

    def _entry(self, entry_id: int | None) -> RunLogEntry:
        with self._db.transaction() as conn:
            return self._entries(conn, [updates.get_log_entry(conn, entry_id)])[0]

    # --- reading -------------------------------------------------------------------------------

    def get_run(self, run_id: int) -> Run:
        with self._db.transaction() as conn:
            row = updates.get_run(conn, run_id)
            if row is None:
                raise NotFound()
            statuses = updates.supplier_statuses(conn, [run_id])[run_id]
        return _run(row, statuses)

    def list_log(self, page: int = 1) -> Page[RunLogEntry]:
        """The run log newest first, 50 entries a page (REQ-F-033, REQ-F-057)."""
        with self._db.transaction() as conn:
            total = updates.count_log_entries(conn)
            rows = updates.log_entries(
                conn, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
            )
            entries = self._entries(conn, rows)
        return Page(
            items=entries,
            page=page,
            total_items=total,
            total_pages=-(-total // PAGE_SIZE),
        )

    @staticmethod
    def _entries(conn, rows: list[updates.LogEntryRow]) -> list[RunLogEntry]:
        run_ids = [r.run_id for r in rows if r.run_id is not None]
        runs = updates.runs_by_id(conn, run_ids)
        statuses = updates.supplier_statuses(conn, run_ids)
        accepted = updates.acceptances_by_id(
            conn, [r.volume_acceptance_id for r in rows if r.volume_acceptance_id]
        )
        entries = []
        for r in rows:
            run = (
                _run(runs[r.run_id], statuses[r.run_id])
                if r.run_id is not None
                else None
            )
            acceptance = (
                _acceptance(accepted[r.volume_acceptance_id])
                if r.volume_acceptance_id is not None
                else None
            )
            # The trigger of an entry is only the cause of «немає активних
            # постачальників» (contract, RunLogEntry.trigger).
            trigger = r.trigger if r.kind == "no_active_suppliers" else None
            entries.append(RunLogEntry(r.kind, r.occurred_at, trigger, run, acceptance))
        return entries

    def update_statuses(self, page: int = 1) -> Page[SupplierUpdateStatus]:
        """Active suppliers by name with the last update date (REQ-F-034)."""
        with self._db.transaction() as conn:
            suppliers = [s for s in repositories.all_suppliers(conn) if s.active]
            dates = updates.last_update_dates(conn)
        rows = [
            SupplierUpdateStatus(SupplierRef(s.id, s.name), dates.get(s.id))
            for s in sort_by(suppliers, lambda s: s.name)
        ]
        return paginate(rows, page)

    # --- accepting a new volume (REQ-F-031, REQ-F-052, REQ-F-047) -----------------------------

    def reject_acceptance(self, actor: Actor, reason_code: str) -> None:
        """Record an acceptance refused before it reached ``accept_volume``."""
        self._record.rejected(
            actor, "volume_accept", VOLUME_ACCEPTANCE, None, reason_code
        )

    def accept_volume(
        self, actor: Actor, run_id: int, supplier_id: int
    ) -> VolumeAcceptance:
        """The supplier's parsed count in the run becomes its volume base.

        Only in the supplier's last run with a status and only for "частково";
        the absence count of its items starts again (REQ-F-047).
        """
        try:
            with self._db.transaction() as conn:
                errors = []
                if updates.get_run(conn, run_id) is None:
                    errors.append(
                        FieldError("run_id", "reference_not_found", REFERENCE_NOT_FOUND)
                    )
                if repositories.get_supplier(conn, supplier_id) is None:
                    errors.append(
                        FieldError(
                            "supplier_id", "reference_not_found", REFERENCE_NOT_FOUND
                        )
                    )
                if errors:
                    raise ValidationFailed(errors)
                status = updates.status_of(conn, run_id, supplier_id)
                if status is None or not status.volume_acceptance_available:
                    raise Conflict(
                        "volume_acceptance_unavailable", VOLUME_ACCEPTANCE_UNAVAILABLE
                    )
                now = self._clock.now()
                count = status.parsed_items_count
                updates.set_volume_base(conn, supplier_id, count)
                updates.restart_absence_count(conn, supplier_id)
                acceptance_id = updates.insert_acceptance(
                    conn,
                    run_id=run_id,
                    supplier_id=supplier_id,
                    accepted_by=actor.login,
                    accepted_at=now,
                    volume_baseline=count,
                )
                updates.insert_log_entry(
                    conn,
                    kind="volume_acceptance",
                    occurred_at=now,
                    day=to_kyiv(now).date(),
                    volume_acceptance_id=acceptance_id,
                )
                row = updates.acceptances_by_id(conn, [acceptance_id])[acceptance_id]
        except ServiceError as exc:
            self.reject_acceptance(actor, exc.code)
            raise
        self._record.success(actor, "volume_accept", VOLUME_ACCEPTANCE, acceptance_id)
        return _acceptance(row)

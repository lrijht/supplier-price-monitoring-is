"""Update runs: the run itself, the scheduler, the catch-up and the interrupted
run (REQ-F-018, REQ-F-020…REQ-F-034, REQ-F-042…REQ-F-047, REQ-F-052…REQ-F-055,
REQ-F-060…REQ-F-067, REQ-NF-016, REQ-NF-017).

``UpdateRunner`` implements the port ``RunLauncher`` of ``services``. One run
at a time per application: the mark "a run is going" is shared by ``run``,
``tick``, ``startup`` and the manual run. Suppliers of a run are processed one
by one in the order of their names; the data of a supplier (items, daily
prices, events, feed state, volume base and its status) is written in one
transaction before the next page is requested (REQ-NF-016). No transaction is
open while a page is being fetched.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from spm.clock import Clock, kyiv_date, scheduled_moment
from spm.logging import JsonLinesLog, current_request_id, request_id_scope
from spm.services.directories import normalize_unit
from spm.services.ordering import sort_by
from spm.services.runs import LaunchResult
from spm.storage import Database, repositories, updates
from spm.storage.updates import FeedState, LinkSnapshot
from spm.update import fetch
from spm.update.parsers import PriceState, parse_rows, read_price

SCHEDULED, MANUAL, CATCH_UP = "scheduled", "manual", "catch_up"
SUCCESS, PARTIAL, ERROR = "success", "partial", "error"

UNPARSABLE = "unparsable"
WRITE_FAILED = "write_failed"
REASON_TEXT = {
    fetch.UNAVAILABLE: "сторінка недоступна",
    UNPARSABLE: "сторінку не розібрано",
    WRITE_FAILED: "збій запису даних",
}
# REQ-F-030: fewer than 80 % of the volume base is an incomplete crawl.
COMPLETE_SHARE = (4, 5)
TICK_SECONDS = 0.5  # the background scheduler checks the clock twice a second
_PERCENT_STEP = Decimal("0.1")


def timeout_text(seconds: float) -> str:
    shown = int(seconds) if float(seconds).is_integer() else seconds
    return f"перевищено час очікування {shown} с"


# --- one page --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageItem:
    sku: str
    name: str
    unit: str
    price: Decimal | None  # None — no price (REQ-F-029, REQ-F-062)


@dataclass(slots=True)
class ReadPage:
    items: list[PageItem] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


def read_page(parser: str, html: str) -> ReadPage:
    """Items of the page by REQ-F-060…REQ-F-062: the first row of a sku wins;
    a row without a sku or with an unparsable price is skipped with a warning;
    a zero or negative price is "no price" with a warning."""
    page = ReadPage()
    seen: set[str] = set()
    for row in parse_rows(parser, html):
        if not row.sku:
            page.warnings.append({"kind": "unparsed_row", "sku": None})
            continue
        if row.sku in seen:
            page.warnings.append({"kind": "duplicate_sku", "sku": row.sku})
            continue
        price = read_price(row.price_text)
        if price is PriceState.UNPARSABLE:
            page.warnings.append({"kind": "unparsed_row", "sku": row.sku})
            continue
        seen.add(row.sku)
        if price is PriceState.NO_PRICE:
            price = None
        elif price <= 0:
            page.warnings.append({"kind": "non_positive_price", "sku": row.sku})
            price = None
        page.items.append(PageItem(row.sku, row.name, row.unit, price))
    return page


# --- the feed state of an item (REQ-F-045…REQ-F-047, REQ-F-064) -----------------------------


def seen_on_page(state: FeedState, day: date, status: str) -> None:
    """The item is on the page of a run dated ``day`` with ``status``."""
    if state.disappeared:  # back after "зник": "з'явився" with the next price
        state.disappeared = False
        state.base = None
    if status == PARTIAL and state.on_date == day and state.by_success:
        return  # a run with "успіх" decided this date (REQ-F-047)
    if state.on_date != day:
        state.before = state.absences
        state.on_date = day
    state.absent = False
    state.by_success = status == SUCCESS


def missing_from_page(state: FeedState, day: date) -> None:
    """The item is absent from the page of a run with "успіх" dated ``day``."""
    if state.on_date != day:
        state.before = state.absences
        state.on_date = day
    state.absent = True
    state.by_success = True


# --- what a run starts with ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierSnapshot:
    id: int
    name: str
    catalog_url: str
    parser: str


@dataclass(frozen=True, slots=True)
class Began:
    """A started run with its snapshot of directories and settings (REQ-F-067)."""

    run_id: int
    request_id: str
    price_date: date
    suppliers: list[SupplierSnapshot]
    links: dict[int, LinkSnapshot]
    threshold_tenths: int


@dataclass(frozen=True, slots=True)
class NoActive:
    log_entry_id: int


class _Busy:
    pass


BUSY = _Busy()


class UpdateRunner:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        action_log: JsonLinesLog,
        technical_log: JsonLinesLog,
    ) -> None:
        self._db = database
        self._clock = clock
        self._actions = action_log
        self._technical = technical_log
        self._guard = threading.Lock()
        self._busy = False
        self._stop = threading.Event()
        self._scheduler: threading.Thread | None = None

    # --- the port of services: the manual run (REQ-F-020, REQ-F-021) -----------------------

    def launch_manual(self, started_by: str) -> LaunchResult:
        began = self._begin(MANUAL, started_by, request_id=current_request_id())
        if began is BUSY:
            return LaunchResult(busy=True)
        if isinstance(began, NoActive):
            return LaunchResult(log_entry_id=began.log_entry_id)
        self._spawn(began)
        return LaunchResult(run_id=began.run_id)

    # --- runs from code ----------------------------------------------------------------------

    def run(self, trigger: str, *, started_by: str | None = None) -> int | None:
        """Perform one run now, in this thread; its id, or None when no run
        started (no active supplier, or another run is going)."""
        began = self._begin(trigger, started_by, counts=trigger == SCHEDULED)
        if not isinstance(began, Began):
            return None
        self._execute(began)
        return began.run_id

    def tick(self, *, background: bool = False) -> int | None:
        """One check of the scheduler at the clock's moment (REQ-F-018,
        REQ-F-022, REQ-F-054, REQ-F-055, REQ-F-063)."""
        now = self._clock.now()
        today = kyiv_date(now)
        with self._db.transaction() as conn:
            update_time = repositories.get_settings(conn).update_time
            if now < scheduled_moment(today, update_time):
                return None
            if updates.day_has_scheduled_run(conn, today):
                return None
        began = self._begin(SCHEDULED, None, counts=True)
        if began is BUSY:
            self._skipped(now)
            return None
        if not isinstance(began, Began):
            return None
        if background:
            self._spawn(began)
        else:
            self._execute(began)
        return began.run_id

    def startup(self, *, background: bool = False) -> int | None:
        """Right after the start: runs left "триває" become "перервано"
        (REQ-F-024), then one catch-up if REQ-F-023 holds."""
        now = self._clock.now()
        today = kyiv_date(now)
        with self._db.transaction() as conn:
            stopped = updates.runs_in_progress(conn)
            for run in stopped:
                updates.interrupt_run(conn, run.id)
            last = updates.last_run(conn)
            update_time = repositories.get_settings(conn).update_time
            missed = now >= scheduled_moment(
                today, update_time
            ) and not updates.day_has_scheduled_run(conn, today)
        for run in stopped:
            with request_id_scope(str(run.id)):
                self._actions.write(
                    level="warning", event="run_interrupted", run_id=run.id
                )
        interrupted = last is not None and last.status == "interrupted"
        if not (missed or interrupted):
            return None
        # A catch-up for a missed time replaces the day's scheduled run; one only
        # for an interrupted run does not (REQ-F-023, REQ-F-055).
        began = self._begin(CATCH_UP, None, counts=missed)
        if not isinstance(began, Began):
            return None
        if background:
            self._spawn(began)
        else:
            self._execute(began)
        return began.run_id

    # --- the background scheduler (REQ-NF-014) ---------------------------------------------------

    def start_background(self) -> None:
        self._stop.clear()
        self._scheduler = threading.Thread(
            target=self._loop, name="spm-scheduler", daemon=True
        )
        self._scheduler.start()

    def stop_background(self) -> None:
        self._stop.set()
        if self._scheduler is not None:
            self._scheduler.join(timeout=5)
            self._scheduler = None

    def _loop(self) -> None:
        self._safely(lambda: self.startup(background=True))
        while not self._stop.wait(TICK_SECONDS):
            self._safely(lambda: self.tick(background=True))

    def _safely(self, step: Callable[[], object]) -> None:
        """A failure of the scheduler goes to the technical log and does not
        stop the application (REQ-NF-017)."""
        try:
            step()
        except Exception as exc:  # noqa: BLE001
            self._technical.write(
                level="error",
                event="scheduler_failed",
                result="error",
                error=f"{type(exc).__name__}: {exc}",
            )

    # --- starting a run ---------------------------------------------------------------------------

    def _begin(
        self,
        trigger: str,
        started_by: str | None,
        *,
        request_id: str | None = None,
        counts: bool = False,
    ) -> Began | NoActive | _Busy:
        now = self._clock.now()
        day = kyiv_date(now)
        with self._guard:
            if self._busy:
                return BUSY
            with self._db.transaction() as conn:
                suppliers = [s for s in repositories.all_suppliers(conn) if s.active]
                if not suppliers:
                    entry_id = updates.insert_log_entry(
                        conn,
                        kind="no_active_suppliers",
                        occurred_at=now,
                        day=day,
                        trigger=MANUAL if trigger == MANUAL else SCHEDULED,
                        counts_as_scheduled=counts,
                    )
                    began: Began | NoActive = NoActive(entry_id)
                else:
                    suppliers = sort_by(suppliers, lambda s: s.name)
                    threshold = repositories.get_settings(
                        conn
                    ).notification_threshold_tenths
                    links = {link.item_id: link for link in updates.links(conn)}
                    run_id = updates.insert_run(
                        conn,
                        trigger=trigger,
                        started_at=now,
                        started_by=started_by if trigger == MANUAL else None,
                        price_date=day,
                        supplier_ids=[s.id for s in suppliers],
                    )
                    updates.insert_log_entry(
                        conn,
                        kind="run",
                        occurred_at=now,
                        day=day,
                        run_id=run_id,
                        counts_as_scheduled=counts,
                    )
                    began = Began(
                        run_id,
                        request_id or str(run_id),
                        day,
                        [
                            SupplierSnapshot(s.id, s.name, s.catalog_url, s.parser)
                            for s in suppliers
                        ],
                        links,
                        threshold,
                    )
            if isinstance(began, Began):
                self._busy = True
        if isinstance(began, NoActive):
            with request_id_scope(str(began.log_entry_id)):
                self._actions.write(
                    level="info",
                    event="no_active_suppliers",
                    run_log_entry_id=began.log_entry_id,
                    trigger=MANUAL if trigger == MANUAL else SCHEDULED,
                )
            return began
        with request_id_scope(began.request_id):
            self._actions.write(
                level="info",
                event="run_started",
                run_id=began.run_id,
                trigger=trigger,
            )
        return began

    def _skipped(self, now: datetime) -> None:
        """REQ-F-022: «пропущено: оновлення вже триває» at the scheduled time."""
        with self._db.transaction() as conn:
            entry_id = updates.insert_log_entry(
                conn,
                kind="skipped",
                occurred_at=now,
                day=kyiv_date(now),
                counts_as_scheduled=True,
            )
        with request_id_scope(str(entry_id)):
            self._actions.write(
                level="warning", event="run_skipped", run_log_entry_id=entry_id
            )

    def _spawn(self, began: Began) -> None:
        threading.Thread(
            target=self._execute, args=(began,), name="spm-update-run", daemon=True
        ).start()

    # --- performing a run -------------------------------------------------------------------------

    def _execute(self, began: Began) -> None:
        try:
            with request_id_scope(began.request_id):
                statuses = [self._supplier(began, s) for s in began.suppliers]
                overall = (
                    SUCCESS
                    if all(s == SUCCESS for s in statuses)
                    else ERROR
                    if all(s == ERROR for s in statuses)
                    else PARTIAL
                )
                with self._db.transaction() as conn:
                    updates.finish_run(conn, began.run_id, overall, self._clock.now())
                self._actions.write(
                    level="info",
                    event="run_finished",
                    run_id=began.run_id,
                    status=overall,
                )
        finally:
            with self._guard:
                self._busy = False

    def _supplier(self, began: Began, supplier: SupplierSnapshot) -> str:
        """Fetch, read and write one supplier; its status in the run."""
        try:
            html = fetch.fetch_page(supplier.catalog_url)
        except fetch.FetchError as exc:
            text = (
                timeout_text(exc.timeout)
                if exc.reason_code == fetch.TIMEOUT
                else REASON_TEXT[exc.reason_code]
            )
            return self._failed(began, supplier, exc.reason_code, text, exc.detail)
        try:
            page = read_page(supplier.parser, html)
        except Exception as exc:  # noqa: BLE001 - any parser failure: not parsed
            page, detail = ReadPage(), f"{type(exc).__name__}: {exc}"
        else:
            detail = "на сторінці не знайдено жодної позиції"
        if not page.items:  # REQ-F-026: no list of items, or every row skipped
            return self._failed(
                began, supplier, UNPARSABLE, REASON_TEXT[UNPARSABLE], detail
            )
        try:
            with self._db.transaction() as conn:
                status = self._write(conn, began, supplier, page)
        except Exception as exc:  # noqa: BLE001 - REQ-NF-016: rolled back
            return self._failed(
                began,
                supplier,
                WRITE_FAILED,
                REASON_TEXT[WRITE_FAILED],
                f"{type(exc).__name__}: {exc}",
            )
        self._actions.write(
            level="info",
            event="supplier_status",
            run_id=began.run_id,
            supplier_id=supplier.id,
            status=status,
            parsed_items_count=len(page.items),
            reason_code=None,
        )
        return status

    def _failed(
        self,
        began: Began,
        supplier: SupplierSnapshot,
        reason_code: str,
        text: str,
        detail: str,
    ) -> str:
        """Status "помилка" with the reason; the details go to the technical log
        (REQ-F-026, REQ-NF-016, REQ-NF-018)."""
        self._technical.write(
            level="error",
            event="supplier_update_failed",
            result="error",
            run_id=began.run_id,
            supplier_id=supplier.id,
            reason_code=reason_code,
            error=f"{text}: {detail}",
        )
        with self._db.transaction() as conn:
            updates.set_supplier_status(
                conn,
                began.run_id,
                supplier.id,
                status=ERROR,
                reason_code=reason_code,
                error_reason=text,
            )
        self._actions.write(
            level="warning",
            event="supplier_status",
            run_id=began.run_id,
            supplier_id=supplier.id,
            status=ERROR,
            parsed_items_count=None,
            reason_code=reason_code,
        )
        return ERROR

    def _write(self, conn, began: Began, supplier: SupplierSnapshot, page: ReadPage):
        """Everything of one supplier in one transaction (REQ-NF-016)."""
        day = began.price_date
        now = self._clock.now()
        warnings = list(page.warnings)
        count = len(page.items)
        base = updates.volume_base(conn, supplier.id)
        share_num, share_den = COMPLETE_SHARE
        status = (
            PARTIAL
            if base is not None and count * share_den < base * share_num
            else SUCCESS
        )
        own_links = {
            item_id: link
            for item_id, link in began.links.items()
            if link.supplier_id == supplier.id
        }
        present: set[int] = set()
        for item in page.items:
            item_id = updates.upsert_item(
                conn,
                supplier_id=supplier.id,
                sku=item.sku,
                name=item.name,
                unit=item.unit,
                seen=day,
            )
            present.add(item_id)
            link = own_links.get(item_id)
            if link is None:
                continue  # REQ-F-012: no prices of unlinked items
            state = updates.feed_state(conn, item_id)
            seen_on_page(state, day, status)
            if item.price is not None:
                if normalize_unit(item.unit) != normalize_unit(link.material_unit):
                    # REQ-F-017, REQ-F-028, REQ-F-065: marked, no events, and it
                    # does not replace a price of the date.
                    warnings.append({"kind": "unit_mismatch", "sku": item.sku})
                    if not updates.has_daily_price(conn, item_id, day):
                        self._price(conn, item, link, day, mismatch=True)
                else:
                    self._price(conn, item, link, day, mismatch=False)
                    if link.material_active:  # REQ-F-042, REQ-F-049
                        self._price_event(conn, began, state, item.price, link, now)
            updates.save_feed_state(conn, state)
        if status == SUCCESS:
            for item_id, link in own_links.items():
                if item_id in present:
                    continue
                state = updates.feed_state(conn, item_id)
                missing_from_page(state, day)
                if (
                    state.absences >= 2
                    and not state.disappeared
                    and state.base is not None
                    and link.material_active
                ):
                    updates.insert_event(
                        conn,
                        kind="disappeared",
                        event_date=day,
                        created_at=now,
                        material_id=link.material_id,
                        supplier_id=supplier.id,
                        item_id=item_id,
                    )
                    state.disappeared = True
                updates.save_feed_state(conn, state)
            if base is None or count > base:  # REQ-F-052
                updates.set_volume_base(conn, supplier.id, count)
        updates.set_supplier_status(
            conn,
            began.run_id,
            supplier.id,
            status=status,
            parsed_items_count=count,
            warnings=warnings,
        )
        return status

    @staticmethod
    def _price(conn, item: PageItem, link: LinkSnapshot, day: date, *, mismatch):
        updates.put_daily_price(
            conn,
            item_id=link.item_id,
            day=day,
            price=item.price,
            unit=item.unit,
            material_id=link.material_id,
            unit_mismatch=mismatch,
        )

    def _price_event(
        self,
        conn,
        began: Began,
        state: FeedState,
        price: Decimal,
        link: LinkSnapshot,
        now: datetime,
    ) -> None:
        """ "з'явився" without a feed base, "зміна ціни" from the threshold up
        (REQ-F-044…REQ-F-046); the price of the event becomes the base."""
        common = {
            "event_date": began.price_date,
            "created_at": now,
            "material_id": link.material_id,
            "supplier_id": link.supplier_id,
            "item_id": link.item_id,
        }
        if state.base is None:
            updates.insert_event(conn, kind="appeared", price=price, **common)
            state.base = price
            return
        change = price - state.base
        # |new − base| / base × 100 % ≥ threshold, exactly (threshold in tenths).
        if abs(change) * 1000 < state.base * began.threshold_tenths:
            return
        percent = (change * 100 / state.base).quantize(_PERCENT_STEP, ROUND_HALF_UP)
        updates.insert_event(
            conn,
            kind="price_change",
            old_price=state.base,
            new_price=price,
            change_percent=percent,
            **common,
        )
        state.base = price

"""Views of prices: the comparison list and the comparison of a material, the
history of a material, the change feed and the items that need attention
(REQ-F-017, REQ-F-029, REQ-F-035…REQ-F-042, REQ-F-049, REQ-F-057…REQ-F-059,
REQ-F-065, REQ-F-066, REQ-F-068).

Everything is computed when asked (REQ-F-039); "today" is the Kyiv date of the
clock. The web interface and the API call the same functions (REQ-NF-031).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from spm.clock import Clock, kyiv_date
from spm.services.directories import normalize_unit
from spm.services.errors import NotFound
from spm.services.ordering import Page, matches, paginate, sort_by
from spm.services.runs import SupplierRef
from spm.storage import Database, repositories, views
from spm.storage.repositories import MaterialRow, SupplierRow

# REQ-F-038: a price more than 2 days older than today is stale.
STALE_AFTER_DAYS = 2
PERIODS = {"last_7_days": 7, "last_30_days": 30, "all": None}  # REQ-F-040
EVENT_KINDS = ("price_change", "appeared", "disappeared")
_PERCENT = Decimal("0.1")
_MONEY = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class MaterialRef:
    id: int
    name: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class DailyPrice:
    price: Decimal
    date: date
    unit_mismatch: bool


@dataclass(frozen=True, slots=True)
class Difference:
    percent: Decimal  # rounded to 0.1, half away from zero
    amount: Decimal  # rounded to 0.01


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    supplier: SupplierRef
    daily_price: DailyPrice | None  # None — «ціни ще немає»
    stale: bool | None
    cheapest: bool
    difference: Difference | None  # None — «—»


@dataclass(frozen=True, slots=True)
class MaterialComparison:
    material: MaterialRef
    items: list[ComparisonRow]  # empty for a deactivated material


@dataclass(frozen=True, slots=True)
class ComparisonListRow:
    material: MaterialRef
    cheapest_supplier: SupplierRef | None
    price: Decimal | None


@dataclass(frozen=True, slots=True)
class HistoryRow:
    date: date
    supplier: SupplierRef
    price: Decimal
    unit_mismatch: bool
    effective_at_period_start: bool


@dataclass(frozen=True, slots=True)
class PriceHistory:
    material: MaterialRef
    period: str
    items: list[HistoryRow]


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    kind: str
    date: date
    created_at: datetime
    material: MaterialRef
    supplier: SupplierRef
    old_price: Decimal | None
    new_price: Decimal | None
    change_percent: Decimal | None
    price: Decimal | None


@dataclass(frozen=True, slots=True)
class AttentionItem:
    item_id: int
    supplier: SupplierRef
    supplier_active: bool
    sku: str
    name: str
    unit: str
    material: MaterialRef
    material_unit: str
    last_unit_mismatch_date: date


def _round(value: Decimal, step: Decimal) -> Decimal:
    return value.quantize(step, ROUND_HALF_UP)


def _shown_price(prices: list[views.LinkedPriceRow]) -> views.LinkedPriceRow | None:
    """REQ-F-065: the last price without the mark; without one at all — the
    last price with the mark; no price — None."""
    dated = [p for p in prices if p.price_date is not None]
    plain = [p for p in dated if not p.unit_mismatch]
    pool = plain or dated
    return max(pool, key=lambda p: p.price_date) if pool else None


def _comparison_rows(
    prices: list[views.LinkedPriceRow], today: date
) -> list[ComparisonRow]:
    """Rows of active suppliers by name, with the cheapest and the difference
    (REQ-F-036…REQ-F-038)."""
    by_item: dict[int, list[views.LinkedPriceRow]] = defaultdict(list)
    for p in prices:
        if p.supplier_active:  # REQ-F-011, REQ-F-037
            by_item[p.item_id].append(p)
    oldest_fresh = today - timedelta(days=STALE_AFTER_DAYS)
    shown = []
    for item_prices in by_item.values():
        first = item_prices[0]
        supplier = SupplierRef(first.supplier_id, first.supplier_name)
        price = _shown_price(item_prices)
        shown.append((supplier, price))
    suitable = [
        p.price
        for _, p in shown
        if p is not None and not p.unit_mismatch and p.price_date >= oldest_fresh
    ]
    minimum = min(suitable) if suitable else None
    rows = []
    for supplier, p in shown:
        if p is None:
            rows.append(ComparisonRow(supplier, None, None, False, None))
            continue
        stale = p.price_date < oldest_fresh
        fit = not stale and not p.unit_mismatch
        difference = None
        if fit and minimum is not None:
            change = p.price - minimum
            difference = Difference(
                _round(change * 100 / minimum, _PERCENT), _round(change, _MONEY)
            )
        rows.append(
            ComparisonRow(
                supplier,
                DailyPrice(p.price, p.price_date, p.unit_mismatch),
                stale,
                fit and p.price == minimum,
                difference,
            )
        )
    return sort_by(rows, lambda r: r.supplier.name)


def _cheapest(rows: list[ComparisonRow]) -> ComparisonRow | None:
    """REQ-F-035: of equal minimum prices the later date, then the first
    supplier by name."""
    best = [r for r in rows if r.cheapest]
    if not best:
        return None
    latest = max(r.daily_price.date for r in best)
    return [r for r in best if r.daily_price.date == latest][0]  # sorted by name


def _changes(prices: list[views.HistoryPriceRow]) -> list[views.HistoryPriceRow]:
    """REQ-F-040: the first price and each next one that differs from the
    previous (the mark «одиниця не збігається» counts)."""
    result: list[views.HistoryPriceRow] = []
    previous = None
    for p in sorted(prices, key=lambda p: (p.price_date, p.id)):
        key = (p.price, p.unit_mismatch)
        if key != previous:
            result.append(p)
        previous = key
    return result


class Views:
    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    def today(self) -> date:
        return kyiv_date(self._clock.now())

    # --- comparison (REQ-F-035…REQ-F-039, REQ-F-049, REQ-F-059) -------------------------

    def comparison_list(
        self, page: int = 1, q: str | None = None
    ) -> Page[ComparisonListRow]:
        """Active materials by name with the cheapest supplier and price."""
        with self._db.transaction() as conn:
            materials = [
                m
                for m in repositories.all_materials(conn)
                if m.active and matches(q, m.name)
            ]
            result = paginate(sort_by(materials, lambda m: m.name), page)
            prices = views.linked_prices(conn, [m.id for m in result.items])
        by_material: dict[int, list[views.LinkedPriceRow]] = defaultdict(list)
        for p in prices:
            by_material[p.material_id].append(p)
        today = self.today()
        rows = []
        for m in result.items:
            best = _cheapest(_comparison_rows(by_material[m.id], today))
            rows.append(
                ComparisonListRow(
                    MaterialRef(m.id, m.name, m.active),
                    best.supplier if best else None,
                    best.daily_price.price if best else None,
                )
            )
        return Page(rows, result.page, result.total_items, result.total_pages)

    def material_comparison(self, material_id: int) -> MaterialComparison:
        with self._db.transaction() as conn:
            material = repositories.get_material(conn, material_id)
            if material is None:
                raise NotFound()
            prices = views.linked_prices(conn, [material.id])
        ref = MaterialRef(material.id, material.name, material.active)
        if not material.active:  # REQ-F-049: «матеріал деактивовано»
            return MaterialComparison(ref, [])
        return MaterialComparison(ref, _comparison_rows(prices, self.today()))

    # --- history (REQ-F-040, REQ-F-041, REQ-F-016) ------------------------------------------

    def price_history(self, material_id: int, period: str) -> PriceHistory:
        """Changes of the material's prices per supplier in the period, newest
        first; the rows «чинна на початок періоду» last."""
        with self._db.transaction() as conn:
            material = repositories.get_material(conn, material_id)
            if material is None:
                raise NotFound()
            prices = views.material_prices(conn, material.id)
        days = PERIODS[period]
        start = self.today() - timedelta(days=days - 1) if days else None
        by_supplier: dict[int, list[views.HistoryPriceRow]] = defaultdict(list)
        for p in prices:
            by_supplier[p.supplier_id].append(p)
        inside: list[HistoryRow] = []
        at_start: list[HistoryRow] = []
        for supplier_prices in by_supplier.values():
            changes = _changes(supplier_prices)
            before = [c for c in changes if start is not None and c.price_date < start]
            within = [c for c in changes if start is None or c.price_date >= start]
            for c in within:
                inside.append(self._history_row(c, False))
            if before and not (within and within[0].price_date == start):
                at_start.append(self._history_row(before[-1], True))

        def newest_first(rows: list[HistoryRow]) -> list[HistoryRow]:
            by_name = sort_by(rows, lambda r: r.supplier.name)
            return sorted(by_name, key=lambda r: r.date, reverse=True)

        return PriceHistory(
            MaterialRef(material.id, material.name, material.active),
            period,
            newest_first(inside) + newest_first(at_start),
        )

    @staticmethod
    def _history_row(p: views.HistoryPriceRow, at_start: bool) -> HistoryRow:
        return HistoryRow(
            p.price_date,
            SupplierRef(p.supplier_id, p.supplier_name),
            p.price,
            p.unit_mismatch,
            at_start,
        )

    def history_materials(self, show_inactive: bool) -> list[MaterialRow]:
        """The choice of the material: active ones, or all with «показати
        неактивні», by name (REQ-F-040, REQ-F-057)."""
        with self._db.transaction() as conn:
            rows = repositories.all_materials(conn)
        return sort_by([r for r in rows if show_inactive or r.active], lambda r: r.name)

    # --- the feed (REQ-F-042, REQ-F-057, REQ-F-058) -------------------------------------------

    def events(
        self,
        page: int = 1,
        *,
        material_id: int | None = None,
        supplier_id: int | None = None,
        kind: str | None = None,
    ) -> Page[Event]:
        """Events newest first by the moment of creation; the same moment — the
        later created first."""
        with self._db.transaction() as conn:
            rows = views.feed_events(
                conn, material_id=material_id, supplier_id=supplier_id, kind=kind
            )
        rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        events = [
            Event(
                r.id,
                r.kind,
                r.event_date,
                r.created_at,
                MaterialRef(r.material_id, r.material_name),
                SupplierRef(r.supplier_id, r.supplier_name),
                r.old_price,
                r.new_price,
                r.change_percent,
                r.price,
            )
            for r in rows
        ]
        return paginate(events, page)

    def feed_choices(self) -> tuple[list[MaterialRow], list[SupplierRow]]:
        """Values of the feed filters: all materials and all suppliers, deactivated
        ones included (REQ-F-011), by name (REQ-F-057)."""
        with self._db.transaction() as conn:
            materials = repositories.all_materials(conn)
            suppliers = repositories.all_suppliers(conn)
        return (
            sort_by(materials, lambda m: m.name),
            sort_by(suppliers, lambda s: s.name),
        )

    # --- items that need attention (REQ-F-017, REQ-F-066, REQ-F-068) ------------------------

    def attention_items(self, page: int = 1) -> Page[AttentionItem]:
        """Linked items whose unit on the page differs from the material's and
        that have a price «одиниця не збігається» for it; by supplier, then sku."""
        with self._db.transaction() as conn:
            rows = views.linked_items_with_marked_prices(conn)
        items = [
            AttentionItem(
                r.item_id,
                SupplierRef(r.supplier_id, r.supplier_name),
                r.supplier_active,
                r.sku,
                r.name,
                r.unit,
                MaterialRef(r.material_id, r.material_name),
                r.material_unit,
                r.last_unit_mismatch_date,
            )
            for r in rows
            if normalize_unit(r.unit) != normalize_unit(r.material_unit)
        ]
        return paginate(
            sort_by(items, lambda i: i.supplier.name, lambda i: i.sku), page
        )

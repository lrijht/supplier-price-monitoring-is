"""Parsers of supplier catalogue pages (REQ-NF-005, REQ-NF-006, REQ-NF-024).

One parser per page layout of the three simulator suppliers (REQ-NF-026). A
parser reads the page's HTML only, so the same page served by any web server
gives the same result (REQ-NF-007).

``parse_page`` gives the items with their prices; ``parse_rows`` gives the raw
rows of the page for an update run, which decides itself what a row without a
sku, an unparsable price or "ціну уточнюйте" means (REQ-F-029, REQ-F-061).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from html.parser import HTMLParser

NO_PRICE_TEXT = "ціну уточнюйте"
_SKU_PREFIX = re.compile(r"^Арт\.\s*")
_SPACES = re.compile(r"\s+")
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ParsedItem:
    sku: str
    name: str
    unit: str
    price: Decimal | None  # None — «ціну уточнюйте»


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text.replace("\xa0", " ")).strip()


def parse_price(text: str) -> Decimal | None:
    """«1 250,50 грн», «18.40 грн», «64,20 грн» → Decimal; «ціну уточнюйте» → None."""
    text = _clean(text)
    if not text or text.lower().startswith(NO_PRICE_TEXT):
        return None
    number = text.lower().removesuffix("грн").strip()
    number = number.replace(" ", "").replace(",", ".")
    try:
        return Decimal(number).quantize(_CENT)
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class PageRow:
    """One item row of the page as text; ``price_text`` is the shown price."""

    sku: str
    name: str
    unit: str
    price_text: str


class PriceState(Enum):
    NO_PRICE = "no_price"  # «ціну уточнюйте»
    UNPARSABLE = "unparsable"


def read_price(text: str) -> Decimal | PriceState:
    """The price of a row: a number, «ціну уточнюйте», or text that is no price."""
    text = _clean(text)
    if text.lower().startswith(NO_PRICE_TEXT):
        return PriceState.NO_PRICE
    number = text.lower().removesuffix("грн").strip()
    number = number.replace(" ", "").replace(",", ".")
    try:
        value = Decimal(number)
    except InvalidOperation:
        return PriceState.UNPARSABLE
    if not number or not value.is_finite():
        return PriceState.UNPARSABLE
    return value.quantize(_CENT)


@dataclass
class _Node:
    """Text collected for the elements of one item, keyed by CSS class."""

    texts: dict[str, list[str]] = field(default_factory=dict)
    classes: set[str] = field(default_factory=set)

    def text(self, cls: str) -> str:
        return _clean("".join(self.texts.get(cls, [])))


class _ClassCollector(HTMLParser):
    """Collects text per CSS class inside every element of the item class.

    Nested elements are followed with a stack, so the text of an inner element
    also belongs to every enclosing class being collected.
    """

    _VOID = {"br", "img", "input", "meta", "link", "hr", "wbr"}

    def __init__(self, item_tag: str, item_class: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self.item_tag = item_tag
        self.item_class = item_class
        self.items: list[_Node] = []
        self._stack: list[tuple[str, list[str]]] = []
        self._item_depth: int | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID:
            return
        classes = (dict(attrs).get("class") or "").split()
        if self._item_depth is None and tag == self.item_tag:
            if self.item_class is None or self.item_class in classes:
                self._item_depth = len(self._stack)
                self.items.append(_Node())
        if self._item_depth is not None:
            self.items[-1].classes.update(classes)
        self._stack.append((tag, classes))

    def handle_endtag(self, tag):
        if tag in self._VOID:
            return
        # Close up to the matching tag (tolerates unclosed inner elements).
        for depth in range(len(self._stack) - 1, -1, -1):
            if self._stack[depth][0] == tag:
                del self._stack[depth:]
                break
        if self._item_depth is not None and len(self._stack) <= self._item_depth:
            self._item_depth = None

    def handle_data(self, data):
        if self._item_depth is None:
            return
        node = self.items[-1]
        for _, classes in self._stack[self._item_depth :]:
            for cls in classes:
                node.texts.setdefault(cls, []).append(data)
        node.texts.setdefault("", []).append(data)


def _collect(html: str, item_tag: str, item_class: str | None) -> list[_Node]:
    collector = _ClassCollector(item_tag, item_class)
    collector.feed(html)
    collector.close()
    return collector.items


def _rows_table(html: str) -> list[PageRow]:
    """Layout «table»: one ``<tr>`` per item with cells sku, name, unit, price.

    The header row has no sku cell; a row with an empty sku cell is an item row.
    """
    return [
        PageRow(row.text("sku"), row.text("name"), row.text("unit"), row.text("price"))
        for row in _collect(html, "tr", None)
        if "sku" in row.classes
    ]


def _rows_cards(html: str) -> list[PageRow]:
    """Layout «cards»: title, «Арт. …», «<price> грн / <unit>»."""
    rows = []
    for card in _collect(html, "div", "card"):
        price_text = card.text("card-price")
        price_part = price_text.rsplit("/", 1)[0] if "/" in price_text else price_text
        rows.append(
            PageRow(
                _SKU_PREFIX.sub("", card.text("card-sku")).strip(),
                card.text("card-title"),
                card.text("card-unit"),
                price_part,
            )
        )
    return rows


def _rows_list(html: str) -> list[PageRow]:
    """Layout «list»: «<sku> — <name>, <unit>: <price>» in ``<li>``."""
    return [
        PageRow(
            entry.text("product-sku"),
            entry.text("product-name"),
            entry.text("product-unit"),
            entry.text("product-price"),
        )
        for entry in _collect(html, "li", "product")
    ]


def _items(rows: list[PageRow]) -> list[ParsedItem]:
    return [ParsedItem(r.sku, r.name, r.unit, parse_price(r.price_text)) for r in rows]


def _parse_table(html: str) -> list[ParsedItem]:
    return _items([r for r in _rows_table(html) if r.sku])


def _parse_cards(html: str) -> list[ParsedItem]:
    return _items(_rows_cards(html))


def _parse_list(html: str) -> list[ParsedItem]:
    return _items(_rows_list(html))


_ROWS: dict[str, Callable[[str], list[PageRow]]] = {
    "table_layout": _rows_table,
    "cards_layout": _rows_cards,
    "list_layout": _rows_list,
}

_PARSERS: dict[str, Callable[[str], list[ParsedItem]]] = {
    "table_layout": _parse_table,
    "cards_layout": _parse_cards,
    "list_layout": _parse_list,
}


def available_parsers() -> Iterable[str]:
    """Names of the available parsers (``GET /parsers``)."""
    return tuple(_PARSERS)


def parse_page(parser: str, html: str) -> list[ParsedItem]:
    """Items of the page in page order."""
    try:
        parse = _PARSERS[parser]
    except KeyError:
        raise ValueError(f"unknown parser: {parser}") from None
    return parse(html)


def parse_rows(parser: str, html: str) -> list[PageRow]:
    """Item rows of the page in page order; none — no list of items found."""
    try:
        rows = _ROWS[parser]
    except KeyError:
        raise ValueError(f"unknown parser: {parser}") from None
    return rows(html)

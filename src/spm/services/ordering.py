"""Alphabetical order, search and pages of lists (REQ-F-057, Р-113, Р-114).

Strings are compared character by character without regard to case: first all
other characters (space, hyphen, apostrophe…) by code, then digits, then
Cyrillic letters in the order of the Ukrainian alphabet, then Latin letters.
SKUs use the same order. SQLite cannot sort this way, so lists are sorted here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil

PAGE_SIZE = 50

UKRAINIAN_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_LETTER_RANK = {letter: rank for rank, letter in enumerate(UKRAINIAN_ALPHABET)}

_OTHER, _DIGIT, _CYRILLIC, _LATIN = range(4)


def _char_key(ch: str) -> tuple[int, int]:
    if ch in _LETTER_RANK:
        return _CYRILLIC, _LETTER_RANK[ch]
    if "0" <= ch <= "9":
        return _DIGIT, ord(ch)
    if "a" <= ch <= "z":
        return _LATIN, ord(ch)
    if "Ѐ" <= ch <= "ӿ":
        # Cyrillic letters outside the Ukrainian alphabet: after it, by code.
        return _CYRILLIC, len(UKRAINIAN_ALPHABET) + ord(ch)
    return _OTHER, ord(ch)


def alphabetical_key(text: str) -> tuple[tuple[int, int], ...]:
    return tuple(_char_key(ch) for ch in text.lower())


def matches(query: str | None, *texts: str) -> bool:
    """Substring search without regard to case (Cyrillic included)."""
    if not query:
        return True
    needle = query.casefold()
    return any(needle in text.casefold() for text in texts)


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    page: int
    total_items: int
    total_pages: int
    page_size: int = PAGE_SIZE


def page_count(total_items: int) -> int:
    """How many pages of 50 the list has; an empty list has none."""
    return ceil(total_items / PAGE_SIZE)


def paginate[T](items: Sequence[T], page: int) -> Page[T]:
    """Page ``page`` (from 1) of 50; a page beyond the end is empty."""
    start = (page - 1) * PAGE_SIZE
    return Page(
        items=list(items[start : start + PAGE_SIZE]),
        page=page,
        total_items=len(items),
        total_pages=page_count(len(items)),
    )


def sort_by[T](items: Sequence[T], *keys: Callable[[T], str]) -> list[T]:
    """Sort by the given text fields in alphabetical order, one after another."""
    return sorted(
        items,
        key=lambda item: tuple((alphabetical_key(k(item)), k(item)) for k in keys),
    )

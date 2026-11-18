"""The comparison list as a CSV file (REQ-F-072, addendum A-06).

The rows are those of the comparison list screen (``Views``), every page at
once; this module only writes them in the file format of Р-131: UTF-8 with BOM,
";" as the delimiter, CRLF, quotes by RFC 4180 where needed, a decimal comma.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # views builds the files; a runtime import would be a cycle
    from spm.services.views import ComparisonListRow

CSV_MEDIA_TYPE = "text/csv"
CSV_ENCODING = "utf-8-sig"  # UTF-8 with BOM: Excel reads the Cyrillic right
CSV_DELIMITER = ";"
CSV_LINE_END = "\r\n"
COMPARISON_HEADER = ("Матеріал", "Найдешевший постачальник", "Ціна, грн")
NO_VALUE = "—"
COMPARISON_FILE_NAME = "porivniannia-{day}.csv"


@dataclass(frozen=True, slots=True)
class ExportFile:
    name: str
    content: bytes
    media_type: str = CSV_MEDIA_TYPE


def file_price(value: Decimal | None) -> str:
    """1000.5 -> "1000,50", without "грн" and a thousands separator; no price -> "—"."""
    return f"{value:.2f}".replace(".", ",") if value is not None else NO_VALUE


def comparison_csv(rows: Iterable[ComparisonListRow]) -> bytes:
    """The header row and one row per material."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=CSV_DELIMITER, lineterminator=CSV_LINE_END)
    writer.writerow(COMPARISON_HEADER)
    for r in rows:
        supplier = r.cheapest_supplier.name if r.cheapest_supplier else NO_VALUE
        writer.writerow((r.material.name, supplier, file_price(r.price)))
    return out.getvalue().encode(CSV_ENCODING)


def comparison_file(rows: Iterable[ComparisonListRow], day: date) -> ExportFile:
    """The file of the comparison list exported on the Kyiv date ``day``."""
    return ExportFile(
        COMPARISON_FILE_NAME.format(day=day.isoformat()), comparison_csv(rows)
    )

"""T-09: parsers of the simulator's supplier pages on saved pages.

REQ-NF-005, REQ-NF-006, REQ-NF-007, REQ-NF-024, REQ-NF-029. The saved pages in
tests/pages/ were taken from the simulator with its own data file
(simulator/data.json), mode "normal".
"""

from __future__ import annotations

import http.server
import importlib
import subprocess
import sys
import threading
from decimal import Decimal
from functools import partial
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = Path(__file__).resolve().parent / "pages"

# Parser names: values of GET /parsers in the contract examples (spec/openapi.yaml).
PARSER_OF = {"alfa": "table_layout", "beta": "cards_layout", "vega": "list_layout"}

# What each saved page shows: SKU, name, unit, price (None — "ціну уточнюйте").
EXPECTED = {
    "alfa": [
        ("АП-101", "Плита ДСП біла 16 мм", "шт", Decimal("1250.50")),
        ("АП-102", "Плита ДСП дуб сонома 16 мм", "шт", Decimal("1384.00")),
        ("АП-205", "Плита МДФ 18 мм", "шт", Decimal("1720.90")),
        ("АП-310", "ДВП біле 3 мм", "шт", None),
    ],
    "beta": [
        ("БК-01", "Кромка ПВХ біла 2 мм", "м.п.", Decimal("18.40")),
        ("БК-02", "Кромка ПВХ дуб 2 мм", "м.п.", Decimal("21.10")),
        ("БК-07", "Кромка ПВХ біла 0,4 мм", "м.п.", Decimal("6.75")),
        ("БК-12", "Кромка АБС графіт 1 мм", "м.п.", None),
    ],
    "vega": [
        ("ВФ-5001", "Петля накладна з доводчиком", "шт", Decimal("64.20")),
        ("ВФ-5002", "Ручка-скоба 128 мм", "шт", Decimal("95.00")),
        ("ВФ-5010", "Напрямна кулькова 450 мм", "компл.", Decimal("212.30")),
        ("ВФ-5020", "Шуруп 4х16", "уп.", None),
    ],
}
SLUGS = sorted(EXPECTED)


@pytest.fixture
def parsers_module():
    return importlib.import_module("spm.update.parsers")


def saved_page(slug: str) -> str:
    return (PAGES / f"{slug}.html").read_text(encoding="utf-8")


def as_tuples(items) -> list[tuple]:
    return [(i.sku, i.name, i.unit, i.price) for i in items]


# REQ-NF-029: a saved page for each of the 3 simulator suppliers lies in /tests.
def test_saved_pages_exist_for_three_suppliers():
    assert sorted(p.stem for p in PAGES.glob("*.html")) == SLUGS


# REQ-NF-029: every saved page equals what the simulator serves for its data
# file in mode "normal".
@pytest.mark.parametrize("slug", SLUGS)
def test_saved_page_matches_simulator(simulator_module, client_factory, slug):
    sim = client_factory(
        simulator_module.create_app(simulator_module.DEFAULT_DATA_PATH)
    )
    resp = sim.get(f"/catalog/{slug}")
    assert resp.status_code == 200
    assert resp.text == saved_page(slug)


# REQ-NF-006: the list of available parsers has a parser for each of the 3
# simulator suppliers.
def test_available_parsers_cover_three_suppliers(parsers_module):
    names = list(parsers_module.available_parsers())
    assert set(PARSER_OF.values()) <= set(names)
    assert len(names) == len(set(names))


# REQ-NF-005, REQ-NF-006, REQ-NF-024: each parser parses its saved page: as many
# items as on the page; SKU, name, unit and price (or "no price") as shown.
@pytest.mark.parametrize("slug", SLUGS)
def test_parser_reads_saved_page(parsers_module, slug):
    items = parsers_module.parse_page(PARSER_OF[slug], saved_page(slug))
    assert as_tuples(items) == EXPECTED[slug]


# REQ-NF-005: the price is a Decimal in hryvnias with two decimal places; an
# item without a price has the mark "no price" (None), not 0.
@pytest.mark.parametrize("slug", SLUGS)
def test_parsed_prices_are_exact_decimals(parsers_module, slug):
    items = parsers_module.parse_page(PARSER_OF[slug], saved_page(slug))
    prices = [i.price for i in items]
    assert None in prices
    for price in prices:
        if price is not None:
            assert isinstance(price, Decimal)
            assert price > 0
            assert price.as_tuple().exponent == -2


# REQ-NF-005 (boundary): a page of the same layout with one item and with a
# thousands separator in the price is parsed too (simulator, test data).
@pytest.mark.parametrize(
    ("slug", "layout"), [("alfa", "table"), ("beta", "cards"), ("vega", "list")]
)
def test_parser_reads_single_item_page(
    parsers_module,
    simulator_module,
    client_factory,
    sim_data_file,
    write_sim_data,
    sim_data,
    slug,
    layout,
):
    supplier = next(s for s in sim_data["suppliers"] if s["slug"] == slug)
    supplier["items"] = [
        {"sku": "Х-1", "name": "Стільниця 38 мм", "unit": "шт", "price": "12345.60"}
    ]
    write_sim_data(sim_data)
    sim = client_factory(simulator_module.create_app(sim_data_file))
    html = sim.get(f"/catalog/{slug}").text
    assert (
        f"<{'table' if layout == 'table' else 'li' if layout == 'list' else 'div'}"
        in html
    )
    items = parsers_module.parse_page(PARSER_OF[slug], html)
    assert as_tuples(items) == [("Х-1", "Стільниця 38 мм", "шт", Decimal("12345.60"))]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the test output clean
        pass


@pytest.fixture
def other_web_server(tmp_path):
    """A plain web server (http.server) that serves the saved pages from files."""
    for slug in SLUGS:
        (tmp_path / f"{slug}.html").write_bytes((PAGES / f"{slug}.html").read_bytes())
    handler = partial(_QuietHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


# REQ-NF-007: a parser gives the same result for the page from the simulator and
# for the same page saved to a file and served by another web server.
@pytest.mark.parametrize("slug", SLUGS)
def test_parser_same_result_from_other_web_server(
    parsers_module, simulator_module, client_factory, other_web_server, slug
):
    sim = client_factory(
        simulator_module.create_app(simulator_module.DEFAULT_DATA_PATH)
    )
    from_simulator = sim.get(f"/catalog/{slug}").text
    from_other = httpx.get(f"{other_web_server}/{slug}.html", timeout=5)
    assert from_other.status_code == 200
    from_other.encoding = "utf-8"
    parser = PARSER_OF[slug]
    result_simulator = as_tuples(parsers_module.parse_page(parser, from_simulator))
    result_other = as_tuples(parsers_module.parse_page(parser, from_other.text))
    assert result_simulator == result_other == EXPECTED[slug]


# REQ-NF-007, REQ-NF-029: the system's code does not import the simulator — not
# even indirectly when the application and the parsers are loaded.
def test_system_does_not_load_simulator_module():
    code = (
        "import sys, spm.app, spm.update.parsers; "
        "sys.exit(1 if any(m == 'simulator' or m.startswith('simulator.') "
        "for m in sys.modules) else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT / "src",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

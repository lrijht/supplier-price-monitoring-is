"""T-07: supplier simulator (REQ-NF-013, REQ-NF-026...REQ-NF-029)."""

from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
NO_PRICE_MARK = "ціну уточнюйте"


def _page_text(html: str) -> str:
    """Text for value lookup: tags stripped, spaces removed, comma as decimal."""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[\s  ]+", "", text).replace(",", ".")


def _has_value(html: str, value: str) -> bool:
    return re.sub(r"\s+", "", value).replace(",", ".") in _page_text(html)


def _layout_markers(html: str) -> dict[str, bool]:
    return {
        "table": "<table" in html.lower(),
        "cards": re.search(r'class="[^"]*\bcard\b', html) is not None,
        "list": "<li" in html.lower(),
    }


def _supplier(data: dict, slug: str) -> dict:
    return next(s for s in data["suppliers"] if s["slug"] == slug)


def _skus_on_page(html: str, supplier: dict) -> list[str]:
    return [i["sku"] for i in supplier["items"] if _has_value(html, i["sku"])]


# REQ-NF-026, REQ-NF-005: each supplier page shows every item with SKU, name,
# unit and price, or the "no price" mark.
@pytest.mark.parametrize("slug", ["alfa", "beta", "vega"])
def test_page_shows_all_items(sim_client, sim_data, slug):
    resp = sim_client.get(f"/catalog/{slug}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    for item in _supplier(sim_data, slug)["items"]:
        for value in (item["sku"], item["name"], item["unit"]):
            assert _has_value(resp.text, value), value
        if item["price"] is not None:
            assert _has_value(resp.text, item["price"]), item["price"]
    assert NO_PRICE_MARK in resp.text


# REQ-NF-026: three layouts: table, cards, list.
@pytest.mark.parametrize(
    ("slug", "layout"), [("alfa", "table"), ("beta", "cards"), ("vega", "list")]
)
def test_each_supplier_has_its_own_layout(sim_client, slug, layout):
    markers = _layout_markers(sim_client.get(f"/catalog/{slug}").text)
    assert markers[layout]
    assert [k for k, v in markers.items() if v] == [layout]


# REQ-NF-026: an unknown catalogue address is not a supplier page.
def test_unknown_catalogue_is_404(sim_client):
    assert sim_client.get("/catalog/no-such-supplier").status_code == 404


# REQ-NF-026, REQ-NF-027: the shipped data file has 3 fictional suppliers, one
# per layout, all in mode "normal".
def test_default_data_file_has_three_suppliers(simulator_module):
    data = json.loads(Path(simulator_module.DEFAULT_DATA_PATH).read_text("utf-8"))
    suppliers = data["suppliers"]
    assert len(suppliers) == 3
    assert sorted(s["layout"] for s in suppliers) == ["cards", "list", "table"]
    assert all(s["mode"] == "normal" for s in suppliers)
    assert all(s["items"] for s in suppliers)


# REQ-NF-028, Р-111: the default delay of mode "slow" is set in the data file and
# is longer than 30 s (checked by value, without waiting).
def test_default_slow_delay_is_over_30_seconds(simulator_module):
    data = json.loads(Path(simulator_module.DEFAULT_DATA_PATH).read_text("utf-8"))
    assert all(s["delay_seconds"] > 30 for s in data["suppliers"])


# REQ-NF-027: a price change in the data file is served on the next request
# without restarting the simulator.
def test_price_change_applies_without_restart(sim_client, sim_data, write_sim_data):
    assert _has_value(sim_client.get("/catalog/alfa").text, "1250.50")
    _supplier(sim_data, "alfa")["items"][0]["price"] = "1300.00"
    write_sim_data(sim_data)
    html = sim_client.get("/catalog/alfa").text
    assert _has_value(html, "1300.00")
    assert not _has_value(html, "1250.50")


# REQ-NF-027: an added item appears and a removed item disappears.
def test_assortment_change_applies_without_restart(
    sim_client, sim_data, write_sim_data
):
    items = _supplier(sim_data, "beta")["items"]
    removed = items.pop(1)
    items.append({"sku": "Б-99", "name": "Шуруп 4х16", "unit": "шт", "price": "0.35"})
    write_sim_data(sim_data)
    html = sim_client.get("/catalog/beta").text
    assert _has_value(html, "Б-99")
    assert not _has_value(html, removed["sku"])


def _assert_others_normal(sim_client, sim_data, slug):
    for other in sim_data["suppliers"]:
        if other["slug"] == slug:
            continue
        resp = sim_client.get(f"/catalog/{other['slug']}")
        assert resp.status_code == 200
        assert len(_skus_on_page(resp.text, other)) == len(other["items"])


# REQ-NF-028: mode "normal" serves the full page.
def test_mode_normal(sim_client, sim_data):
    for supplier in sim_data["suppliers"]:
        resp = sim_client.get(f"/catalog/{supplier['slug']}")
        assert resp.status_code == 200
        assert len(_skus_on_page(resp.text, supplier)) == len(supplier["items"])


# REQ-NF-028, BDD-002: mode "unavailable" does not serve the page; the other
# suppliers stay "normal". The mode applies from the next request.
def test_mode_unavailable(sim_client, sim_data, write_sim_data):
    assert sim_client.get("/catalog/alfa").status_code == 200
    _supplier(sim_data, "alfa")["mode"] = "unavailable"
    write_sim_data(sim_data)
    resp = sim_client.get("/catalog/alfa")
    assert resp.status_code >= 500
    assert "А-1" not in resp.text
    _assert_others_normal(sim_client, sim_data, "alfa")


# REQ-NF-028, BDD-051: mode "broken" serves a page the parser cannot read: none
# of the three layouts is there. The other suppliers stay "normal".
def test_mode_broken_layout(sim_client, sim_data, write_sim_data):
    _supplier(sim_data, "alfa")["mode"] = "broken"
    write_sim_data(sim_data)
    resp = sim_client.get("/catalog/alfa")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert not any(_layout_markers(resp.text).values())
    _assert_others_normal(sim_client, sim_data, "alfa")


# REQ-NF-028, BDD-005: mode "reduced" keeps the number of items set in the data
# file. The other suppliers stay "normal".
@pytest.mark.parametrize("keep", [1, 2, 3])
def test_mode_reduced_assortment(sim_client, sim_data, write_sim_data, keep):
    supplier = _supplier(sim_data, "vega")
    supplier["mode"] = "reduced"
    supplier["keep_items"] = keep
    write_sim_data(sim_data)
    resp = sim_client.get("/catalog/vega")
    assert resp.status_code == 200
    assert _layout_markers(resp.text)["list"]
    assert len(_skus_on_page(resp.text, supplier)) == keep
    _assert_others_normal(sim_client, sim_data, "vega")


# REQ-NF-028, REQ-NF-013, BDD-003: mode "slow" with a 2 s delay and a client
# timeout of 1 s fails by timeout in about 1 s; the other suppliers answer at
# once. Runs against the simulator on a loopback address.
def test_mode_slow_times_out_quickly(live_simulator, sim_data, write_sim_data):
    supplier = _supplier(sim_data, "beta")
    supplier["mode"] = "slow"
    supplier["delay_seconds"] = 2
    write_sim_data(sim_data)
    started = time.monotonic()
    with pytest.raises(httpx.TimeoutException):
        httpx.get(f"{live_simulator}/catalog/beta", timeout=1.0)
    assert time.monotonic() - started < 1.9
    for slug in ("alfa", "vega"):
        assert httpx.get(f"{live_simulator}/catalog/{slug}", timeout=1.0).is_success


# REQ-NF-028: mode "slow" serves the full page after the delay from the data
# file (a short delay here, so the test stays fast).
def test_mode_slow_serves_page_after_delay(live_simulator, sim_data, write_sim_data):
    supplier = _supplier(sim_data, "alfa")
    supplier["mode"] = "slow"
    supplier["delay_seconds"] = 0.5
    write_sim_data(sim_data)
    started = time.monotonic()
    resp = httpx.get(f"{live_simulator}/catalog/alfa", timeout=3.0)
    elapsed = time.monotonic() - started
    assert resp.status_code == 200
    assert 0.5 <= elapsed < 2.5
    assert len(_skus_on_page(resp.text, supplier)) == len(supplier["items"])


# REQ-NF-028: switching back to "normal" applies on the next request.
def test_mode_change_back_to_normal(sim_client, sim_data, write_sim_data):
    _supplier(sim_data, "alfa")["mode"] = "unavailable"
    write_sim_data(sim_data)
    assert sim_client.get("/catalog/alfa").status_code >= 500
    _supplier(sim_data, "alfa")["mode"] = "normal"
    write_sim_data(sim_data)
    assert sim_client.get("/catalog/alfa").status_code == 200


# REQ-NF-029, П-6: the simulator lives in /simulator at the repository root.
def test_simulator_is_outside_src(simulator_module):
    location = Path(simulator_module.__file__).resolve()
    assert ROOT / "simulator" in location.parents
    assert ROOT / "src" not in location.parents


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


# REQ-NF-029, REQ-NF-007: /src holds no simulator code and does not import it.
def test_src_does_not_import_simulator():
    sources = list((ROOT / "src").rglob("*.py"))
    assert not [p for p in sources if "simulator" in p.relative_to(ROOT).parts]
    offenders = [p for p in sources if "simulator" in _imported_modules(p)]
    assert offenders == []

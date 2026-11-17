"""T-36: unit locked by prices, and the list "позиції, що потребують уваги".

REQ-F-009 (with prices, which B1 could not check), REQ-F-017 (the list),
REQ-F-066, REQ-F-068 (columns of the list), REQ-F-011 (mark "постачальник
неактивний"), REQ-F-057; BDD-028 (the list), BDD-052 (leaving the list); UC-07
(2а), UC-10; operation 15 (П-17, Н-37).

Screen: ``GET /attention-items?page=N`` (administrator). Items get the unit
"уп" on the simulator page after being linked to a material with "шт".
"""

from __future__ import annotations

import pytest
from helpers import API, NO_ACCESS, assert_problem, data_table, error_codes, page_text
from helpers_b2 import latest_run, row
from helpers_b3 import (
    SUPPLIER_INACTIVE,
    UNIT_MISMATCH,
    D,
    Market,
    attention,
    history_rows,
    lower_headers,
    row_text,
    screen,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

UNIT_LOCKED = "одиницю не можна змінити: є ціни або прив'язки"
# REQ-F-068: the columns of the list, exactly.
ATTENTION_COLUMNS = [
    "постачальник",
    "артикул",
    "найменування",
    "одиниця на сторінці",
    "одиниця матеріалу",
]


def material(client, mid: int) -> dict:
    return client.get(f"{API}/materials/{mid}").json()


def attention_skus(client) -> list[str]:
    return [r["supplier_item"]["sku"] for r in attention(client)]


def screen_skus(client, page: int = 1) -> list[str]:
    _, rows = data_table(screen(client, f"/attention-items?page={page}"))
    return [r[1] for r in rows]


@pytest.fixture
def v2(world):
    """В-2 of Вега linked to М1 ("шт"): 100,00 "шт" on 2026-10-08, then
    1000,00 "уп" on 2026-10-09 (BDD-052)."""
    m = Market(world, {"Вега": {"В-2": "М1"}, "Бета": {"Б-1": "М2"}}, start=D(7))
    m.day(D(8), {"Вега": {"В-2": "100.00"}, "Бета": {"Б-1": "50.00"}})
    m.day(D(9), {"Вега": {"В-2": ("1000.00", "уп")}, "Бета": {"Б-1": "50.00"}})
    return m


# --- REQ-F-009: the unit of a material with prices --------------------------------------------------


# REQ-F-009 criterion 1, Н-10: М1 has daily prices (its item was unlinked after
# the run) — changing the unit is refused with "одиницю не можна змінити: є ціни
# або прив'язки" (409 unit_locked), the unit stays "шт"; the same on the screen.
def test_unit_locked_by_prices(world, admin_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}})
    m.day(D(2), {"Альфа": {"А-1": "1000.00"}})
    world.unlink("А-1")
    mid = m.mid("М1")
    assert material(admin_client, mid)["linked_items_count"] == 0
    problem = assert_problem(
        admin_client.patch(f"{API}/materials/{mid}", json={"unit": "уп"}),
        409,
        "unit_locked",
    )
    assert error_codes(problem) == [("unit", "unit_locked")]
    assert UNIT_LOCKED in problem["detail"].replace("’", "'")
    resp = admin_client.post(
        f"/materials/{mid}",
        data={"name": "М1", "unit": "уп", "active": "on"},
        follow_redirects=False,
    )
    assert resp.status_code not in (302, 303)
    assert UNIT_LOCKED in page_text(resp.text)
    assert material(admin_client, mid)["unit"] == "шт"


# REQ-F-009 criterion 3: a material that had a link but never a price, after the
# link is removed, has neither prices nor links — the unit change is stored.
def test_unit_change_after_link_removed_without_prices(world, admin_client):
    Market(world, {"Альфа": {"А-1": "М1"}})
    world.unlink("А-1")
    mid = world.material_ids["М1"]
    resp = admin_client.patch(f"{API}/materials/{mid}", json={"unit": "уп"})
    assert resp.status_code == 200, resp.text
    assert material(admin_client, mid)["unit"] == "уп"


# --- REQ-F-017: the list -----------------------------------------------------------------------------


# BDD-028, REQ-F-017 criterion, П-17: В-2 linked to М1 ("шт") is parsed with "уп" —
# the daily price is stored with the mark, the run row of Вега has a warning, and
# В-2 is in the list with the page unit, the material unit and the date of the
# last marked price (API).
def test_item_with_other_unit_in_list_bdd028(v2, admin_client):
    world = v2.world
    assert history_rows(admin_client, v2.mid("М1"))[0] == (
        "2026-10-09",
        "Вега",
        "1000.00",
        True,
        False,
    )
    run = latest_run(world.admin)
    assert {"kind": "unit_mismatch", "sku": "В-2"} in row(run, "Вега")["warnings"]
    body = admin_client.get(f"{API}/attention-items").json()
    assert (body["page"], body["page_size"], body["total_items"]) == (1, 50, 1)
    (entry,) = body["items"]
    assert entry["supplier_item"] == {
        "id": world.item_ids["В-2"],
        "supplier": {"id": v2.sid("Вега"), "name": "Вега", "active": True},
        "sku": "В-2",
        "name": "Позиція В-2",
        "unit": "уп",
    }
    assert entry["material"] == {"id": v2.mid("М1"), "name": "М1", "unit": "шт"}
    assert entry["last_unit_mismatch_date"] == "2026-10-09"


# REQ-F-068 criterion, REQ-F-017: the screen has exactly the columns of REQ-F-068
# (the last — the date of the last price "одиниця не збігається") and the row of
# В-2 with "уп", "шт" and "2026-10-09".
def test_attention_screen_columns(v2, admin_client):
    html = screen(admin_client, "/attention-items")
    headers = lower_headers(html)
    assert len(headers) == 6
    assert headers[:5] == ATTENTION_COLUMNS
    assert headers[5].startswith("дата") and UNIT_MISMATCH in headers[5]
    _, rows = data_table(html)
    assert [r[:6] for r in rows] == [
        ["Вега", "В-2", "Позиція В-2", "уп", "шт", "2026-10-09"]
    ]


# BDD-052, REQ-F-066 criterion 1: the run of 2026-10-10 parses В-2 with 101,00 "шт"
# — В-2 leaves the list, and the price is stored without the mark.
def test_leaves_list_when_unit_matches_bdd052(v2, admin_client):
    v2.day(D(10), {"Вега": {"В-2": "101.00"}, "Бета": {"Б-1": "50.00"}})
    assert attention_skus(admin_client) == []
    assert screen_skus(admin_client) == []
    assert history_rows(admin_client, v2.mid("М1"))[0] == (
        "2026-10-10",
        "Вега",
        "101.00",
        False,
        False,
    )


# REQ-F-066 criterion 2: an item leaves the list right after its link is removed
# (no run needed) — and it is back among unlinked items.
def test_leaves_list_after_unlink(v2, admin_client):
    v2.world.unlink("В-2")
    assert attention_skus(admin_client) == []
    assert screen_skus(admin_client) == []
    unlinked = [r["sku"] for r in v2.world.unlinked()]
    assert "В-2" in unlinked


# REQ-F-066 criterion 2: an item leaves the list right after its link is changed —
# relinked to М3 with the unit "уп".
def test_leaves_list_after_relink(v2, admin_client):
    v2.world.material("М3", unit="уп")
    v2.world.link("В-2", "М3")
    assert attention_skus(admin_client) == []
    assert screen_skus(admin_client) == []


# REQ-F-011: an item of a deactivated supplier stays in the list with the mark
# "постачальник неактивний" (API: supplier.active false).
def test_inactive_supplier_marked_in_list(v2, admin_client):
    v2.world.set_active("Вега", False)
    (entry,) = attention(admin_client)
    assert entry["supplier_item"]["supplier"]["active"] is False
    _, rows = data_table(screen(admin_client, "/attention-items"))
    (found,) = rows
    assert SUPPLIER_INACTIVE in row_text(found)
    v2.world.set_active("Вега", True)
    _, rows = data_table(screen(admin_client, "/attention-items"))
    assert SUPPLIER_INACTIVE not in row_text(rows[0])


# --- REQ-F-057: order and pages ---------------------------------------------------------------------


# REQ-F-057 criterion: items of "Бета" (created first) and "Альфа" — first the
# items of "Альфа", then "Бета", within a supplier by sku; 51 items — 50 on the
# first page and 1 on the second (API and screen).
def test_attention_order_and_pages(world, admin_client):
    alfa = {f"А-{n:02d}": f"МА{n:02d}" for n in range(1, 26)}
    beta = {f"Б-{n:02d}": f"МБ{n:02d}" for n in range(1, 27)}
    m = Market(world, {"Бета": beta, "Альфа": alfa})
    m.day(
        D(2),
        {
            "Бета": {sku: ("10.00", "уп") for sku in beta},
            "Альфа": {sku: ("10.00", "уп") for sku in alfa},
        },
    )
    expected = sorted(alfa) + sorted(beta)
    pages = [
        admin_client.get(f"{API}/attention-items?page={p}").json() for p in (1, 2, 3)
    ]
    assert [len(p["items"]) for p in pages] == [50, 1, 0]
    assert (pages[0]["total_items"], pages[0]["total_pages"]) == (51, 2)
    assert [r["supplier_item"]["sku"] for p in pages for r in p["items"]] == expected
    html = screen(admin_client, "/attention-items")
    assert "page=2" in html
    assert screen_skus(admin_client, 1) == expected[:50]
    assert screen_skus(admin_client, 2) == expected[50:]


# REQ-F-057 criterion (П-3): skus "А-2", "А-10" and "А 3" of one supplier are in the
# order "А 3", "А-10", "А-2".
def test_attention_sku_order(world, admin_client):
    skus = {"А-2": "М1", "А-10": "М2", "А 3": "М3"}
    m = Market(world, {"Альфа": skus})
    m.day(D(2), {"Альфа": {sku: ("10.00", "уп") for sku in skus}})
    assert attention_skus(admin_client) == ["А 3", "А-10", "А-2"]
    assert screen_skus(admin_client) == ["А 3", "А-10", "А-2"]


# --- roles ------------------------------------------------------------------------------------------


# Н-37, REQ-F-005, REQ-NF-003: the manager gets 403 "немає доступу" for the list —
# through the API and on the screen — and sees none of its data.
def test_manager_no_access_to_attention_items(v2, manager_client):
    problem = assert_problem(
        manager_client.get(f"{API}/attention-items"), 403, "forbidden"
    )
    assert problem["detail"] == NO_ACCESS
    resp = manager_client.get("/attention-items")
    assert resp.status_code == 403
    text = page_text(resp.text)
    assert NO_ACCESS in text and "В-2" not in text


# REQ-F-057, contract: page "abc" or "0" — 422 page_invalid; a page past the end —
# 200 with empty items.
def test_attention_items_page_parameter(admin_client):
    for value in ("abc", "0"):
        problem = assert_problem(
            admin_client.get(f"{API}/attention-items?page={value}"),
            422,
            "validation_failed",
        )
        assert error_codes(problem) == [("page", "page_invalid")]
    body = admin_client.get(f"{API}/attention-items?page=5").json()
    assert (body["items"], body["page"]) == ([], 5)

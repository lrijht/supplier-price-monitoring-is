"""T-38: the comparison list and the comparison of a material (API and screens).

REQ-F-029 (the last known price takes part), REQ-F-035…REQ-F-039, REQ-F-057
(the list), REQ-F-059, REQ-F-065 (comparison), REQ-NF-030; BDD-023…BDD-025,
BDD-028 (comparison), BDD-050, BDD-052 (comparison), BDD-055; UC-02.

Prices are written by real runs on the simulator (``Market`` in helpers_b3);
"today" and staleness come from the controlled clock. Screens:
``GET /material-comparisons?page=N&q=…`` (the list) and
``GET /material-comparisons/{id}`` (the material).
"""

from __future__ import annotations

import pytest
from helpers import API, all_pages, create_material, data_table, page_text
from helpers_b2 import kyiv, move_to
from helpers_b3 import (
    CHEAPEST,
    NO_PRICE_YET,
    STALE,
    UNIT_MISMATCH,
    D,
    Market,
    compact,
    comparison,
    comparison_list,
    comparison_rows,
    hrefs,
    list_row,
    row_text,
    screen,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

DASH = "—"
# REQ-F-057 criterion (П-3): the alphabetical order of these names.
ALPHABET_NAMES = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
ALPHABET_ORDER = ["2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак", "Alpha"]


def three(world, names=("Альфа", "Бета", "Вега")) -> Market:
    """One item of each supplier linked to М1."""
    prefix = {"Альфа": "А", "Бета": "Б", "Вега": "В", "Гама": "Г", "Ірпінь": "І"}
    return Market(world, {n: {f"{prefix[n]}-1": "М1"} for n in names})


def material_screen_row(client, material_id: int, supplier: str) -> str:
    """Text of the supplier's row on the material comparison screen."""
    _, rows = data_table(screen(client, f"/material-comparisons/{material_id}"))
    (found,) = [r for r in rows if supplier in row_text(r)]
    return row_text(found)


def material_screen_cells(client, material_id: int, supplier: str) -> dict[str, str]:
    """The supplier's row on the material comparison screen, cell by header."""
    headers, rows = data_table(screen(client, f"/material-comparisons/{material_id}"))
    (found,) = [r for r in rows if supplier in row_text(r)]
    return dict(zip(headers, found, strict=False))


def list_screen_row(client, material: str, query: str = "") -> str:
    _, rows = data_table(screen(client, f"/material-comparisons{query}"))
    (found,) = [r for r in rows if material in r[0]]
    return row_text(found)


def cheapest(rows: dict[str, dict]) -> set[str]:
    return {name for name, r in rows.items() if r["cheapest"]}


# --- REQ-F-036: the comparison of a material ----------------------------------------------------


# REQ-F-036 criterion 1, BDD-025, П-22: today А 1000,00 and Б 1100,00 — А is the
# cheapest with 0,0 % and 0,00 грн; Б has +10,0 % and +100,00 грн; the list shows
# "Альфа, 1000,00 грн".
def test_cheapest_and_difference_bdd025(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(10), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00"}})
    body = comparison(manager_client, m.mid("М1"))
    assert body["material"] == {"id": m.mid("М1"), "name": "М1", "active": True}
    rows = {r["supplier"]["name"]: r for r in body["items"]}
    assert set(rows) == {"Альфа", "Бета"}
    assert rows["Альфа"]["daily_price"] == {
        "price": "1000.00",
        "date": "2026-10-10",
        "unit_mismatch": False,
    }
    assert (rows["Альфа"]["cheapest"], rows["Альфа"]["stale"]) == (True, False)
    assert rows["Альфа"]["difference_from_cheapest"] == {
        "percent": 0.0,
        "amount": "0.00",
    }
    assert (rows["Бета"]["cheapest"], rows["Бета"]["stale"]) == (False, False)
    assert rows["Бета"]["difference_from_cheapest"] == {
        "percent": 10.0,
        "amount": "100.00",
    }
    assert list_row(manager_client, "М1")["cheapest_supplier"] == {
        "id": m.sid("Альфа"),
        "name": "Альфа",
    }
    assert list_row(manager_client, "М1")["price"] == "1000.00"


# REQ-F-036, BDD-025, REQ-NF-030 on the screens: the cheapest row is marked
# "найдешевша", the other is not; differences "+10,0 %" and "+100,00 грн"; the
# date "2026-10-10"; the list row shows "Альфа" and "1000,00".
def test_cheapest_and_difference_on_screens(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(10), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00"}})
    alfa = material_screen_row(manager_client, m.mid("М1"), "Альфа")
    beta = material_screen_row(manager_client, m.mid("М1"), "Бета")
    assert CHEAPEST in alfa and CHEAPEST not in beta
    assert "2026-10-10" in alfa and "2026-10-10" in beta
    assert "1000,00" in compact(alfa) and "0,0%" in compact(alfa)
    assert "1100,00" in compact(beta)
    assert "+10,0%" in compact(beta) and "+100,00" in compact(beta)
    listed = list_screen_row(manager_client, "М1")
    assert "Альфа" in listed and "1000,00" in compact(listed)


# REQ-F-036 criterion 2: А 1000,00, Б 1000,00 and В 1100,00 today — А and Б are
# both marked, both with 0,0 %; В has +10,0 %.
def test_all_minimal_prices_marked(world, manager_client):
    m = three(world)
    m.day(
        D(10),
        {
            "Альфа": {"А-1": "1000.00"},
            "Бета": {"Б-1": "1000.00"},
            "Вега": {"В-1": "1100.00"},
        },
    )
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert cheapest(rows) == {"Альфа", "Бета"}
    for name in ("Альфа", "Бета"):
        assert rows[name]["difference_from_cheapest"]["percent"] == 0.0
    assert rows["Вега"]["difference_from_cheapest"]["percent"] == 10.0
    marked = [
        name
        for name in ("Альфа", "Бета", "Вега")
        if CHEAPEST in material_screen_row(manager_client, m.mid("М1"), name)
    ]
    assert marked == ["Альфа", "Бета"]


# REQ-F-036 criterion 5: 1000,00 and 1012,50 — +1,3 % (1,25 % rounded half away
# from zero) and +12,50 грн.
def test_difference_rounding(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(10), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1012.50"}})
    beta = comparison_rows(manager_client, m.mid("М1"))["Бета"]
    assert beta["difference_from_cheapest"] == {"percent": 1.3, "amount": "12.50"}
    text = compact(material_screen_row(manager_client, m.mid("М1"), "Бета"))
    assert "+1,3%" in text and "+12,50" in text


# BDD-050, REQ-F-035 criterion 2: today 2026-10-10; Альфа 1000,00 from
# 2026-10-09, Бета 1000,00 and Гама 1100,00 from 2026-10-10 — Альфа and Бета are
# marked with 0,0 %; the list shows "Бета, 1000,00" (the later date wins).
def test_equal_minimum_later_date_wins_bdd050(world, manager_client):
    m = three(world, ("Альфа", "Бета", "Гама"))
    m.day(D(9), {"Альфа": {"А-1": "1000.00"}})
    m.day(D(10), {"Бета": {"Б-1": "1000.00"}, "Гама": {"Г-1": "1100.00"}})
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert rows["Альфа"]["daily_price"]["date"] == "2026-10-09"
    assert cheapest(rows) == {"Альфа", "Бета"}
    assert rows["Альфа"]["difference_from_cheapest"]["percent"] == 0.0
    assert rows["Бета"]["difference_from_cheapest"]["percent"] == 0.0
    row = list_row(manager_client, "М1")
    assert (row["cheapest_supplier"]["name"], row["price"]) == ("Бета", "1000.00")
    assert "Бета" in list_screen_row(manager_client, "М1")


# REQ-F-035 criterion 2–3, REQ-F-057 (П-3): equal minimum on the same date — the
# first supplier by name: "Альфа" before "Бета", and "Альфа" before "Ірпінь"
# (Ірпінь created first, so the creation order does not decide).
@pytest.mark.parametrize("names", [("Бета", "Альфа"), ("Ірпінь", "Альфа")])
def test_equal_minimum_same_date_first_by_name(world, manager_client, names):
    m = three(world, names)
    prefix = {"Альфа": "А-1", "Бета": "Б-1", "Ірпінь": "І-1"}
    m.day(D(10), {n: {prefix[n]: "1000.00"} for n in names})
    row = list_row(manager_client, "М1")
    assert row["cheapest_supplier"]["name"] == "Альфа"
    listed = list_screen_row(manager_client, "М1")
    assert "Альфа" in listed and names[0] not in listed


# REQ-F-035 criterion 4, REQ-F-038 criterion 3: a material whose only price is
# stale has no suitable price — the list shows "—" (API: null supplier and
# price); in its comparison no supplier is marked and every difference is "—".
def test_no_suitable_price_dash(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(5), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00"}})
    m.world.at(2026, 10, 10)
    row = list_row(manager_client, "М1")
    assert (row["cheapest_supplier"], row["price"]) == (None, None)
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert cheapest(rows) == set()
    assert all(r["stale"] is True for r in rows.values())
    assert all(r["difference_from_cheapest"] is None for r in rows.values())
    listed = list_screen_row(manager_client, "М1")
    assert DASH in listed and "Альфа" not in listed and "Бета" not in listed
    for name in ("Альфа", "Бета"):
        text = material_screen_row(manager_client, m.mid("М1"), name)
        assert CHEAPEST not in text and DASH in text


# REQ-F-036 ("ціни ще немає"), REQ-F-029: a linked item with no daily price yet
# — the row shows "ціни ще немає" and "—"; API: daily_price, stale and difference
# are null, cheapest false.
def test_linked_item_without_prices(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(10), {"Бета": {"Б-1": "1100.00"}})
    alfa = comparison_rows(manager_client, m.mid("М1"))["Альфа"]
    assert alfa == {
        "supplier": {"id": m.sid("Альфа"), "name": "Альфа"},
        "daily_price": None,
        "stale": None,
        "cheapest": False,
        "difference_from_cheapest": None,
    }
    text = material_screen_row(manager_client, m.mid("М1"), "Альфа")
    assert NO_PRICE_YET in text and DASH in text and CHEAPEST not in text


# REQ-F-029 criterion 3: А-1 has "ціну уточнюйте" today — the comparison shows its
# last known price 1000,00 with the date 2026-10-09, and it is the cheapest
# (not stale).
def test_price_to_clarify_keeps_last_known(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(9), {"Альфа": {"А-1": "1000.00"}})
    m.day(D(10), {"Альфа": {"А-1": None}, "Бета": {"Б-1": "1100.00"}})
    alfa = comparison_rows(manager_client, m.mid("М1"))["Альфа"]
    assert alfa["daily_price"] == {
        "price": "1000.00",
        "date": "2026-10-09",
        "unit_mismatch": False,
    }
    assert (alfa["stale"], alfa["cheapest"]) == (False, True)
    text = material_screen_row(manager_client, m.mid("М1"), "Альфа")
    assert "2026-10-09" in text and CHEAPEST in text


# --- REQ-F-038: staleness --------------------------------------------------------------------------


# BDD-023, BDD-024, REQ-F-038 criterion: today 2026-10-10; А 950,00 from
# 2026-10-07 is "застаріла" and not the cheapest — Б 1000,00 from 2026-10-10 is;
# А from 2026-10-08 is not stale and is the cheapest.
@pytest.mark.parametrize(("alfa_day", "stale"), [(7, True), (8, False)])
def test_stale_boundary(world, manager_client, alfa_day, stale):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(alfa_day), {"Альфа": {"А-1": "950.00"}})
    m.day(D(10), {"Бета": {"Б-1": "1000.00"}})
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert rows["Альфа"]["stale"] is stale
    assert cheapest(rows) == ({"Бета"} if stale else {"Альфа"})
    if stale:
        assert rows["Альфа"]["difference_from_cheapest"] is None
    alfa = material_screen_row(manager_client, m.mid("М1"), "Альфа")
    assert (STALE in alfa) is stale
    assert (CHEAPEST in alfa) is not stale
    assert f"2026-10-0{alfa_day}" in alfa
    # REQ-F-036 criterion 3 on the screen, while Бета's price is suitable: the
    # stale row shows "—" in both difference columns; a fresh cheapest — 0,0 %.
    cells = material_screen_cells(manager_client, m.mid("М1"), "Альфа")
    differences = (cells["Різниця, %"], cells["Різниця, грн"])
    if stale:
        assert differences == (DASH, DASH)
    else:
        assert compact(differences[0]) == "0,0%"
        assert DASH not in differences


# REQ-F-039 criterion 2, REQ-F-038: the price from 2026-10-08 at 23:59 on
# 2026-10-10 is not stale; at 00:00 on 2026-10-11, without a new run, it is
# stale on the next opening (API, both screens).
def test_stale_at_midnight_without_run(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(8), {"Альфа": {"А-1": "950.00"}})
    move_to(world.clock, kyiv(2026, 10, 10, 23, 59))
    assert comparison_rows(manager_client, m.mid("М1"))["Альфа"]["stale"] is False
    assert list_row(manager_client, "М1")["price"] == "950.00"
    assert STALE not in material_screen_row(manager_client, m.mid("М1"), "Альфа")
    move_to(world.clock, kyiv(2026, 10, 11, 0, 0))
    alfa = comparison_rows(manager_client, m.mid("М1"))["Альфа"]
    assert (alfa["stale"], alfa["cheapest"]) == (True, False)
    assert list_row(manager_client, "М1")["price"] is None
    assert STALE in material_screen_row(manager_client, m.mid("М1"), "Альфа")
    assert DASH in list_screen_row(manager_client, "М1")


# REQ-F-039 criterion 1: prices of a finished run are in the comparison on the
# next opening, without any action of the user.
def test_comparison_built_when_opened(world, manager_client):
    m = three(world, ("Альфа", "Бета"))
    m.day(D(9), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00"}})
    assert list_row(manager_client, "М1")["cheapest_supplier"]["name"] == "Альфа"
    m.day(D(10), {"Альфа": {"А-1": "1200.00"}, "Бета": {"Б-1": "1100.00"}})
    assert list_row(manager_client, "М1")["cheapest_supplier"]["name"] == "Бета"
    assert "Бета" in list_screen_row(manager_client, "М1")


# --- REQ-F-037: what does not take part ---------------------------------------------------------------


# REQ-F-037 criterion: for each of the four cases А's price 900,00, lower than the
# rest, is not the cheapest and does not change the differences — Б 1000,00 is
# the cheapest, В 1100,00 has +10,0 % and +100,00 грн, the list shows "Бета":
# relinked / unlinked item (not linked now), deactivated supplier, "одиниця не
# збігається", stale price.
@pytest.mark.parametrize(
    "case", ["relinked", "unlinked", "inactive_supplier", "unit_mismatch", "stale"]
)
def test_excluded_prices_do_not_take_part(world, manager_client, case):
    m = three(world)
    others = {"Бета": {"Б-1": "1000.00"}, "Вега": {"В-1": "1100.00"}}
    if case == "stale":
        m.day(D(7), {"Альфа": {"А-1": "900.00"}})
        m.day(D(10), others)
    elif case == "unit_mismatch":
        m.day(D(10), {"Альфа": {"А-1": ("900.00", "уп")}, **others})
    else:
        m.day(D(10), {"Альфа": {"А-1": "900.00"}, **others})
    if case == "relinked":
        world.material("М2")
        world.link("А-1", "М2")
    elif case == "unlinked":
        world.unlink("А-1")
    elif case == "inactive_supplier":
        world.set_active("Альфа", False)
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert cheapest(rows) == {"Бета"}
    assert rows["Вега"]["difference_from_cheapest"] == {
        "percent": 10.0,
        "amount": "100.00",
    }
    if case in ("relinked", "unlinked", "inactive_supplier"):
        assert "Альфа" not in rows
    else:
        assert rows["Альфа"]["cheapest"] is False
        assert rows["Альфа"]["difference_from_cheapest"] is None
    row = list_row(manager_client, "М1")
    assert (row["cheapest_supplier"]["name"], row["price"]) == ("Бета", "1000.00")
    assert "Бета" in list_screen_row(manager_client, "М1")


# BDD-055, REQ-F-036 criterion 4: А-3 (900,00) and Б (1000,00) priced for М1 on
# 2026-10-05; after that run А-3 is relinked to М2. On 2026-10-06 before a run:
# М1 has no row of Альфа and Бета is the cheapest; М2 shows Альфа with "ціни ще
# немає" and "—".
def test_comparison_after_relink_bdd055(world, manager_client):
    m = Market(world, {"Альфа": {"А-3": "М1"}, "Бета": {"Б-1": "М1"}})
    m.day(D(5), {"Альфа": {"А-3": "900.00"}, "Бета": {"Б-1": "1000.00"}})
    world.material("М2")
    world.link("А-3", "М2")
    world.at(2026, 10, 6, 1, 0)
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert set(rows) == {"Бета"}
    assert cheapest(rows) == {"Бета"}
    _, screen_rows = data_table(
        screen(manager_client, f"/material-comparisons/{m.mid('М1')}")
    )
    assert not [r for r in screen_rows if "Альфа" in row_text(r)]
    alfa = comparison_rows(manager_client, m.mid("М2"))["Альфа"]
    assert (alfa["daily_price"], alfa["difference_from_cheapest"]) == (None, None)
    text = material_screen_row(manager_client, m.mid("М2"), "Альфа")
    assert NO_PRICE_YET in text and DASH in text


# --- REQ-F-065, BDD-028, BDD-052: "одиниця не збігається" -------------------------------------------


# REQ-F-065 criterion, BDD-052 (comparison): В-2 had 100,00 "шт" on 2026-10-08;
# on 2026-10-09 the page shows 1000,00 "уп". The comparison shows 100,00 from
# 2026-10-08 without the mark; on 2026-10-11 it is stale and not the cheapest.
def test_unit_mismatch_takes_last_price_without_mark(world, manager_client):
    m = Market(world, {"Вега": {"В-2": "М1"}})
    m.day(D(8), {"Вега": {"В-2": "100.00"}})
    m.day(D(9), {"Вега": {"В-2": ("1000.00", "уп")}})
    row = comparison_rows(manager_client, m.mid("М1"))["Вега"]
    assert row["daily_price"] == {
        "price": "100.00",
        "date": "2026-10-08",
        "unit_mismatch": False,
    }
    assert (row["stale"], row["cheapest"]) == (False, True)
    text = material_screen_row(manager_client, m.mid("М1"), "Вега")
    assert "100,00" in compact(text) and "2026-10-08" in text
    world.at(2026, 10, 11)
    row = comparison_rows(manager_client, m.mid("М1"))["Вега"]
    assert (row["stale"], row["cheapest"]) == (True, False)
    assert list_row(manager_client, "М1")["price"] is None


# REQ-F-065 (no price without the mark at all), BDD-028: the only price of В-2 is
# "одиниця не збігається" — the row shows it with the mark and "—"; it is not the
# cheapest, Бета is.
def test_only_mismatched_price_shown_with_dash(world, manager_client):
    m = Market(world, {"Бета": {"Б-1": "М1"}, "Вега": {"В-2": "М1"}})
    m.day(D(10), {"Бета": {"Б-1": "1000.00"}, "Вега": {"В-2": ("90.00", "уп")}})
    rows = comparison_rows(manager_client, m.mid("М1"))
    assert rows["Вега"]["daily_price"] == {
        "price": "90.00",
        "date": "2026-10-10",
        "unit_mismatch": True,
    }
    assert rows["Вега"]["difference_from_cheapest"] is None
    assert cheapest(rows) == {"Бета"}
    text = material_screen_row(manager_client, m.mid("М1"), "Вега")
    assert UNIT_MISMATCH in text and DASH in text and CHEAPEST not in text


# --- REQ-F-035, REQ-F-057, REQ-F-059: the comparison list ------------------------------------------------


# REQ-F-057 criterion: 120 materials — the list pages hold 50, 50 and 20, the
# first page the first 50 by name (API and screen).
def test_list_120_materials_pages(admin_client, manager_client):
    names = [f"Матеріал {n:03d}" for n in range(120, 0, -1)]
    for name in names:
        create_material(admin_client, name)
    pages = [
        manager_client.get(f"{API}/material-comparisons?page={p}").json()
        for p in (1, 2, 3, 4)
    ]
    assert [len(p["items"]) for p in pages] == [50, 50, 20, 0]
    assert (pages[0]["total_items"], pages[0]["total_pages"]) == (120, 3)
    assert pages[0]["page_size"] == 50
    listed = [r["material"]["name"] for p in pages for r in p["items"]]
    assert listed == sorted(names)
    _, rows = data_table(screen(manager_client, "/material-comparisons"))
    assert [r[0] for r in rows] == sorted(names)[:50]
    assert "page=2" in screen(manager_client, "/material-comparisons")
    _, rows = data_table(screen(manager_client, "/material-comparisons?page=3"))
    assert [r[0] for r in rows] == sorted(names)[100:]


# REQ-F-057 criterion (П-3): "Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама",
# "2 Плита", "Альфа" are listed as "2 Плита", "Альфа", "бета", "Гама", "Ґанок",
# "Іскра", "Їжак", "Alpha".
def test_list_alphabetical_order(admin_client, manager_client):
    for name in ALPHABET_NAMES:
        create_material(admin_client, name)
    listed = [r["material"]["name"] for r in comparison_list(manager_client)]
    assert listed == ALPHABET_ORDER
    _, rows = data_table(screen(manager_client, "/material-comparisons"))
    assert [r[0] for r in rows] == ALPHABET_ORDER


# REQ-F-059 criterion: search "лдсп" shows "ЛДСП Білий 18 мм" (any case) and no
# material without "лдсп" in the name (API and the screen's search field q).
def test_list_search_case_insensitive(admin_client, manager_client):
    for name in ("ЛДСП Білий 18 мм", "Кромка біла 2 мм", "Плита лдсп сіра"):
        create_material(admin_client, name)
    found = [r["material"]["name"] for r in comparison_list(manager_client, "лдсп")]
    assert found == ["ЛДСП Білий 18 мм", "Плита лдсп сіра"]
    html = screen(manager_client, "/material-comparisons?q=лдсп")
    _, rows = data_table(html)
    assert [r[0] for r in rows] == ["ЛДСП Білий 18 мм", "Плита лдсп сіра"]
    assert "Кромка" not in page_text(html)
    upper = [r["material"]["name"] for r in comparison_list(manager_client, "ЛДСП")]
    assert upper == found


# REQ-F-035, REQ-F-049: the list holds active materials only; each row leads to the
# comparison of its material (UC-02).
def test_list_active_materials_with_links(admin_client, manager_client):
    m1 = create_material(admin_client, "М1")
    m2 = create_material(admin_client, "М2")
    resp = admin_client.patch(f"{API}/materials/{m2['id']}", json={"active": False})
    assert resp.status_code == 200
    names = [
        r["material"]["name"]
        for r in all_pages(manager_client, f"{API}/material-comparisons")
    ]
    assert names == ["М1"]
    html = screen(manager_client, "/material-comparisons")
    assert any(h.endswith(f"/material-comparisons/{m1['id']}") for h in hrefs(html))
    assert "М2" not in page_text(html)

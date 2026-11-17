"""T-32: the price history of a material (screen and operation 20).

REQ-F-016 (shown by material), REQ-F-040, REQ-F-041, REQ-F-057 (the choice of
the material), REQ-NF-030; BDD-013 (history), BDD-026, BDD-036, BDD-042; UC-03.

Screen: ``GET /price-history?material_id=N&period=P`` — a GET form with
``<select name="material_id">`` (the choice of the material), the period
``period`` (``last_7_days``, ``last_30_days``, ``all`` — the values of the API)
and the option "показати неактивні" (field ``show_inactive``); the data table
has the columns "дата", "постачальник", "ціна" first. Prices come from real
runs on the simulator.
"""

from __future__ import annotations

import pytest
from helpers import API, create_material, data_table, forms, page_text
from helpers_b2 import item
from helpers_b3 import (
    AT_PERIOD_START,
    SHOW_INACTIVE,
    UNIT_MISMATCH,
    D,
    Market,
    compact,
    feed,
    history_rows,
    row_text,
    screen,
    select_options,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

ALPHABET_NAMES = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
ALPHABET_ORDER = ["2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак", "Alpha"]


def history_screen(
    client, material_id: int, period: str = "all", extra: str = ""
) -> str:
    return screen(
        client, f"/price-history?material_id={material_id}&period={period}{extra}"
    )


def screen_history(client, material_id: int, period: str = "all") -> list[tuple]:
    """Rows of the screen: ``(date, supplier, price without spaces, marks)``."""
    html = history_screen(client, material_id, period)
    headers, rows = data_table(html)
    assert [h.lower() for h in headers[:3]] == ["дата", "постачальник", "ціна"]
    result = []
    for r in rows:
        text = row_text(r)
        marks = {m for m in (UNIT_MISMATCH, AT_PERIOD_START) if m in text}
        result.append((r[0], r[1], compact(r[2]), marks))
    return result


def show_inactive_value(html: str) -> str:
    for form in forms(html):
        for field in form["inputs"]:
            if field.get("name") == "show_inactive":
                return field.get("value") or "on"
    raise AssertionError("no show_inactive field on the history screen")


# --- REQ-F-040: the table of changes ---------------------------------------------------------------


# BDD-036, REQ-F-040 criterion 1, П-15: А's daily prices 2026-10-01…2026-10-05 are
# 1000; 1000; 1010; 1010; 1000 — the whole period holds three rows: 10-01 1000,00;
# 10-03 1010,00; 10-05 1000,00 (newest first), for the manager (API and screen).
def test_history_shows_only_changes_bdd036(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(30, 9))
    for day, price in zip(
        range(1, 6),
        ["1000.00", "1000.00", "1010.00", "1010.00", "1000.00"],
        strict=True,
    ):
        m.day(D(day), {"Альфа": {"А-1": price}})
    assert history_rows(manager_client, m.mid("М1")) == [
        ("2026-10-05", "Альфа", "1000.00", False, False),
        ("2026-10-03", "Альфа", "1010.00", False, False),
        ("2026-10-01", "Альфа", "1000.00", False, False),
    ]
    rows = screen_history(manager_client, m.mid("М1"))
    assert [(r[0], r[1], r[3]) for r in rows] == [
        ("2026-10-05", "Альфа", set()),
        ("2026-10-03", "Альфа", set()),
        ("2026-10-01", "Альфа", set()),
    ]
    for row, price in zip(rows, ["1000,00", "1010,00", "1000,00"], strict=True):
        assert price in row[2]


# REQ-F-040 criteria 2 and 6: today 2026-10-10, "7 днів". Бета 1200,00 since
# 2026-09-01 (unchanged on later dates); Альфа 1000,00 from 2026-10-05 (its
# first price) and 1010,00 from 2026-10-08. Rows: 10-08 Альфа 1010,00; 10-05
# Альфа 1000,00; 09-01 Бета 1200,00 "чинна на початок періоду" — last.
def test_seven_days_with_price_effective_at_start(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М1"}}, start=D(31, 8))
    m.day(D(1, 9), {"Альфа": {"А-1": None}, "Бета": {"Б-1": "1200.00"}})
    m.day(D(5), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1200.00"}})
    m.day(D(8), {"Альфа": {"А-1": "1010.00"}, "Бета": {"Б-1": "1200.00"}})
    world.at(2026, 10, 10)
    assert history_rows(manager_client, m.mid("М1"), "last_7_days") == [
        ("2026-10-08", "Альфа", "1010.00", False, False),
        ("2026-10-05", "Альфа", "1000.00", False, False),
        ("2026-09-01", "Бета", "1200.00", False, True),
    ]
    rows = screen_history(manager_client, m.mid("М1"), "last_7_days")
    assert [(r[0], r[1], r[3]) for r in rows] == [
        ("2026-10-08", "Альфа", set()),
        ("2026-10-05", "Альфа", set()),
        ("2026-09-01", "Бета", {AT_PERIOD_START}),
    ]
    assert "1200,00" in rows[2][2]


# REQ-F-040 criterion 2 (second part): Бета's price changed on 2026-10-04, the
# first date of the 7-day period — the row 2026-10-04 has no mark, and the older
# price is not shown.
def test_change_on_first_date_of_period_has_no_mark(world, manager_client):
    m = Market(world, {"Бета": {"Б-1": "М1"}}, start=D(31, 8))
    m.day(D(1, 9), {"Бета": {"Б-1": "1200.00"}})
    m.day(D(4), {"Бета": {"Б-1": "1250.00"}})
    world.at(2026, 10, 10)
    assert history_rows(manager_client, m.mid("М1"), "last_7_days") == [
        ("2026-10-04", "Бета", "1250.00", False, False),
    ]
    rows = screen_history(manager_client, m.mid("М1"), "last_7_days")
    assert [(r[0], r[3]) for r in rows] == [("2026-10-04", set())]


# REQ-F-040 (period bounds): "30 днів" is today and 29 previous dates — on
# 2026-10-30 a change on 2026-10-01 is a plain row; on 2026-10-31 it is the
# price effective at the start of the period.
@pytest.mark.parametrize(("today", "marked"), [(30, False), (31, True)])
def test_thirty_days_bounds(world, manager_client, today, marked):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(30, 9))
    m.day(D(1), {"Альфа": {"А-1": "1000.00"}})
    world.at(2026, 10, today)
    assert history_rows(manager_client, m.mid("М1"), "last_30_days") == [
        ("2026-10-01", "Альфа", "1000.00", False, marked),
    ]


# REQ-F-040 criteria 3 and 5: a price "одиниця не збігається" is shown with the
# mark; the same sum without and then with the mark is two rows; a date without a
# daily price ("ціну уточнюйте") has no row.
def test_unit_mismatch_mark_and_days_without_price(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(30, 9))
    m.day(D(1), {"Альфа": {"А-1": "1000.00"}})
    m.day(D(2), {"Альфа": {"А-1": ("1000.00", "уп")}})
    m.day(D(3), {"Альфа": {"А-1": None}})
    assert history_rows(manager_client, m.mid("М1")) == [
        ("2026-10-02", "Альфа", "1000.00", True, False),
        ("2026-10-01", "Альфа", "1000.00", False, False),
    ]
    rows = screen_history(manager_client, m.mid("М1"))
    assert [(r[0], r[3]) for r in rows] == [
        ("2026-10-02", {UNIT_MISMATCH}),
        ("2026-10-01", set()),
    ]
    assert "2026-10-03" not in page_text(history_screen(manager_client, m.mid("М1")))


# REQ-F-040 criterion 4: rows of different suppliers differ by the column
# "постачальник"; equal prices of two suppliers are both shown.
def test_rows_of_suppliers_distinguished(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М1"}}, start=D(30, 9))
    m.day(D(1), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1000.00"}})
    rows = history_rows(manager_client, m.mid("М1"))
    assert sorted(r[1] for r in rows) == ["Альфа", "Бета"]
    assert sorted(r[1] for r in screen_history(manager_client, m.mid("М1"))) == [
        "Альфа",
        "Бета",
    ]


# REQ-F-040: the price is compared with the previous price of the same supplier
# even if another item represented it — А-1 1000,00, then А-2 of the same
# supplier linked to М1 instead with 1000,00 — no new row; 1010,00 — a new row.
def test_same_supplier_other_item_compared(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(30, 9))
    m.day(D(1), {"Альфа": {"А-1": "1000.00"}})
    world.page("Альфа", [item("А-1", "1000.00"), item("А-2", "1000.00")])
    world.at(2026, 10, 2)
    world.run()
    world.unlink("А-1")
    world.link("А-2", "М1")
    m.day(D(3), {"Альфа": {"А-1": "1000.00", "А-2": "1000.00"}})
    m.day(D(4), {"Альфа": {"А-1": "1000.00", "А-2": "1010.00"}})
    assert history_rows(manager_client, m.mid("М1")) == [
        ("2026-10-04", "Альфа", "1010.00", False, False),
        ("2026-10-01", "Альфа", "1000.00", False, False),
    ]


# --- REQ-F-041, BDD-013: prices kept for ever ---------------------------------------------------------------


# BDD-013, REQ-F-041 criterion: base 1000,00, threshold 1 % — 1005,00 (0,5 %) makes
# no event, but the history shows 1005,00.
def test_change_below_threshold_in_history_not_in_feed(world, manager_client):
    world.linked_with_base("Альфа", "alfa", [item("А-1", "1000.00")], {"А-1": "М1"})
    world.page("Альфа", [item("А-1", "1005.00")])
    world.at(2026, 10, 3)
    world.run()
    mid = world.material_ids["М1"]
    assert [e["kind"] for e in feed(manager_client, material_id=mid)] == ["appeared"]
    assert history_rows(manager_client, mid)[0] == (
        "2026-10-03",
        "Альфа",
        "1005.00",
        False,
        False,
    )
    assert "1005,00" in compact(history_screen(manager_client, mid))


# REQ-F-041 criterion: the prices of the oldest date are in "весь період" (as a
# plain row), and the screen offers no deletion of prices.
def test_oldest_prices_in_whole_period_no_delete(world, admin_client, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(31, 8))
    m.day(D(1, 9), {"Альфа": {"А-1": "900.00"}})
    m.day(D(5), {"Альфа": {"А-1": "1000.00"}})
    world.at(2026, 10, 10)
    assert history_rows(manager_client, m.mid("М1"))[-1] == (
        "2026-09-01",
        "Альфа",
        "900.00",
        False,
        False,
    )
    for client in (admin_client, manager_client):
        html = history_screen(client, m.mid("М1"))
        assert "2026-09-01" in page_text(html)
        text = page_text(html).lower()
        assert "видалити" not in text and "вилучити" not in text
        assert not [
            f for f in forms(html) if f["method"] == "post" and "delete" in f["action"]
        ]
    resp = admin_client.delete(f"{API}/materials/{m.mid('М1')}/price-history")
    assert resp.status_code == 405
    assert len(history_rows(manager_client, m.mid("М1"))) == 2


# --- REQ-F-016: prices stay with their material -----------------------------------------------------------


# BDD-026, REQ-F-016 criterion 1: А-3 linked to М1 has prices 2026-10-01…10-05;
# relinked to М2 after the run of 2026-10-05; the run of 2026-10-06 writes its
# price — М1 history keeps 10-01…10-05, М2 has only 10-06, and М2 gets "з'явився".
def test_relink_does_not_rewrite_history_bdd026(world, manager_client):
    m = Market(world, {"Альфа": {"А-3": "М1"}}, start=D(30, 9))
    for day in range(1, 6):
        m.day(D(day), {"Альфа": {"А-3": f"{1000 + day}.00"}})
    world.material("М2")
    world.link("А-3", "М2")
    m.day(D(6), {"Альфа": {"А-3": "1006.00"}})
    assert [r[0] for r in history_rows(manager_client, m.mid("М1"))] == [
        f"2026-10-0{d}" for d in range(5, 0, -1)
    ]
    assert history_rows(manager_client, m.mid("М2")) == [
        ("2026-10-06", "Альфа", "1006.00", False, False)
    ]
    assert [e["kind"] for e in feed(manager_client, material_id=m.mid("М2"))] == [
        "appeared"
    ]
    assert [r[0] for r in screen_history(manager_client, m.mid("М2"))] == ["2026-10-06"]
    assert len(screen_history(manager_client, m.mid("М1"))) == 5


# BDD-042, REQ-F-016 criterion 2: the scheduled run of 2026-10-05 wrote А-3's price
# for М1; А-3 is relinked to М2 and a manual run follows that day — the one daily
# price of 10-05 belongs to М2: not in М1 history, in М2 history.
def test_relink_and_rerun_same_day_bdd042(world, manager_client):
    m = Market(world, {"Альфа": {"А-3": "М1"}}, start=D(30, 9))
    m.day(D(4), {"Альфа": {"А-3": "1000.00"}})
    m.day(D(5), {"Альфа": {"А-3": "1010.00"}})
    world.material("М2")
    world.link("А-3", "М2")
    m.day(D(5), {"Альфа": {"А-3": "1010.00"}}, hour=10, trigger="manual")
    assert [r[0] for r in history_rows(manager_client, m.mid("М1"))] == ["2026-10-04"]
    assert history_rows(manager_client, m.mid("М2")) == [
        ("2026-10-05", "Альфа", "1010.00", False, False)
    ]
    assert "2026-10-05" not in page_text(history_screen(manager_client, m.mid("М1")))
    assert "2026-10-05" in page_text(history_screen(manager_client, m.mid("М2")))


# REQ-F-016 criterion 3: after linking a previously unlinked item the material has
# no prices of dates before the link.
def test_no_prices_before_link(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00")])
    world.at(2026, 10, 1)
    world.run()
    world.at(2026, 10, 2)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    world.at(2026, 10, 3)
    world.run()
    rows = history_rows(manager_client, world.material_ids["М1"])
    assert [r[0] for r in rows] == ["2026-10-03"]


# --- the choice of the material -----------------------------------------------------------------------


# REQ-F-057 (П-3), REQ-F-040: the choice of the material lists active materials by
# name in alphabetical order.
def test_material_choice_alphabetical(admin_client, manager_client):
    for name in ALPHABET_NAMES:
        create_material(admin_client, name)
    html = screen(manager_client, "/price-history")
    names = [text for _, text in select_options(html, "material_id")]
    assert names == ALPHABET_ORDER


# REQ-F-040, REQ-F-049 criterion 5: a deactivated material is not in the choice
# without "показати неактивні", and is with it; its history opens for both roles.
def test_show_inactive_option(world, admin_client, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(30, 9))
    m.day(D(1), {"Альфа": {"А-1": "1000.00"}})
    create_material(admin_client, "М2")
    world.admin.patch(f"{API}/materials/{m.mid('М1')}", json={"active": False})
    for client in (admin_client, manager_client):
        html = screen(client, "/price-history")
        assert SHOW_INACTIVE in page_text(html)
        assert [t for _, t in select_options(html, "material_id")] == ["М2"]
        value = show_inactive_value(html)
        with_inactive = screen(client, f"/price-history?show_inactive={value}")
        options = select_options(with_inactive, "material_id")
        assert [t for _, t in options] == ["М1", "М2"]
        assert (str(m.mid("М1")), "М1") in options
        rows = screen_history(client, m.mid("М1"))
        assert [r[0] for r in rows] == ["2026-10-01"]


# REQ-NF-030 criterion: the daily price of 5 October 2026 is shown as
# "2026-10-05" on the history screen.
def test_history_date_format(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(30, 9))
    m.day(D(5), {"Альфа": {"А-1": "1000.00"}})
    rows = screen_history(manager_client, m.mid("М1"))
    assert rows[0][0] == "2026-10-05"

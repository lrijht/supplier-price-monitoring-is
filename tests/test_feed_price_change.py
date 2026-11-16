"""T-26: events "зміна ціни", the feed base, the threshold, the event date.

Events and daily prices are read from storage (``spm.storage.events``,
``spm.storage.daily_prices``): the feed and history screens are block B3. The
feed base is internal (REQ-NF-031); tests see it through the events it causes.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from helpers_b2 import item, kyiv, move_to, parse_dt, start_manual, wait_run, wait_until

BASE = "1000.00"

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")


def D(day: int) -> date:
    return date(2026, 10, day)


@pytest.fixture
def a1(world):
    """А-1 linked to М1 with the feed base 1000,00 (event "з'явився" 2026-10-02);
    threshold 1 % (default). Further runs from 2026-10-03."""
    world.linked_with_base(
        "Альфа", "alfa", [item("А-1", BASE), item("А-2", "500.00")], {"А-1": "М1"}
    )
    return world


def priced(
    world, day: int, price: str | None, *, hour: int = 3, trigger: str = "scheduled"
):
    """A run on 2026-10-``day`` with А-1 at ``price`` (None — "ціну уточнюйте")."""
    world.page("Альфа", [item("А-1", price), item("А-2", "500.00")])
    world.at(2026, 10, day, hour, 30)
    return world.run(trigger)


def changes(world, sku: str = "А-1") -> list[tuple]:
    return [
        (e.old_price, e.new_price, Decimal(str(e.change_percent)))
        for e in world.events(sku, "price_change")
    ]


def ev(old: str, new: str, percent: str) -> tuple:
    return (Decimal(old), Decimal(new), Decimal(percent))


# --- REQ-F-044: the threshold ---------------------------------------------------------------


# REQ-F-044: base 1000,00, threshold 1 % — 1009,00 gives no event; 1009,99 gives
# none (0,999 % is compared exactly, not rounded to 1,0 %); 1010,00 gives
# "1000,00 -> 1010,00, +1,0 %".
def test_threshold_compared_exactly(a1):
    priced(a1, 3, "1009.00")
    priced(a1, 4, "1009.99")
    assert changes(a1) == []
    priced(a1, 5, "1010.00")
    assert changes(a1) == [ev(BASE, "1010.00", "1.0")]


# REQ-F-044, BDD-016: 990,00 gives the event with −1,0 %.
def test_drop_by_threshold(a1):
    priced(a1, 3, "990.00")
    assert changes(a1) == [ev(BASE, "990.00", "-1.0")]


# REQ-F-044, Д.11: the change is rounded to 0,1 %, half away from zero —
# 1012,50 is +1,25 % -> +1,3 %; 987,50 is −1,25 % -> −1,3 %.
@pytest.mark.parametrize(("price", "percent"), [("1012.50", "1.3"), ("987.50", "-1.3")])
def test_change_rounded_half_away_from_zero(a1, price, percent):
    priced(a1, 3, price)
    assert changes(a1) == [ev(BASE, price, percent)]


# REQ-F-044, BDD-013: 1005,00 gives no event; the daily price 1005,00 is stored.
def test_small_change_no_event(a1):
    priced(a1, 3, "1005.00")
    assert changes(a1) == []
    assert a1.price_on("А-1", D(3)).price == Decimal("1005.00")


# --- REQ-F-045: the feed base ---------------------------------------------------------------


# REQ-F-045, BDD-014: 1006,00 then 1012,00 give one event "1000,00 -> 1012,00,
# +1,2 %"; the base becomes 1012,00 (1018,00 then gives none, 1023,00 does).
def test_small_changes_accumulate(a1):
    priced(a1, 3, "1006.00")
    assert changes(a1) == []
    priced(a1, 4, "1012.00")
    assert changes(a1) == [ev(BASE, "1012.00", "1.2")]
    priced(a1, 5, "1018.00")
    assert len(changes(a1)) == 1
    priced(a1, 6, "1023.00")
    assert changes(a1)[-1][:2] == (Decimal("1012.00"), Decimal("1023.00"))


# REQ-F-045, BDD-015: 1006,00 then 1000,00 — no event.
def test_opposite_changes_cancel(a1):
    priced(a1, 3, "1006.00")
    priced(a1, 4, BASE)
    assert changes(a1) == []


# REQ-F-045: a day without a price between 1006,00 and 1012,00 changes nothing.
def test_day_without_price_between(a1):
    priced(a1, 3, "1006.00")
    priced(a1, 4, None)
    priced(a1, 5, "1012.00")
    assert changes(a1) == [ev(BASE, "1012.00", "1.2")]


# REQ-F-029, BDD-018: "ціну уточнюйте" — no daily price, no "зміна ціни" or "зник";
# the next run with 1015,00 gives "1000,00 -> 1015,00, +1,5 %".
def test_no_price_keeps_base(a1):
    priced(a1, 3, None)
    assert a1.price_on("А-1", D(3)) is None
    assert [e.kind for e in a1.events("А-1")] == ["appeared"]
    priced(a1, 4, "1015.00")
    assert changes(a1) == [ev(BASE, "1015.00", "1.5")]


# --- REQ-F-028, REQ-F-053: a repeated run of the same date ---------------------------------------


# REQ-F-028, REQ-F-044, BDD-010: scheduled run 2026-10-05 writes 1000,00; the
# manual run that day reads 1020,00 — one daily price 1020,00 and the event
# "1000,00 -> 1020,00, +2,0 %".
def test_same_date_rerun_creates_event(a1):
    priced(a1, 5, BASE)
    priced(a1, 5, "1020.00", hour=10, trigger="manual")
    assert a1.price_on("А-1", D(5)).price == Decimal("1020.00")
    assert changes(a1) == [ev(BASE, "1020.00", "2.0")]


# REQ-F-053, BDD-041: scheduled 2026-10-05 writes 1020,00 and creates +2,0 %;
# the manual run that day writes 1000,00 — the event "1020,00 -> 1000,00,
# −2,0 %" is added, the first one stays; base 1000,00; one daily price 1000,00.
def test_same_date_rerun_keeps_first_event(a1):
    priced(a1, 5, "1020.00")
    priced(a1, 5, BASE, hour=10, trigger="manual")
    assert changes(a1) == [ev(BASE, "1020.00", "2.0"), ev("1020.00", BASE, "-2.0")]
    assert a1.price_on("А-1", D(5)).price == Decimal(BASE)
    priced(a1, 6, "1015.00")
    assert changes(a1)[-1][:2] == (Decimal(BASE), Decimal("1015.00"))


# REQ-F-053: "з'явився" is not created again by a repeated run of the date.
def test_same_date_rerun_no_second_appeared(world):
    world.supplier("Альфа", "alfa", [item("А-1", BASE)])
    world.at(2026, 10, 4)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    world.at(2026, 10, 5)
    world.run()
    world.at(2026, 10, 5, 10, 0)
    world.run("manual")
    assert [e.kind for e in world.events("А-1")] == ["appeared"]


# --- REQ-F-065: a price with the mark "одиниця не збігається" -------------------------------------


# REQ-F-065, BDD-052: base 100,00 (unit «шт»); 1000,00 for «уп» — no event and
# the base stays 100,00: then 100,50 for «шт» gives no event either.
def test_unit_mismatch_price_no_event_no_base(world):
    world.linked_with_base("Вега", "vega", [item("В-2", "100.00", "шт")], {"В-2": "МВ"})
    world.page("Вега", [item("В-2", "1000.00", "уп")])
    world.at(2026, 10, 9)
    world.run()
    assert [e.kind for e in world.events("В-2")] == ["appeared"]
    world.page("Вега", [item("В-2", "100.50", "шт")])
    world.at(2026, 10, 10)
    world.run()
    assert [e.kind for e in world.events("В-2")] == ["appeared"]
    assert world.price_on("В-2", D(10)).unit_mismatch is False


# REQ-F-065, REQ-F-046: after a new link the first price with the mark gives no
# "з'явився"; the first price without it does.
def test_unit_mismatch_price_no_appeared(world):
    world.supplier("Вега", "vega", [item("В-2", "100.00", "шт")])
    world.at(2026, 10, 1)
    world.run()
    world.material("МВ")
    world.link("В-2", "МВ")
    world.page("Вега", [item("В-2", "1000.00", "уп")])
    world.at(2026, 10, 2)
    world.run()
    assert world.events("В-2") == []
    world.page("Вега", [item("В-2", "100.00", "шт")])
    world.at(2026, 10, 3)
    world.run()
    (event,) = world.events("В-2")
    assert (event.kind, event.price) == ("appeared", Decimal("100.00"))


# --- REQ-F-042: which items give events; fields ----------------------------------------------------


# REQ-F-042, REQ-F-049, BDD-045: price changes above the threshold for an item
# of active М1, an item of deactivated М2 and unlinked Б-9 — only the М1 item
# gets an event.
def test_events_only_for_linked_items_of_active_materials(world):
    page = [item("А-1", BASE), item("А-2", BASE), item("Б-9", BASE)]
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1", "А-2": "М2"})
    resp = world.admin.patch(
        f"/api/v1/materials/{world.material_ids['М2']}", json={"active": False}
    )
    assert resp.status_code == 200
    world.page("Альфа", [item(s, "1100.00") for s in ("А-1", "А-2", "Б-9")])
    world.at(2026, 10, 3)
    world.run()
    assert len(world.events("А-1", "price_change")) == 1
    assert world.events("А-2", "price_change") == []
    assert world.events("Б-9") == []


# REQ-F-042, Д.6: each event has its kind's fields — "зміна ціни": old, new and
# change, no price; "з'явився": price only; both with the material and the
# supplier of the item.
def test_event_fields_by_kind(a1):
    priced(a1, 3, "1100.00")
    appeared, change = a1.events("А-1")
    assert (appeared.kind, appeared.price, appeared.old_price, appeared.new_price) == (
        "appeared",
        Decimal(BASE),
        None,
        None,
    )
    assert appeared.change_percent is None
    assert (change.kind, change.price) == ("price_change", None)
    for event in (appeared, change):
        assert event.material_id == a1.material_ids["М1"]
        assert event.supplier_id == a1.supplier_ids["Альфа"]
    assert (appeared.event_date, change.event_date) == (D(2), D(3))


# --- REQ-F-043, BDD-017: a new threshold from the next run --------------------------------------------


# REQ-F-043, BDD-017: threshold 1 %, the event +1,5 % from yesterday's run; the
# threshold becomes 2 % — the event stays as it was; the next run with +1,5 %
# for another item creates no event.
def test_new_threshold_from_next_run(world):
    page = [item("А-1", BASE), item("А-2", BASE)]
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1", "А-2": "М2"})
    world.page("Альфа", [item("А-1", "1015.00"), item("А-2", BASE)])
    world.at(2026, 10, 3)
    world.run()
    before = world.events("А-1", "price_change")
    assert changes(world) == [ev(BASE, "1015.00", "1.5")]
    world.settings(notification_threshold=2)
    world.page("Альфа", [item("А-1", "1015.00"), item("А-2", "1015.00")])
    world.at(2026, 10, 4)
    world.run()
    assert world.events("А-2", "price_change") == []
    assert world.events("А-1", "price_change") == before


# --- REQ-F-042, BDD-064: the date of an event -----------------------------------------------------------


# REQ-F-042, BDD-064: the run starts 2026-10-05 at 23:59 and after midnight
# (00:01) creates "зміна ціни" for А-1 and "зник" for А-2 — both events have the
# date 2026-10-05 and the actual creation time 2026-10-06 00:01.
def test_event_date_is_run_date(world):
    page = [item("А-1", BASE), item("А-2", BASE)] + [
        item(f"А-{n}") for n in range(3, 9)
    ]
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1", "А-2": "М2"})
    world.page("Альфа", [i for i in page if i["sku"] != "А-2"])
    world.at(2026, 10, 4)
    world.run()
    world.page("Альфа", [item("А-1", "1100.00")] + [i for i in page[2:]])
    world.at(2026, 10, 5, 23, 59)
    world.sim.hold("alfa")
    run_id = start_manual(world.admin)["id"]
    wait_until(lambda: world.sim.requests("alfa") == 4, what="request to Альфа")
    move_to(world.clock, kyiv(2026, 10, 6, 0, 1))
    world.sim.release()
    run = wait_run(world.admin, run_id)
    assert run["started_at"] == "2026-10-05T23:59:00+03:00"
    assert parse_dt(run["finished_at"]) >= kyiv(2026, 10, 6, 0, 1)
    (change,) = world.events("А-1", "price_change")
    (gone,) = world.events("А-2", "disappeared")
    for event in (change, gone):
        assert event.event_date == D(5)
        assert event.created_at == kyiv(2026, 10, 6, 0, 1)
        assert event.created_at.utcoffset() == timedelta(hours=3)
    assert world.price_on("А-1", D(5)).price == Decimal("1100.00")

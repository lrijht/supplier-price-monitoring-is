"""T-27: events "з'явився" and "зник".

Supplier Альфа has 10 items (volume base 10): leaving one item out keeps the
supplier "успіх" (9 of 10), a 7-item page is "частково" (70 %). А-1 (and,
where needed, А-2) is linked with a feed base by two runs on 2026-10-01 and
2026-10-02 (``World.linked_with_base``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from helpers import API
from helpers_b2 import item, items, row

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

PAGE = items("А", 10, "1000.00")


def D(day: int) -> date:
    return date(2026, 10, day)


def without(*skus: str) -> list[dict]:
    return [i for i in PAGE if i["sku"] not in skus]


def partial_with(*skus: str) -> list[dict]:
    """A 7-item page ("частково") that has the given items."""
    chosen = [i for i in PAGE if i["sku"] in skus]
    rest = [i for i in PAGE if i["sku"] not in skus and i["sku"] not in ("А-1", "А-2")]
    return chosen + rest[: 7 - len(chosen)]


@pytest.fixture
def a1(world):
    world.linked_with_base("Альфа", "alfa", PAGE, {"А-1": "М1", "А-2": "М2"})
    return world


def day(
    world,
    d: int,
    page: list[dict] | None,
    *,
    hour: int = 3,
    trigger="scheduled",
    status="success",
):
    """A run on 2026-10-``d``; ``page`` None — the page is unavailable."""
    if page is None:
        world.mode("Альфа", "unavailable")
    else:
        world.page("Альфа", page)
    world.at(2026, 10, d, hour, 30)
    run = world.run(trigger)
    assert row(run, "Альфа")["status"] == status
    return run


def gone(world, sku: str = "А-1") -> list[date]:
    return [e.event_date for e in world.events(sku, "disappeared")]


def appeared(world, sku: str = "А-1") -> list[tuple]:
    return [
        (e.event_date, e.price, e.material_id) for e in world.events(sku, "appeared")
    ]


# --- REQ-F-047: "зник" -----------------------------------------------------------------------


# REQ-F-047, BDD-020: А-1 was on the page 2026-10-04; absent in the "успіх" run of
# 2026-10-05 — no event; absent again 2026-10-06 — "зник" dated 2026-10-06.
def test_disappeared_after_two_dates(a1):
    day(a1, 4, PAGE)
    day(a1, 5, without("А-1"))
    assert gone(a1) == []
    day(a1, 6, without("А-1"))
    assert gone(a1) == [D(6)]
    (event,) = a1.events("А-1", "disappeared")
    assert (event.price, event.old_price, event.new_price, event.change_percent) == (
        None,
    ) * 4
    assert event.material_id == a1.material_ids["М1"]


# REQ-F-047, BDD-022: absent 2026-10-05 ("успіх"), Альфа "помилка" 2026-10-06,
# absent 2026-10-07 ("успіх") — "зник" 2026-10-07; the same with "частково" on
# 2026-10-06 (А-1 absent from that run too).
@pytest.mark.parametrize("middle", ["error", "partial"])
def test_error_or_partial_run_does_not_break_sequence(a1, middle):
    day(a1, 5, without("А-1"))
    if middle == "error":
        day(a1, 6, None, status="error")
    else:
        day(a1, 6, partial_with("А-2"), status="partial")
    assert gone(a1) == []
    day(a1, 7, without("А-1"))
    assert gone(a1) == [D(7)]


# REQ-F-030, BDD-005: base 100; the item absent 2026-10-05 ("успіх", 99 items);
# the reduced page of 79 items without it on 2026-10-06 is "частково" — no
# "зник", and the 79 daily prices are written.
def test_no_disappeared_in_partial_run(world):
    page = items("А", 100)
    world.linked_with_base("Альфа", "alfa", page, {"А-17": "М17", "А-1": "М1"})
    rest = [i for i in page if i["sku"] != "А-17"]
    world.page("Альфа", rest)
    world.at(2026, 10, 5)
    world.run()
    world.page("Альфа", rest, mode="reduced", keep_items=79)
    world.at(2026, 10, 6)
    assert row(world.run(), "Альфа")["status"] == "partial"
    assert gone(world, "А-17") == []
    assert world.price_on("А-1", D(6)) is not None


# REQ-F-047, BDD-033: absent in the scheduled run and in the manual run of
# 2026-10-05 (both "успіх") — no event; absent 2026-10-06 — "зник".
def test_same_date_counts_once(a1):
    day(a1, 5, without("А-1"))
    day(a1, 5, without("А-1"), hour=10, trigger="manual")
    assert gone(a1) == []
    day(a1, 6, without("А-1"))
    assert gone(a1) == [D(6)]


# REQ-F-047: absent in the scheduled run of 2026-10-05 but present in the manual
# run that day (both "успіх"); absent 2026-10-06 — no "зник".
def test_last_success_run_of_date_present(a1):
    day(a1, 5, without("А-1"))
    day(a1, 5, PAGE, hour=10, trigger="manual")
    day(a1, 6, without("А-1"))
    assert gone(a1) == []


# REQ-F-047, BDD-067: present in the scheduled run of 2026-10-05, absent in the
# manual run that day (both "успіх"); absent 2026-10-06 — "зник": the manual
# run decided the state of 2026-10-05.
def test_last_success_run_of_date_absent(a1):
    day(a1, 5, PAGE)
    day(a1, 5, without("А-1"), hour=10, trigger="manual")
    assert gone(a1) == []
    day(a1, 6, without("А-1"))
    assert gone(a1) == [D(6)]


# REQ-F-047, BDD-067: А-2 absent 2026-10-12 ("успіх"); on 2026-10-13 present in
# the scheduled run with "частково" but absent in the manual "успіх" run of the
# day — the counter is not reset, and "зник" comes after the manual run.
def test_partial_presence_does_not_reset_when_date_has_success(a1):
    day(a1, 12, without("А-2"))
    day(a1, 13, partial_with("А-1", "А-2"), status="partial")
    assert gone(a1, "А-2") == []
    day(a1, 13, without("А-2"), hour=10, trigger="manual")
    assert gone(a1, "А-2") == [D(13)]


# REQ-F-047, REQ-F-030, BDD-057: absent 2026-10-05 ("успіх"); present 2026-10-06
# in a "частково" run; absent 2026-10-07 ("успіх") — no "зник": the presence
# reset the counter.
def test_partial_presence_resets_counter(a1):
    day(a1, 5, without("А-1"))
    day(a1, 6, partial_with("А-1"), status="partial")
    day(a1, 7, without("А-1"))
    assert gone(a1) == []


# REQ-F-046, BDD-057: А-2 has "зник"; a "частково" run finds it at 700,00 —
# "з'явився" for А-2 with 700,00.
def test_appeared_in_partial_run(a1):
    day(a1, 5, without("А-2"))
    day(a1, 6, without("А-2"))
    assert gone(a1, "А-2") == [D(6)]
    page = partial_with("А-2")
    page = [item("А-2", "700.00") if i["sku"] == "А-2" else i for i in page]
    day(a1, 7, page, status="partial")
    assert appeared(a1, "А-2")[-1] == (D(7), Decimal("700.00"), a1.material_ids["М2"])


# REQ-F-064, BDD-049: "зник" on 2026-10-06; absent 2026-10-07 and 2026-10-08 —
# no new "зник"; 2026-10-09 present with "ціну уточнюйте" — no events, counter
# reset; 2026-10-10 at 1050,00 — "з'явився, 1050,00 грн".
def test_disappeared_once_and_return_without_price(a1):
    day(a1, 5, without("А-1"))
    day(a1, 6, without("А-1"))
    day(a1, 7, without("А-1"))
    day(a1, 8, without("А-1"))
    assert gone(a1) == [D(6)]
    day(a1, 9, [item("А-1", None)] + without("А-1"))
    assert len(a1.events("А-1")) == 2
    day(a1, 10, [item("А-1", "1050.00")] + without("А-1"))
    assert appeared(a1)[-1][:2] == (D(10), Decimal("1050.00"))
    assert a1.events("А-1", "price_change") == []


# REQ-F-064: the return without a price resets the counter — absent again on
# 2026-10-10 after "ціну уточнюйте" on 2026-10-09: no event yet.
def test_return_without_price_resets_counter(a1):
    for d in (5, 6):
        day(a1, d, without("А-1"))
    day(a1, 9, [item("А-1", None)] + without("А-1"))
    day(a1, 10, without("А-1"))
    assert gone(a1) == [D(6)]


# REQ-F-046, BDD-021: "зник" with base 1000,00; А-1 is back at 1100,00 —
# "з'явився" 1100,00, no "зміна ціни"; the base is 1100,00 (1105,00 then gives no
# event, 1115,00 gives one from 1100,00).
def test_return_after_disappeared(a1):
    day(a1, 5, without("А-1"))
    day(a1, 6, without("А-1"))
    day(a1, 7, [item("А-1", "1100.00")] + without("А-1"))
    assert appeared(a1)[-1][:2] == (D(7), Decimal("1100.00"))
    assert a1.events("А-1", "price_change") == []
    day(a1, 8, [item("А-1", "1105.00")] + without("А-1"))
    assert a1.events("А-1", "price_change") == []
    day(a1, 9, [item("А-1", "1115.00")] + without("А-1"))
    (change,) = a1.events("А-1", "price_change")
    assert change.old_price == Decimal("1100.00")


# REQ-F-047, BDD-062: unlinked Б-9 last seen 2026-10-01 is linked to М1 on
# 2026-10-05; absent in the "успіх" runs of 2026-10-06 and 2026-10-07 — no "зник":
# the item has no feed base.
def test_no_disappeared_without_feed_base(world):
    world.supplier("Бета", "beta", [item("Б-1"), item("Б-2"), item("Б-9")])
    world.at(2026, 10, 1)
    world.run()
    world.page("Бета", [item("Б-1"), item("Б-2"), item("Б-3")])
    world.at(2026, 10, 2)
    world.run()
    world.material("М1")
    world.at(2026, 10, 5, 12, 0)
    world.link("Б-9", "М1")
    for d in (6, 7):
        world.at(2026, 10, d)
        assert row(world.run(), "Бета")["status"] == "success"
    assert world.events("Б-9") == []


# REQ-F-031, REQ-F-047, BDD-007: the last run of Альфа is "частково" with 70 of
# base 100 and А-17 not among them; the new volume is accepted; the runs of
# 2026-10-06 and 2026-10-07 with the same 70 items are "успіх", and after
# 2026-10-07 "зник" is created for А-17.
def test_disappeared_after_accepting_volume(world):
    page = items("А", 100)
    world.linked_with_base("Альфа", "alfa", page, {"А-17": "М17"})
    seventy = [i for i in page if i["sku"] != "А-17"][:70]
    world.page("Альфа", seventy)
    world.at(2026, 10, 5)
    run05 = world.run()
    assert row(run05, "Альфа")["status"] == "partial"
    resp = world.admin.post(
        f"{API}/volume-acceptances",
        json={"run_id": run05["id"], "supplier_id": world.supplier_ids["Альфа"]},
    )
    assert resp.status_code == 201, resp.text
    world.at(2026, 10, 6)
    assert row(world.run(), "Альфа")["status"] == "success"
    assert gone(world, "А-17") == []
    world.at(2026, 10, 7)
    assert row(world.run(), "Альфа")["status"] == "success"
    assert gone(world, "А-17") == [D(7)]


# REQ-F-047: after accepting a new volume the count starts from the first run
# after it — absent 2026-10-05 ("успіх"), "частково" 2026-10-06 (accepted),
# absent 2026-10-07: no event; absent 2026-10-08: "зник".
def test_accepting_volume_restarts_count(a1):
    day(a1, 5, without("А-1"))
    run06 = day(a1, 6, partial_with("А-2"), status="partial")
    resp = a1.admin.post(
        f"{API}/volume-acceptances",
        json={"run_id": run06["id"], "supplier_id": a1.supplier_ids["Альфа"]},
    )
    assert resp.status_code == 201, resp.text
    day(a1, 7, partial_with("А-2"))
    assert gone(a1) == []
    day(a1, 8, partial_with("А-2"))
    assert gone(a1) == [D(8)]


# --- REQ-F-046: "з'явився" -----------------------------------------------------------------------


# REQ-F-046, REQ-F-016, BDD-019: Б-5 unlinked, seen on 2026-10-05 at 1100,00; linked
# that day to "ЛДСП Білий 18 мм"; the manual run of the day writes 1100,00 —
# "з'явився" for the material, supplier Бета, 1100,00; the base is 1100,00; the
# daily price of 2026-10-05 exists and none before it.
def test_appeared_after_link(world):
    world.supplier("Бета", "beta", [item("Б-5", "1100.00")])
    world.at(2026, 10, 4)
    world.run()
    world.at(2026, 10, 5)
    world.run()
    world.material("ЛДСП Білий 18 мм")
    world.link("Б-5", "ЛДСП Білий 18 мм")
    world.at(2026, 10, 5, 10, 0)
    world.run("manual")
    (event,) = world.events("Б-5")
    assert (event.kind, event.event_date, event.price) == (
        "appeared",
        D(5),
        Decimal("1100.00"),
    )
    assert event.material_id == world.material_ids["ЛДСП Білий 18 мм"]
    assert event.supplier_id == world.supplier_ids["Бета"]
    assert [p.price_date for p in world.prices("Б-5")] == [D(5)]
    world.page("Бета", [item("Б-5", "1105.00")])
    world.at(2026, 10, 6)
    world.run()
    assert len(world.events("Б-5")) == 1


# REQ-F-046, BDD-056: А-1 on М1 with base 1000,00 is relinked to М2 and back to
# М1; the next run at 1005,00 creates "з'явився" for М1 with 1005,00 (no "зміна
# ціни"); the base is 1005,00.
def test_appeared_after_relink_back(a1):
    a1.material("М3")
    a1.link("А-1", "М3")
    a1.link("А-1", "М1")
    day(a1, 3, [item("А-1", "1005.00")] + without("А-1"))
    assert appeared(a1)[-1] == (D(3), Decimal("1005.00"), a1.material_ids["М1"])
    assert a1.events("А-1", "price_change") == []
    day(a1, 4, [item("А-1", "1012.00")] + without("А-1"))
    assert a1.events("А-1", "price_change") == []


# REQ-F-046, BDD-056: the same after removing the link and linking to М1 again.
def test_appeared_after_unlink_and_link(a1):
    a1.unlink("А-1")
    a1.link("А-1", "М1")
    day(a1, 3, [item("А-1", "1005.00")] + without("А-1"))
    assert appeared(a1)[-1] == (D(3), Decimal("1005.00"), a1.material_ids["М1"])


# REQ-F-046, BDD-026: after relinking from М1 to М2 the first run creates
# "з'явився" for М2.
def test_appeared_for_new_material_after_relink(a1):
    day(a1, 5, PAGE)
    a1.material("М3")
    a1.link("А-1", "М3")
    day(a1, 6, PAGE)
    assert appeared(a1)[-1] == (D(6), Decimal("1000.00"), a1.material_ids["М3"])


# REQ-F-047, REQ-F-064: a new link resets the "зник" mark and the count — after
# "зник" and a relink, absence on two more dates gives no new "зник" (no base
# until "з'явився").
def test_relink_resets_disappeared(a1):
    day(a1, 5, without("А-1"))
    day(a1, 6, without("А-1"))
    a1.material("М3")
    a1.link("А-1", "М3")
    day(a1, 7, without("А-1"))
    day(a1, 8, without("А-1"))
    assert gone(a1) == [D(6)]

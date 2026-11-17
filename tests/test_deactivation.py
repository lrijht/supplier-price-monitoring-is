"""T-39: deactivation and activation of a supplier and of a material.

REQ-F-011, REQ-F-049, REQ-F-051, REQ-F-056 (with REQ-F-052, REQ-F-047), REQ-F-010;
BDD-034, BDD-038, BDD-040, BDD-044, BDD-053; UC-06 (2а, 2б), UC-07 (2б, 2в).

What B2 did not cover: after activating a supplier or changing its catalogue
address or parser the volume base, the absence counters and the "зник" flag are
reset and the feed base is the last price without the mark (REQ-F-056, BDD-053);
the feed base after activating a material (REQ-F-051, BDD-040). The feed base is
internal (REQ-NF-031): tests see it through the events it causes. Comparison
checks rely on the T-38 tests (test_comparison.py).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from helpers import API, data_table, page_text
from helpers_b2 import item, items, row
from helpers_b3 import (
    MATERIAL_DEACTIVATED,
    SUPPLIER_INACTIVE,
    D,
    Market,
    comparison,
    comparison_list,
    comparison_rows,
    feed,
    history_rows,
    row_text,
    screen,
    select_options,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

RESETS = ["reactivation", "catalog_url", "parser"]


def set_material_active(world, name: str, active: bool) -> None:
    resp = world.admin.patch(
        f"{API}/materials/{world.material_ids[name]}", json={"active": active}
    )
    assert resp.status_code == 200, resp.text


def reset_supplier(world, name: str, how: str) -> None:
    """The actions of REQ-F-056: activation after deactivation, a new catalogue
    address (the same page served at another address), a new parser (the page
    switched to the cards layout and the parser to ``cards_layout``)."""
    sid = world.supplier_ids[name]
    slug = world.slugs[name]
    current = world.sim.suppliers[slug]
    if how == "reactivation":
        world.set_active(name, False)
        world.set_active(name, True)
        return
    if how == "catalog_url":
        new_slug = f"{slug}-new"
        world.sim.put(
            new_slug, current["items"], name=current["name"], layout=current["layout"]
        )
        world.slugs[name] = new_slug
        body = {"catalog_url": world.sim.url(new_slug)}
    else:
        world.sim.put(slug, current["items"], name=current["name"], layout="cards")
        body = {"parser": "cards_layout"}
    resp = world.admin.patch(f"{API}/suppliers/{sid}", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["active"] is True


def changes(world, sku: str = "А-1") -> list[tuple]:
    return [
        (e.old_price, e.new_price, Decimal(str(e.change_percent)), e.event_date)
        for e in world.events(sku, "price_change")
    ]


def gone(world, sku: str = "А-1") -> list[date]:
    return [e.event_date for e in world.events(sku, "disappeared")]


def run_on(world, supplier: str, day: date, page: list[dict], status: str = "success"):
    world.page(supplier, page)
    world.at(day.year, day.month, day.day)
    run = world.run()
    assert row(run, supplier)["status"] == status
    return run


# --- REQ-F-011, BDD-044: a deactivated supplier ------------------------------------------------------


@pytest.fixture
def vega_off(world):
    """Альфа and Вега priced for М1 on 2026-10-01…10-05 (Вега cheaper, a different
    price each day, each change below the threshold); Вега has one event ("з'явився")
    before deactivation; Вега deactivated on
    2026-10-05; the run of 2026-10-06."""
    m = Market(world, {"Альфа": {"А-1": "М1"}, "Вега": {"В-1": "М1"}}, start=D(30, 9))
    for day in range(1, 6):
        m.day(D(day), {"Альфа": {"А-1": "1000.00"}, "Вега": {"В-1": f"{900 + day}.00"}})
    world.set_active("Вега", False)
    m.requests_before = world.sim.requests("vega")
    m.run6 = m.day(D(6), {"Альфа": {"А-1": "1000.00"}, "Вега": {"В-1": "500.00"}})
    return m


# BDD-044, REQ-F-011 criterion 1: the run after deactivation does not request
# Вега's catalogue, and the run has no row of Вега.
def test_deactivated_supplier_not_polled_bdd044(vega_off):
    assert vega_off.world.sim.requests("vega") == vega_off.requests_before
    names = [r["supplier"]["name"] for r in vega_off.run6["supplier_run_statuses"]]
    assert names == ["Альфа"]


# BDD-044, REQ-F-011: the comparison of the material has no row of Вега and its
# (lower) price does not affect the cheapest; the list shows Альфа.
def test_deactivated_supplier_not_in_comparison_bdd044(vega_off, manager_client):
    rows = comparison_rows(manager_client, vega_off.mid("М1"))
    assert set(rows) == {"Альфа"}
    assert rows["Альфа"]["cheapest"] is True
    assert rows["Альфа"]["difference_from_cheapest"] == {
        "percent": 0.0,
        "amount": "0.00",
    }
    (listed,) = [
        r for r in comparison_list(manager_client) if r["material"]["name"] == "М1"
    ]
    assert listed["cheapest_supplier"]["name"] == "Альфа"
    html = screen(manager_client, f"/material-comparisons/{vega_off.mid('М1')}")
    assert "Вега" not in page_text(html)


# BDD-044, REQ-F-011, REQ-F-010: Вега's prices of 2026-10-01…10-05 stay on the history
# screen, unchanged by the deactivation.
def test_deactivated_supplier_prices_in_history_bdd044(vega_off, manager_client):
    vega = [
        r for r in history_rows(manager_client, vega_off.mid("М1")) if r[1] == "Вега"
    ]
    assert [(r[0], r[2]) for r in vega] == [
        (f"2026-10-0{d}", f"{900 + d}.00") for d in range(5, 0, -1)
    ]
    html = screen(
        manager_client, f"/price-history?material_id={vega_off.mid('М1')}&period=all"
    )
    _, rows = data_table(html)
    assert len([r for r in rows if r[1] == "Вега"]) == 5


# REQ-F-011 criterion 2: Вега's event created before deactivation stays in the
# feed, and Вега stays in the feed's supplier filter (screen and API list for the
# manager).
def test_deactivated_supplier_stays_in_feed(vega_off, manager_client):
    vid = vega_off.sid("Вега")
    assert [e["kind"] for e in feed(manager_client, supplier_id=vid)] == ["appeared"]
    html = screen(manager_client, "/events")
    assert [t for v, t in select_options(html, "supplier_id") if v == str(vid)] == [
        t for v, t in select_options(html, "supplier_id") if "Вега" in t
    ]
    assert any(v == str(vid) for v, _ in select_options(html, "supplier_id"))
    rows = data_table(screen(manager_client, f"/events?supplier_id={vid}"))[1]
    assert len(rows) == 1 and "Вега" in row_text(rows[0])
    listed = manager_client.get(f"{API}/suppliers").json()["items"]
    assert {"id": vid, "name": "Вега", "active": False} in listed


# REQ-F-011 criterion 2 (moved from B1.2): an unlinked item of a deactivated
# supplier is in the list of unlinked items with the mark "постачальник
# неактивний"; an item of an active supplier has no mark.
def test_unlinked_item_marked_supplier_inactive(world, admin_client):
    world.supplier("Альфа", "alfa", [item("А-9")])
    world.supplier("Вега", "vega", [item("В-9")])
    world.at(2026, 10, 1)
    world.run()
    world.set_active("Вега", False)
    _, rows = data_table(screen(admin_client, "/unlinked-items"))
    by_sku = {r[1]: row_text(r) for r in rows}
    assert SUPPLIER_INACTIVE in by_sku["В-9"]
    assert SUPPLIER_INACTIVE not in by_sku["А-9"]


# --- REQ-F-049, BDD-034: a deactivated material ---------------------------------------------------------


@pytest.fixture
def m1_off(world):
    """А-1 linked to М1 with the feed base 1000,00 ("з'явився" 2026-10-02); М1
    deactivated; the run of 2026-10-03 writes 1100,00."""
    world.linked_with_base(
        "Альфа", "alfa", [item("А-1", "1000.00"), item("А-2", "500.00")], {"А-1": "М1"}
    )
    set_material_active(world, "М1", False)
    world.page("Альфа", [item("А-1", "1100.00"), item("А-2", "500.00")])
    world.at(2026, 10, 3)
    world.run()
    return world


# BDD-034, REQ-F-049 criterion: М1 is not in the comparison list; its comparison
# shows "матеріал деактивовано" instead of the table (API: active false, empty
# items).
def test_deactivated_material_comparison_bdd034(m1_off, manager_client):
    mid = m1_off.material_ids["М1"]
    assert "М1" not in [r["material"]["name"] for r in comparison_list(manager_client)]
    assert comparison(manager_client, mid) == {
        "material": {"id": mid, "name": "М1", "active": False},
        "items": [],
    }
    html = screen(manager_client, f"/material-comparisons/{mid}")
    assert MATERIAL_DEACTIVATED in page_text(html)
    assert "<thead" not in html.lower()
    assert "М1" not in page_text(screen(manager_client, "/material-comparisons"))


# BDD-034, REQ-F-049, REQ-F-010: no "зміна ціни" for М1 although +10 %; the link
# А-1 → М1 is kept; the price 1100,00 is on М1's history for both roles; the event
# created before deactivation stays in the feed.
def test_deactivated_material_prices_no_events_bdd034(
    m1_off, admin_client, manager_client
):
    mid = m1_off.material_ids["М1"]
    assert m1_off.events("А-1", "price_change") == []
    assert [e["kind"] for e in feed(manager_client, material_id=mid)] == ["appeared"]
    links = admin_client.get(f"{API}/materials/{mid}/links").json()["items"]
    assert [entry["supplier_item"]["sku"] for entry in links] == ["А-1"]
    for client in (admin_client, manager_client):
        assert history_rows(client, mid)[0] == (
            "2026-10-03",
            "Альфа",
            "1100.00",
            False,
            False,
        )


# --- REQ-F-051, BDD-038, BDD-040: activation of a material -------------------------------------------------


# BDD-038, REQ-F-051 criterion: base 1000,00; while М1 is deactivated the runs write
# 1050,00 and 1100,00; after activation there are no events of the deactivation
# period, the history has 1050,00 and 1100,00, the base is 1100,00 — the same price
# makes no event, 1111,00 makes "1100,00 → 1111,00, +1,0 %".
def test_material_activation_feed_base_bdd038(world, manager_client):
    world.linked_with_base("Альфа", "alfa", [item("А-1", "1000.00")], {"А-1": "М1"})
    set_material_active(world, "М1", False)
    for day, price in ((3, "1050.00"), (4, "1100.00")):
        run_on(world, "Альфа", D(day), [item("А-1", price)])
    set_material_active(world, "М1", True)
    mid = world.material_ids["М1"]
    assert [e["kind"] for e in feed(manager_client, material_id=mid)] == ["appeared"]
    prices = [r[2] for r in history_rows(manager_client, mid)]
    assert prices[:2] == ["1100.00", "1050.00"]
    run_on(world, "Альфа", D(5), [item("А-1", "1100.00")])
    assert changes(world) == []
    run_on(world, "Альфа", D(6), [item("А-1", "1111.00")])
    assert changes(world) == [
        (Decimal("1100.00"), Decimal("1111.00"), Decimal("1.0"), D(6))
    ]
    (event,) = feed(manager_client, material_id=mid, kind="price_change")
    assert (event["old_price"], event["new_price"]) == ("1100.00", "1111.00")


# REQ-F-051 criterion 5: all daily prices of А-1 for М1 are "одиниця не
# збігається" — after activation there is no base, and the first price without
# the mark (the same sum) creates "з'явився".
def test_material_activation_no_base_from_marked_prices(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00")])
    world.at(2026, 10, 1)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    set_material_active(world, "М1", False)
    run_on(world, "Альфа", D(2), [item("А-1", "1000.00", "уп")])
    set_material_active(world, "М1", True)
    run_on(world, "Альфа", D(3), [item("А-1", "1000.00")])
    assert [(e.kind, e.price, e.event_date) for e in world.events("А-1")] == [
        ("appeared", Decimal("1000.00"), D(3))
    ]
    mid = world.material_ids["М1"]
    assert [r[:4] for r in history_rows(manager_client, mid)] == [
        ("2026-10-03", "Альфа", "1000.00", False),
        ("2026-10-02", "Альфа", "1000.00", True),
    ]


# BDD-040, REQ-F-051 criterion 4, REQ-F-047: М1 deactivated, А-1 absent on 10-04 and
# 10-05 (Альфа "успіх"); М1 activated on 10-05; absent on 10-06 — no "зник";
# absent on 10-07 — "зник" dated 2026-10-07.
def test_material_activation_resets_absences_bdd040(world, manager_client):
    page = items("А", 10, "1000.00")
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1"})
    without = page[1:]
    set_material_active(world, "М1", False)
    run_on(world, "Альфа", D(4), without)
    run_on(world, "Альфа", D(5), without)
    set_material_active(world, "М1", True)
    run_on(world, "Альфа", D(6), without)
    assert gone(world) == []
    run_on(world, "Альфа", D(7), without)
    assert gone(world) == [D(7)]
    kinds = [
        e["kind"] for e in feed(manager_client, material_id=world.material_ids["М1"])
    ]
    assert kinds == ["disappeared", "appeared"]


# --- REQ-F-056, BDD-053: activation of a supplier, new address or parser -----------------------------------


# BDD-053, REQ-F-056 criterion: Альфа had the volume base 100; А-1 had the feed base
# 1000,00 and the last price 1008,00. After activation (or a new address, or a new
# parser) the first run with 60 items is "успіх" (base 60 — 47 items is then
# "частково"); 1020,00 makes "1008,00 → 1020,00, +1,2 %".
@pytest.mark.parametrize("how", RESETS)
def test_supplier_reset_volume_and_feed_base_bdd053(world, how):
    page = [item("А-1", "1000.00")] + items("А", 100, "500.00")[1:]
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1"})
    run_on(world, "Альфа", D(3), [item("А-1", "1008.00")] + page[1:])
    assert changes(world) == []
    reset_supplier(world, "Альфа", how)
    run_on(world, "Альфа", D(5, 11), [item("А-1", "1008.00")] + page[1:60])
    assert changes(world) == []
    run_on(world, "Альфа", D(6, 11), [item("А-1", "1020.00")] + page[1:60])
    assert changes(world) == [
        (Decimal("1008.00"), Decimal("1020.00"), Decimal("1.2"), D(6, 11))
    ]
    run_on(world, "Альфа", D(7, 11), page[:47], status="partial")


# REQ-F-056 criterion 3, REQ-F-047: А-1 was absent in the last run before the
# action (one absence); after it, "зник" comes only after two runs with different
# dates — none after the first, "зник" after the second.
@pytest.mark.parametrize("how", RESETS)
def test_supplier_reset_absence_counter(world, how):
    page = items("А", 10, "1000.00")
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1"})
    run_on(world, "Альфа", D(3), page[1:])
    reset_supplier(world, "Альфа", how)
    run_on(world, "Альфа", D(5), page[1:])
    assert gone(world) == []
    run_on(world, "Альфа", D(6), page[1:])
    assert gone(world) == [D(6)]


# REQ-F-056, REQ-F-064: the "зник" flag is reset — А-1 disappeared on 2026-10-04;
# after the action, absent on two more dates, it gets "зник" again.
@pytest.mark.parametrize("how", RESETS)
def test_supplier_reset_disappeared_flag(world, how):
    page = items("А", 10, "1000.00")
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1"})
    run_on(world, "Альфа", D(3), page[1:])
    run_on(world, "Альфа", D(4), page[1:])
    assert gone(world) == [D(4)]
    reset_supplier(world, "Альфа", how)
    run_on(world, "Альфа", D(5), page[1:])
    run_on(world, "Альфа", D(6), page[1:])
    assert gone(world) == [D(4), D(6)]


# REQ-F-056 (feed base without the mark): the last price of А-1 is "одиниця не
# збігається" 1500,00; after activation the base is 1000,00 (the last price without
# the mark) — 1012,00 "шт" makes "1000,00 → 1012,00, +1,2 %".
def test_supplier_reset_feed_base_ignores_marked_price(world):
    world.linked_with_base("Альфа", "alfa", [item("А-1", "1000.00")], {"А-1": "М1"})
    run_on(world, "Альфа", D(3), [item("А-1", "1500.00", "уп")])
    reset_supplier(world, "Альфа", "reactivation")
    run_on(world, "Альфа", D(5), [item("А-1", "1012.00")])
    assert changes(world) == [
        (Decimal("1000.00"), Decimal("1012.00"), Decimal("1.2"), D(5))
    ]

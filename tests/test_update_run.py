"""T-19: an update run — fetching and parsing pages, daily prices, errors.

Runs are started from code (``app.state.updates.run``), without the scheduler;
T-20, T-21, T-26 and T-27 use the same call. Pages come from the simulator on
a loopback address (REQ-NF-013).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal

import pytest
from helpers import API
from helpers_b2 import REASON_TEXT, d, item, items, row

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

D05, D06 = date(2026, 10, 5), date(2026, 10, 6)


def three(world, pages=None) -> None:
    """Suppliers Альфа, Бета, Вега, one per simulator layout (REQ-NF-026)."""
    pages = pages or {}
    world.supplier(
        "Альфа", "alfa", pages.get("alfa", [item("А-1", "1250.50"), item("А-2")])
    )
    world.supplier(
        "Бета",
        "beta",
        pages.get("beta", [item("Б-1", "18.40", "м.п."), item("Б-2", None)]),
        layout="cards",
        parser="cards_layout",
    )
    world.supplier(
        "Вега",
        "vega",
        pages.get("vega", [item("В-1", "64.20"), item("В-2"), item("В-3")]),
        layout="list",
        parser="list_layout",
    )


# --- REQ-F-025, REQ-NF-004: fetching and parsing --------------------------------------


# REQ-F-025: after a run every active supplier got exactly one request to its
# catalogue address and its page was parsed by its own parser — Альфа (table),
# Бета (cards) and Вега (list) succeed with as many items as on the page
# (2, 2, 3; the item "ціну уточнюйте" is parsed too). BDD-001.
def test_each_active_supplier_fetched_once_and_parsed(world):
    three(world)
    world.at(2026, 10, 5)
    run = world.run()
    for slug in ("alfa", "beta", "vega"):
        assert world.sim.requests(slug) == 1
    counts = {
        r["supplier"]["name"]: r["parsed_items_count"]
        for r in run["supplier_run_statuses"]
    }
    assert counts == {"Альфа": 2, "Бета": 2, "Вега": 3}
    assert {r["status"] for r in run["supplier_run_statuses"]} == {"success"}
    assert run["status"] == "success"


# REQ-F-025, Д.8: an inactive supplier is not fetched and has no row in the run.
def test_inactive_supplier_not_fetched(world):
    three(world)
    world.set_active("Вега", False)
    run = world.run()
    assert world.sim.requests("vega") == 0
    names = [r["supplier"]["name"] for r in run["supplier_run_statuses"]]
    assert names == ["Альфа", "Бета"]


# REQ-NF-004: after the catalogue address changes, the next run requests the
# new address and makes no request to the old one.
def test_changed_catalogue_address_used(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.put("alfa-new", [item("А-1")], name="Альфа")
    world.run()
    resp = world.admin.patch(
        f"{API}/suppliers/{world.supplier_ids['Альфа']}",
        json={"catalog_url": world.sim.url("alfa-new")},
    )
    assert resp.status_code == 200
    world.clock.advance(timedelta(days=1))
    run = world.run()
    assert (world.sim.requests("alfa"), world.sim.requests("alfa-new")) == (1, 1)
    assert row(run, "Альфа")["status"] == "success"


# --- REQ-F-012: unlinked items after a run -------------------------------------------------


# REQ-F-012: after a run every parsed item without a link is in the unlinked list
# with the date of this run; a linked item is not shown; items of А come before Б,
# each row names its supplier.
def test_unlinked_items_after_run(world):
    world.supplier("Альфа", "alfa", [item("А-1"), item("А-2")])
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 5)
    world.run()
    rows = world.unlinked()
    assert [(r["supplier"]["name"], r["sku"], r["last_seen_date"]) for r in rows] == [
        ("Альфа", "А-1", "2026-10-05"),
        ("Альфа", "А-2", "2026-10-05"),
        ("Бета", "Б-1", "2026-10-05"),
    ]
    world.material("М1")
    world.link("А-1", "М1")
    world.at(2026, 10, 6)
    world.run()
    assert [r["sku"] for r in world.unlinked()] == ["А-2", "Б-1"]


# REQ-F-012: unlinked Б-9 was on the page 2026-10-05 and is gone 2026-10-06;
# after the run of 2026-10-06 Б-9 stays in the list with 2026-10-05.
def test_unlinked_item_gone_keeps_last_seen_date(world):
    world.supplier("Бета", "beta", [item("Б-1"), item("Б-9")])
    world.at(2026, 10, 5)
    world.run()
    world.page("Бета", [item("Б-1")])
    world.at(2026, 10, 6)
    world.run()
    dates = {r["sku"]: r["last_seen_date"] for r in world.unlinked()}
    assert dates == {"Б-1": "2026-10-06", "Б-9": "2026-10-05"}


# REQ-F-012: no daily price is stored for unlinked items; a changed name or unit
# on the page is shown in the list after the run.
def test_unlinked_items_no_prices_and_new_name_unit(world):
    world.supplier("Альфа", "alfa", [item("А-1", "500.00", "шт", "Стара назва")])
    world.at(2026, 10, 5)
    world.run()
    world.page("Альфа", [item("А-1", "510.00", "уп", "Нова назва")])
    world.at(2026, 10, 6)
    world.run()
    (entry,) = world.unlinked()
    assert (entry["name"], entry["unit"]) == ("Нова назва", "уп")
    assert world.prices("А-1") == []


# --- REQ-F-027, REQ-F-028, REQ-F-016: daily prices --------------------------------------------


def linked(world, page, sku="А-1", unit="шт") -> None:
    """Supplier Альфа with ``page``; ``sku`` linked to М1 after a first run."""
    world.supplier("Альфа", "alfa", page)
    world.at(2026, 10, 1)
    world.run()
    world.material("М1", unit=unit)
    world.link(sku, "М1")


# REQ-F-027: the linked item priced 1250,50 грн on the page has the daily price
# 1250.50 (Decimal, no recalculation) with the unit as on the page.
def test_price_stored_as_on_page(world):
    linked(world, [item("А-1", "1250.50", "шт")])
    world.at(2026, 10, 5)
    world.run()
    price = world.price_on("А-1", D05)
    assert price.price == Decimal("1250.50")
    assert price.unit == "шт"
    assert price.material_id == world.material_ids["М1"]
    assert price.unit_mismatch is False


# REQ-F-028, BDD-010: two runs dated 2026-10-05 with prices 1000,00 and 1020,00 —
# one daily price for the date, 1020,00.
def test_second_run_same_date_replaces_price(world):
    linked(world, [item("А-1", "1000.00")])
    world.at(2026, 10, 5)
    world.run("scheduled")
    world.page("Альфа", [item("А-1", "1020.00")])
    world.at(2026, 10, 5, 10, 0)
    world.run("manual")
    assert world.price_on("А-1", D05).price == Decimal("1020.00")


# REQ-F-028, BDD-058: a same-date run without a new price keeps the stored one —
# "ціну уточнюйте", absent from the page, a price under another unit.
def test_same_date_run_without_new_price_keeps_stored(world):
    linked(world, [item("А-1", "1000.00"), item("А-2")])
    world.at(2026, 10, 5)
    world.run("scheduled")
    for hour, page in (
        (10, [item("А-1", None), item("А-2")]),
        (11, [item("А-2")]),
        (12, [item("А-1", "1100.00", "уп"), item("А-2")]),
    ):
        world.page("Альфа", page)
        world.at(2026, 10, 5, hour, 0)
        world.run("manual")
        price = world.price_on("А-1", D05)
        assert (price.price, price.unit_mismatch) == (Decimal("1000.00"), False)


# REQ-F-029: an item on the page without a price has no daily price for the date.
def test_item_without_price_has_no_daily_price(world):
    linked(world, [item("А-1", None)])
    world.at(2026, 10, 5)
    run = world.run()
    assert world.price_on("А-1", D05) is None
    assert row(run, "Альфа")["parsed_items_count"] == 1


# REQ-F-016: after linking a formerly unlinked item the material has no prices of
# the dates before the link.
def test_no_prices_before_link(world):
    linked(world, [item("А-1", "1000.00")])
    assert world.prices("А-1") == []
    world.at(2026, 10, 2)
    world.run()
    assert [p.price_date for p in world.prices("А-1")] == [date(2026, 10, 2)]


# REQ-F-016, BDD-026: after relinking from М1 to М2 and a run of the next date,
# М1 keeps the prices before the relink and М2 has only the new one.
def test_relink_keeps_history(world):
    linked(world, [item("А-3", "100.00")], sku="А-3")
    for day in (2, 3, 4, 5):
        world.at(2026, 10, day)
        world.run()
    world.material("М2")
    world.link("А-3", "М2")
    world.at(2026, 10, 6)
    world.run()
    by_material = {(p.price_date.day, p.material_id) for p in world.prices("А-3")}
    m1, m2 = world.material_ids["М1"], world.material_ids["М2"]
    assert by_material == {(2, m1), (3, m1), (4, m1), (5, m1), (6, m2)}


# REQ-F-016, REQ-F-028, BDD-042: relinked from М1 to М2 between two runs of
# 2026-10-05 — the one daily price of the date belongs to М2.
def test_relink_between_same_date_runs(world):
    linked(world, [item("А-3", "100.00")], sku="А-3")
    world.at(2026, 10, 5)
    world.run("scheduled")
    world.material("М2")
    world.link("А-3", "М2")
    world.at(2026, 10, 5, 10, 0)
    world.run("manual")
    price = world.price_on("А-3", D05)
    assert price.material_id == world.material_ids["М2"]


# REQ-F-015: after the link is removed the item's new prices are not stored.
def test_unlinked_again_no_new_prices(world):
    linked(world, [item("А-1", "100.00")])
    world.at(2026, 10, 2)
    world.run()
    world.unlink("А-1")
    world.at(2026, 10, 3)
    world.run()
    assert [p.price_date for p in world.prices("А-1")] == [date(2026, 10, 2)]


# REQ-F-017: the unit on the page changed from «шт» to «уп» — the daily price is
# stored with the mark "одиниця не збігається" and the supplier row has a
# unit_mismatch warning with the sku; the status does not change.
def test_unit_changed_on_page_marks_price(world):
    linked(world, [item("В-2", "100.00", "шт")], sku="В-2")
    world.page("Альфа", [item("В-2", "1000.00", "уп")])
    world.at(2026, 10, 9)
    run = world.run()
    price = world.price_on("В-2", date(2026, 10, 9))
    assert (price.price, price.unit, price.unit_mismatch) == (
        Decimal("1000.00"),
        "уп",
        True,
    )
    supplier = row(run, "Альфа")
    assert supplier["status"] == "success"
    assert {"kind": "unit_mismatch", "sku": "В-2"} in supplier["warnings"]


# --- REQ-F-060…REQ-F-062, BDD-051: anomalies of the page --------------------------------------


def with_base_100(world, prefix="А"):
    """Supplier Альфа: first run with 100 items — volume base 100 (REQ-F-052)."""
    world.supplier("Альфа", "alfa", items(prefix, 100))
    world.at(2026, 10, 1)
    world.run()


# REQ-F-060: 100 rows, А-5 twice (500,00 then 510,00) — the daily price of А-5 is
# 500,00, 99 parsed items, a duplicate_sku warning with А-5, status by REQ-F-030.
def test_duplicate_sku_first_row_wins(world):
    with_base_100(world)
    world.material("М5")
    world.link("А-5", "М5")
    page = items("А", 99)
    page[4] = item("А-5", "500.00")
    page.append(item("А-5", "510.00"))
    world.page("Альфа", page)
    world.at(2026, 10, 2)
    run = world.run()
    supplier = row(run, "Альфа")
    assert world.price_on("А-5", date(2026, 10, 2)).price == Decimal("500.00")
    assert supplier["parsed_items_count"] == 99
    assert supplier["warnings"] == [{"kind": "duplicate_sku", "sku": "А-5"}]
    assert supplier["status"] == "success"


# REQ-F-061: 100 rows, one without a sku and one with an unparsable price — 98
# parsed, two unparsed_row warnings, status by REQ-F-030 (success at base 100).
def test_rows_without_sku_or_unparsable_skipped(world):
    with_base_100(world)
    page = items("А", 98) + [item("", "100.00"), item("А-99", "12x.50")]
    world.page("Альфа", page)
    world.at(2026, 10, 2)
    supplier = row(world.run(), "Альфа")
    assert supplier["parsed_items_count"] == 98
    kinds = sorted((w["kind"], w["sku"] or "") for w in supplier["warnings"])
    assert kinds == [("unparsed_row", ""), ("unparsed_row", "А-99")]
    assert supplier["status"] == "success"


# REQ-F-062: the linked item priced 0,00 грн — no daily price for the date, a
# non_positive_price warning, the item counts as parsed; a negative price too.
@pytest.mark.parametrize("price", ["0.00", "-5.00"])
def test_zero_or_negative_price_is_no_price(world, price):
    linked(world, [item("А-1", "100.00"), item("А-2")])
    world.page("Альфа", [item("А-1", price), item("А-2")])
    world.at(2026, 10, 5)
    supplier = row(world.run(), "Альфа")
    assert world.price_on("А-1", D05) is None
    assert supplier["warnings"] == [{"kind": "non_positive_price", "sku": "А-1"}]
    assert supplier["parsed_items_count"] == 2
    assert supplier["status"] == "success"
    assert world.events("А-1") == []


# BDD-051: base 100; 100 rows with А-5 twice, a row without sku and А-8 at 0,00 —
# А-5 from the first row, no price of А-8, 98 parsed, "успіх", three warnings.
# Then mode "зламана верстка" — "помилка" with "сторінку не розібрано".
def test_bdd051_anomalies_then_broken_layout(world):
    with_base_100(world)
    world.material("М5")
    world.material("М8")
    world.link("А-5", "М5")
    world.link("А-8", "М8")
    page = items("А", 97)
    page[4] = item("А-5", "500.00")
    page[7] = item("А-8", "0.00")
    page += [item("А-5", "510.00"), item("", "100.00"), item("А-98")]
    world.page("Альфа", page)
    world.at(2026, 10, 2)
    supplier = row(world.run(), "Альфа")
    assert world.price_on("А-5", date(2026, 10, 2)).price == Decimal("500.00")
    assert world.price_on("А-8", date(2026, 10, 2)) is None
    assert (supplier["parsed_items_count"], supplier["status"]) == (98, "success")
    assert sorted(w["kind"] for w in supplier["warnings"]) == [
        "duplicate_sku",
        "non_positive_price",
        "unparsed_row",
    ]
    world.mode("Альфа", "broken")
    world.at(2026, 10, 3)
    supplier = row(world.run(), "Альфа")
    assert (supplier["status"], supplier["reason_code"]) == ("error", "unparsable")
    assert supplier["error_reason"] == REASON_TEXT["unparsable"]
    assert supplier["parsed_items_count"] is None


# REQ-F-026: a page whose rows are all skipped (REQ-F-061) — "помилка" with
# "сторінку не розібрано", and no volume base comes from such a run: the next
# run with one item is "успіх" with nothing to accept.
def test_all_rows_skipped_is_unparsable(world):
    world.supplier("Альфа", "alfa", [item("", "10.00"), item("", "20.00")])
    supplier = row(world.run(), "Альфа")
    assert (supplier["status"], supplier["reason_code"]) == ("error", "unparsable")
    assert supplier["error_reason"] == "сторінку не розібрано"
    world.page("Альфа", [item("А-1")])
    world.clock.advance(timedelta(days=1))
    supplier = row(world.run(), "Альфа")
    assert (supplier["status"], supplier["parsed_items_count"]) == ("success", 1)


# --- REQ-F-026, REQ-NF-013: supplier errors -------------------------------------------------------


# REQ-F-026, BDD-002: one page of three is unavailable — that supplier "помилка"
# with "сторінка недоступна" after exactly one request; the other two "успіх" with
# their daily prices written; the run "частково".
def test_unavailable_page(world):
    three(world)
    world.at(2026, 10, 4)
    world.run()
    for sku, material in (("А-1", "МА"), ("В-1", "МВ")):
        world.material(material)
        world.link(sku, material)
    world.mode("Бета", "unavailable")
    world.at(2026, 10, 5)
    run = world.run()
    beta = row(run, "Бета")
    assert (beta["status"], beta["reason_code"]) == ("error", "unavailable")
    assert beta["error_reason"] == "сторінка недоступна"
    assert beta["parsed_items_count"] is None
    assert world.sim.requests("beta") == 2  # one in the first run, one now
    assert row(run, "Альфа")["status"] == row(run, "Вега")["status"] == "success"
    assert world.price_on("А-1", D05) is not None
    assert world.price_on("В-1", D05) is not None
    assert run["status"] == "partial"


# REQ-F-026: the named fetch timeout is 30 s.
def test_fetch_timeout_constant_is_30_seconds(update_fetch_module):
    assert update_fetch_module.FETCH_TIMEOUT_SECONDS == 30


# REQ-F-026, REQ-NF-013, BDD-003: with the timeout replaced by 1 s and the
# simulator delay 2 s, the slow supplier is "помилка" with "перевищено час
# очікування 1 с" after one request (no retry); the others succeed.
def test_slow_page_times_out(world, update_fetch_module, monkeypatch):
    monkeypatch.setattr(update_fetch_module, "FETCH_TIMEOUT_SECONDS", 1)
    three(world)
    world.mode("Вега", "slow", delay_seconds=2)
    run = world.run()
    vega = row(run, "Вега")
    assert (vega["status"], vega["reason_code"]) == ("error", "timeout")
    assert vega["error_reason"] == "перевищено час очікування 1 с"
    assert world.sim.requests("vega") == 1
    assert row(run, "Альфа")["status"] == "success"


# --- REQ-F-067, BDD-060: the snapshot at the start of the run ---------------------------------------


# REQ-F-067, BDD-060: while the run waits for Альфа's page, the administrator
# links unlinked Б-9 to М1, deactivates Вега, changes Бета's catalogue address
# and the threshold 1 % -> 2 %. This run writes no price of Б-9, requests Вега
# and Бета's old address and applies 1 % (Б-1 +1,5 % gives an event). The next
# run writes Б-9 for М1, skips Вега, uses Бета's new address and applies 2 %
# (another +1,5 % gives no event).
def test_run_uses_snapshot_of_its_start(world):
    from helpers_b2 import start_manual, wait_run, wait_until

    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1", "1000.00"), item("Б-9", "50.00")])
    world.supplier("Вега", "vega", [item("В-1")])
    world.sim.put("beta-new", [item("Б-1", "1000.00"), item("Б-9", "50.00")])
    world.at(2026, 10, 1)
    world.run()
    world.material("МБ1")
    world.material("М1")
    world.link("Б-1", "МБ1")
    world.at(2026, 10, 2)
    world.run()  # "appeared": base of Б-1 is 1000,00
    world.page("Бета", [item("Б-1", "1015.00"), item("Б-9", "50.00")])
    world.sim.put("beta-new", [item("Б-1", "1030.23"), item("Б-9", "50.00")])

    world.at(2026, 10, 5)
    world.sim.hold("alfa")
    run_id = start_manual(world.admin)["id"]
    wait_until(lambda: world.sim.requests("alfa") == 3, what="request to Альфа")
    world.link("Б-9", "М1")
    world.set_active("Вега", False)
    resp = world.admin.patch(
        f"{API}/suppliers/{world.supplier_ids['Бета']}",
        json={"catalog_url": world.sim.url("beta-new")},
    )
    assert resp.status_code == 200
    world.settings(notification_threshold=2)
    world.sim.release("alfa")
    run = wait_run(world.admin, run_id)

    assert world.price_on("Б-9", D05) is None
    assert world.sim.requests("vega") == 3
    assert row(run, "Вега")["status"] == "success"
    assert (world.sim.requests("beta"), world.sim.requests("beta-new")) == (3, 0)
    (event,) = world.events("Б-1", "price_change")
    assert (event.old_price, event.new_price) == (
        Decimal("1000.00"),
        Decimal("1015.00"),
    )

    world.at(2026, 10, 6)
    world.run()
    assert world.price_on("Б-9", D06).material_id == world.material_ids["М1"]
    assert world.sim.requests("vega") == 3
    assert world.sim.requests("beta-new") == 1
    assert len(world.events("Б-1", "price_change")) == 1


# --- REQ-NF-016: atomic write of a supplier ---------------------------------------------------------


# REQ-NF-016: a failure caused in the middle of writing Бета's data (the second
# daily price) — after the run there is no daily price and no event of Бета from
# this run; Бета is "помилка" (write_failed) with a short Ukrainian text without
# internals; Альфа's data is written fully.
def test_write_failure_rolls_back_supplier(world, config):
    world.supplier("Альфа", "alfa", [item("А-1"), item("А-2")])
    world.supplier("Бета", "beta", [item("Б-1"), item("Б-2")])
    world.at(2026, 10, 1)
    world.run()
    for sku in ("А-1", "А-2", "Б-1", "Б-2"):
        world.material(f"М{sku}")
        world.link(sku, f"М{sku}")
    with closing(sqlite3.connect(config.database_path)) as db:
        db.execute(
            "CREATE TRIGGER test_write_failure AFTER INSERT ON daily_prices"
            f" WHEN NEW.supplier_item_id = {world.item_ids['Б-2']}"
            " BEGIN SELECT RAISE(ABORT, 'test write failure'); END"
        )
        db.commit()
    world.at(2026, 10, 2)
    run = world.run()
    beta = row(run, "Бета")
    assert (beta["status"], beta["reason_code"]) == ("error", "write_failed")
    assert beta["error_reason"] and "daily_prices" not in beta["error_reason"]
    assert "test write failure" not in beta["error_reason"]
    assert world.prices("Б-1") == world.prices("Б-2") == []
    assert world.events("Б-1") == world.events("Б-2") == []
    assert [p.price_date for p in world.prices("А-1")] == [d("2026-10-02")]
    assert [e.kind for e in world.events("А-2")] == ["appeared"]
    assert row(run, "Альфа")["status"] == "success"

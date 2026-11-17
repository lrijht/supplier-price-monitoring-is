"""T-34: the change feed (screen and operation 21).

REQ-F-042 (shown, one feed for both roles), REQ-F-057 (the feed, the order of
the filter values), REQ-F-058, REQ-NF-030; BDD-045, BDD-064 (order); UC-04.

Screen: ``GET /events?page=N&material_id=…&supplier_id=…&kind=…`` — the
parameters of the API; a GET form with ``<select name="material_id">``,
``<select name="supplier_id">`` and ``<select name="kind">`` (option values —
the API values). The data table starts with the columns "дата", "вид",
"матеріал", "постачальник". Events come from real runs on the simulator.
"""

from __future__ import annotations

import pytest
from helpers import API, create_material, create_supplier, data_table, page_text
from helpers_b2 import item, items, kyiv, move_to, start_manual, wait_run, wait_until
from helpers_b3 import (
    KIND_TEXT,
    compact,
    feed,
    feed_keys,
    row_text,
    screen,
    select_options,
    stored_feed_keys,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

ALPHABET_NAMES = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
ALPHABET_ORDER = ["2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак", "Alpha"]
FEED_COLUMNS = ["дата", "вид", "матеріал", "постачальник"]


def feed_screen(client, query: str = "") -> list[list[str]]:
    html = screen(client, f"/events{query}")
    headers, rows = data_table(html)
    assert [h.lower() for h in headers[:4]] == FEED_COLUMNS
    return rows


def kind_of(row: list[str]) -> str:
    (kind,) = [k for k, text in KIND_TEXT.items() if row[1] == text]
    return kind


@pytest.fixture
def five(world):
    """Events: "з'явився" А-1 (М1), А-2 (М2), Б-1 (М1) on 2026-10-02; "зміна ціни"
    А-1 1000,00 → 1100,00 on 2026-10-03; "зник" Б-1 on 2026-10-04."""
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00"), item("А-2", "500.00")])
    beta = items("Б", 5, "200.00")
    world.supplier("Бета", "beta", beta)
    world.at(2026, 10, 1)
    world.run()
    world.material("М1")
    world.material("М2")
    world.link("А-1", "М1")
    world.link("А-2", "М2")
    world.link("Б-1", "М1")
    world.at(2026, 10, 2)
    world.run()
    world.page("Альфа", [item("А-1", "1100.00"), item("А-2", "500.00")])
    world.page("Бета", beta[1:])
    world.at(2026, 10, 3)
    world.run()
    world.at(2026, 10, 4)
    world.run()
    return world


# --- REQ-F-057: order and pages -------------------------------------------------------------------


# REQ-F-057 criterion, T-34: 120 events — the pages hold the 50 newest, the next
# 50 and the 20 oldest, by date and time of creation (60 events on 2026-10-02,
# 60 on 2026-10-03); events created at the same moment — the later created is
# higher (order of creation from storage). API and screen.
def test_feed_120_events_pages(world, manager_client):
    page = items("А", 120, "100.00")
    world.supplier("Альфа", "alfa", page)
    world.at(2026, 10, 1)
    world.run()
    for n in range(1, 121):
        world.material(f"М{n:03d}")
    for n in range(1, 61):
        world.link(f"А-{n}", f"М{n:03d}")
    world.at(2026, 10, 2)
    world.run()
    for n in range(61, 121):
        world.link(f"А-{n}", f"М{n:03d}")
    world.at(2026, 10, 3)
    world.run()
    expected = stored_feed_keys(world)
    assert len(expected) == 120
    pages = [manager_client.get(f"{API}/events?page={p}").json() for p in (1, 2, 3, 4)]
    assert [len(p["items"]) for p in pages] == [50, 50, 20, 0]
    assert (pages[0]["total_items"], pages[0]["total_pages"]) == (120, 3)
    assert feed_keys([e for p in pages for e in p["items"]]) == expected
    assert {e["date"] for e in pages[0]["items"]} == {"2026-10-03"}
    names = {mid: name for name, mid in world.material_ids.items()}
    shown = []
    for p in (1, 2, 3):
        shown += [r[2] for r in feed_screen(manager_client, f"?page={p}")]
    assert shown == [names[key[1]] for key in expected]


# BDD-064, REQ-F-057 criterion: the run started 2026-10-05 at 23:59 creates after
# midnight "зміна ціни" for А-1 and "зник" for А-2 with the same creation time —
# both have the date "2026-10-05", and the one created later is higher (API and
# screen).
def test_same_creation_time_later_created_higher_bdd064(world, manager_client):
    page = [item("А-1", "1000.00"), item("А-2", "1000.00")] + [
        item(f"А-{n}") for n in range(3, 9)
    ]
    world.linked_with_base("Альфа", "alfa", page, {"А-1": "М1", "А-2": "М2"})
    world.page("Альфа", [i for i in page if i["sku"] != "А-2"])
    world.at(2026, 10, 4)
    world.run()
    world.page("Альфа", [item("А-1", "1100.00")] + page[2:])
    world.at(2026, 10, 5, 23, 59)
    world.sim.hold("alfa")
    run_id = start_manual(world.admin)["id"]
    wait_until(lambda: world.sim.requests("alfa") == 4, what="request to Альфа")
    move_to(world.clock, kyiv(2026, 10, 6, 0, 1))
    world.sim.release()
    wait_run(world.admin, run_id)
    expected = stored_feed_keys(world)[:2]
    assert {k[0] for k in expected} == {"price_change", "disappeared"}
    events = feed(manager_client)
    assert feed_keys(events[:2]) == expected
    assert events[0]["created_at"] == events[1]["created_at"]
    assert events[0]["created_at"] == "2026-10-06T00:01:00+03:00"
    assert [e["date"] for e in events[:2]] == ["2026-10-05", "2026-10-05"]
    rows = feed_screen(manager_client)
    assert [r[0] for r in rows[:2]] == ["2026-10-05", "2026-10-05"]
    assert [kind_of(r) for r in rows[:2]] == [k[0] for k in expected]


# --- REQ-F-058: filters ----------------------------------------------------------------------------


# REQ-F-058 criterion: material М1 — only М1 events; supplier Бета — only Бета's;
# Бета and "зник" — only Бета's "зник"; no filters — all; the filters work alone
# and together (API and screen).
@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, ["disappeared", "price_change", "appeared", "appeared", "appeared"]),
        ({"material": "М1"}, ["disappeared", "price_change", "appeared", "appeared"]),
        ({"material": "М2"}, ["appeared"]),
        ({"supplier": "Бета"}, ["disappeared", "appeared"]),
        ({"supplier": "Бета", "kind": "disappeared"}, ["disappeared"]),
        ({"kind": "appeared"}, ["appeared", "appeared", "appeared"]),
        (
            {"material": "М1", "supplier": "Альфа", "kind": "price_change"},
            ["price_change"],
        ),
        ({"material": "М2", "kind": "disappeared"}, []),
    ],
)
def test_feed_filters(five, manager_client, filters, expected):
    params = {}
    if "material" in filters:
        params["material_id"] = five.material_ids[filters["material"]]
    if "supplier" in filters:
        params["supplier_id"] = five.supplier_ids[filters["supplier"]]
    if "kind" in filters:
        params["kind"] = filters["kind"]
    events = feed(manager_client, **params)
    assert [e["kind"] for e in events] == expected
    if "material" in filters:
        assert {e["material"]["name"] for e in events} <= {filters["material"]}
    if "supplier" in filters:
        assert {e["supplier"]["name"] for e in events} <= {filters["supplier"]}
    query = "&".join(f"{k}={v}" for k, v in params.items())
    rows = feed_screen(manager_client, f"?{query}" if query else "")
    assert [kind_of(r) for r in rows] == expected


# Contract (operation 21): a filter with an id that does not exist gives an empty
# list, not an error.
@pytest.mark.parametrize("param", ["material_id", "supplier_id"])
def test_feed_filter_unknown_id_empty(five, manager_client, param):
    body = manager_client.get(f"{API}/events?{param}=9999").json()
    assert (body["items"], body["total_items"]) == ([], 0)


# REQ-F-057 (П-3), REQ-F-011: the values of the material and supplier filters are
# in alphabetical order by name; a deactivated supplier stays in the supplier
# filter; the kind filter offers the three kinds.
def test_filter_values_alphabetical(admin_client, manager_client):
    for n, name in enumerate(ALPHABET_NAMES):
        create_material(admin_client, name)
        create_supplier(admin_client, name, catalog_url=f"http://localhost:8001/{n}")
    alpha = [
        s
        for s in admin_client.get(f"{API}/suppliers").json()["items"]
        if s["name"] == "Іскра"
    ]
    admin_client.patch(f"{API}/suppliers/{alpha[0]['id']}", json={"active": False})
    html = screen(manager_client, "/events")
    assert [t for _, t in select_options(html, "material_id")] == ALPHABET_ORDER
    assert [t for _, t in select_options(html, "supplier_id")] == ALPHABET_ORDER
    assert {v for v, _ in select_options(html, "kind")} == set(KIND_TEXT)


# --- REQ-F-042: fields of each kind ---------------------------------------------------------------


# REQ-F-042: each event has kind, date, material and supplier; "зміна ціни" — old
# price (the base), new price and percent; "з'явився" — its price; "зник" — none
# of them (API: the other fields are null). П-23.
def test_fields_of_each_kind(five, manager_client):
    events = feed(manager_client)
    by_kind = {e["kind"]: e for e in events}
    change = by_kind["price_change"]
    assert (change["old_price"], change["new_price"], change["change_percent"]) == (
        "1000.00",
        "1100.00",
        10.0,
    )
    assert change["price"] is None
    assert change["date"] == "2026-10-03"
    assert change["material"] == {"id": five.material_ids["М1"], "name": "М1"}
    assert change["supplier"] == {"id": five.supplier_ids["Альфа"], "name": "Альфа"}
    gone = by_kind["disappeared"]
    assert (
        gone["old_price"],
        gone["new_price"],
        gone["change_percent"],
        gone["price"],
    ) == (None,) * 4
    assert (gone["date"], gone["supplier"]["name"]) == ("2026-10-04", "Бета")
    appeared = [e for e in events if e["kind"] == "appeared"]
    assert {e["price"] for e in appeared} == {"1000.00", "500.00", "200.00"}
    for e in appeared:
        assert (e["old_price"], e["new_price"], e["change_percent"]) == (None,) * 3
    rows = {kind_of(r): row_text(r) for r in feed_screen(manager_client)}
    assert "1000,00" in compact(rows["price_change"])
    assert "1100,00" in compact(rows["price_change"])
    assert "+10,0" in compact(rows["price_change"])
    assert "2026-10-03" in rows["price_change"] and "М1" in rows["price_change"]
    assert "2026-10-04" in rows["disappeared"] and "Бета" in rows["disappeared"]
    assert "200,00" not in compact(rows["disappeared"])
    assert any(p in compact(rows["appeared"]) for p in ("1000,00", "500,00", "200,00"))


# REQ-F-044 example of the contract (price_decrease): 1000,00 → 990,00 is shown
# with a minus: API -1.0, screen "-1,0" (or the sign "−").
def test_price_decrease_has_minus(world, manager_client):
    world.linked_with_base("Альфа", "alfa", [item("А-1", "1000.00")], {"А-1": "М1"})
    world.page("Альфа", [item("А-1", "990.00")])
    world.at(2026, 10, 3)
    world.run()
    (change,) = feed(manager_client, kind="price_change")
    assert change["change_percent"] == -1.0
    (row,) = [r for r in feed_screen(manager_client) if kind_of(r) == "price_change"]
    text = compact(row_text(row)).replace("−", "-")
    assert "-1,0" in text


# BDD-045, REQ-F-042 criterion: events exist for М1; М2 is deactivated and Б-9 is
# unlinked; a run writes changes above the threshold for М1, М2 and Б-9 — only М1
# gets an event, and the manager and the administrator see the same list (API
# and screen).
def test_one_feed_for_both_roles_bdd045(world, admin_client, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00"), item("А-2", "1000.00")])
    world.supplier("Бета", "beta", [item("Б-9", "1000.00")])
    world.at(2026, 10, 1)
    world.run()
    world.material("М1")
    world.material("М2")
    world.link("А-1", "М1")
    world.link("А-2", "М2")
    world.at(2026, 10, 2)
    world.run()
    before = feed(admin_client)
    world.admin.patch(
        f"{API}/materials/{world.material_ids['М2']}", json={"active": False}
    )
    world.page("Альфа", [item("А-1", "1100.00"), item("А-2", "1100.00")])
    world.page("Бета", [item("Б-9", "1100.00")])
    world.at(2026, 10, 3)
    world.run()
    events = feed(admin_client)
    new = events[: len(events) - len(before)]
    assert [(e["kind"], e["material"]["name"]) for e in new] == [("price_change", "М1")]
    assert feed(manager_client) == events
    assert feed_screen(manager_client) == feed_screen(admin_client)


# REQ-NF-030 criterion: an event of 5 October 2026 has "2026-10-05" in the feed.
def test_feed_date_format(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00")])
    world.at(2026, 10, 4)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    world.at(2026, 10, 5)
    world.run()
    rows = feed_screen(manager_client)
    assert [r[0] for r in rows] == ["2026-10-05"]
    assert "2026-10-05" in page_text(screen(manager_client, "/events"))

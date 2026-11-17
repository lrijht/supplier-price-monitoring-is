"""T-53 (operation 15) and T-54 (operations 18–21): the view operations of the API.

REQ-NF-031, REQ-F-070 and the REQ-ID of the operations (docs/api/resources.md,
section 3); BDD-068 in full; contract scenarios from
tests/contract/scenarios.json (ID above each test): П-15, П-17, П-21, П-22,
П-23, Н-01, Н-22, Н-23, Н-37, Н-45. The manager gets through the API the same
comparisons, history, feed and supplier update statuses as on the screens.
"""

from __future__ import annotations

import sqlite3

import pytest
from helpers import (
    API,
    NO_ACCESS,
    assert_problem,
    create_material,
    create_supplier,
    data_table,
    error_codes,
)
from helpers_b2 import NEVER_UPDATED
from helpers_b3 import (
    KIND_TEXT,
    D,
    Market,
    all_screen_rows,
    compact,
    feed,
    feed_keys,
    row_text,
    screen,
    stored_feed_keys,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

PAGE_FIELDS = {"items", "page", "page_size", "total_items", "total_pages"}


def screen_money(value: str | None) -> str:
    """ "1000.00" as the screens show it (comma, spaces removed)."""
    return value.replace(".", ",") if value else "—"


@pytest.fixture
def market(world):
    """М1: Альфа 1000,00 and Бета 1100,00 on 2026-10-10 (Альфа 1010,00 on 10-09 —
    a change and an event); М2 and М3: linked items without a price; Дельта is
    created after the runs (never updated)."""
    m = Market(
        world,
        {
            "Альфа": {"А-1": "М1"},
            "Бета": {"Б-1": "М1", "Б-2": "М2"},
            "Вега": {"В-1": "М3"},
        },
    )
    m.day(D(9), {"Альфа": {"А-1": "1010.00"}, "Бета": {"Б-1": "1100.00", "Б-2": None}})
    m.day(D(10), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00", "Б-2": None}})
    create_supplier(world.admin, "Дельта", catalog_url="http://localhost:8001/d")
    return m


# --- 401 without a session, 403 for the manager on operation 15 ------------------------------------

VIEWS = [
    (15, "/attention-items"),
    (18, "/material-comparisons"),
    (19, "/material-comparisons/{m1}"),
    (20, "/materials/{m1}/price-history?period=all"),
    (21, "/events"),
]


# Н-01, REQ-NF-031, REQ-NF-021: without a session operations 15, 18–21 are 401
# unauthenticated, without a Location header.
@pytest.mark.parametrize(("number", "path"), VIEWS)
def test_without_session_401(market, client, number, path):
    resp = client.get(API + path.format(m1=market.mid("М1")))
    assert_problem(resp, 401, "unauthenticated")
    assert "location" not in resp.headers


# Н-37, REQ-F-005, REQ-NF-031: the manager on operation 15 (administrator) — 403
# "немає доступу" with no data; the state is the same after the request (the
# list for the administrator is unchanged).
def test_manager_attention_items_403_state_unchanged(
    market, admin_client, manager_client
):
    before = admin_client.get(f"{API}/attention-items").json()
    problem = assert_problem(
        manager_client.get(f"{API}/attention-items"), 403, "forbidden"
    )
    assert problem["detail"] == NO_ACCESS
    assert admin_client.get(f"{API}/attention-items").json() == before
    assert_problem(
        manager_client.get(f"{API}/attention-items?page=abc"), 403, "forbidden"
    )


# REQ-F-003, REQ-NF-031: operations 18–21 are open to both roles — 200 JSON.
@pytest.mark.parametrize(("number", "path"), VIEWS[1:])
def test_views_open_to_both_roles(market, admin_client, manager_client, number, path):
    for c in (admin_client, manager_client):
        resp = c.get(API + path.format(m1=market.mid("М1")))
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("application/json")
    a = admin_client.get(API + path.format(m1=market.mid("М1"))).json()
    m = manager_client.get(API + path.format(m1=market.mid("М1"))).json()
    assert a == m


# --- BDD-068 ----------------------------------------------------------------------------------------


# BDD-068, Н-01, Н-03: threshold 1 %; a request without a session to the comparison
# list — 401; the manager changes the threshold to 2 % — 403 "немає доступу", the
# threshold stays 1 %; the administrator — 200, the threshold is 2 %.
def test_access_by_roles_bdd068(accounts, client, admin_client, manager_client):
    assert admin_client.get(f"{API}/settings").json()["notification_threshold"] == 1
    assert_problem(client.get(f"{API}/material-comparisons"), 401, "unauthenticated")
    problem = assert_problem(
        manager_client.patch(f"{API}/settings", json={"notification_threshold": 2}),
        403,
        "forbidden",
    )
    assert problem["detail"] == NO_ACCESS
    assert admin_client.get(f"{API}/settings").json()["notification_threshold"] == 1
    resp = admin_client.patch(f"{API}/settings", json={"notification_threshold": 2})
    assert resp.status_code == 200
    assert resp.json()["notification_threshold"] == 2
    assert admin_client.get(f"{API}/settings").json()["notification_threshold"] == 2


# --- 15 GET /attention-items --------------------------------------------------------------------------


# П-17, REQ-F-017, REQ-F-068: the page has the page fields and, for an item with
# "уп", the page unit, the material unit and the date of the last marked price.
def test_attention_items_positive(world, admin_client):
    m = Market(world, {"Вега": {"В-2": "М1"}})
    m.day(D(9), {"Вега": {"В-2": ("1000.00", "уп")}})
    body = admin_client.get(f"{API}/attention-items").json()
    assert set(body) == PAGE_FIELDS
    (entry,) = body["items"]
    assert entry["supplier_item"]["unit"] == "уп"
    assert entry["material"]["unit"] == "шт"
    assert entry["last_unit_mismatch_date"] == "2026-10-09"


# --- 18 GET /material-comparisons ---------------------------------------------------------------------


# П-21, REQ-F-035, REQ-F-057: the page of active materials by name with the
# cheapest supplier and price; a material without a suitable price — null, null.
def test_comparison_list_positive(market, manager_client):
    body = manager_client.get(f"{API}/material-comparisons").json()
    assert set(body) == PAGE_FIELDS
    assert (body["page"], body["page_size"], body["total_items"]) == (1, 50, 3)
    assert body["items"] == [
        {
            "material": {"id": market.mid("М1"), "name": "М1"},
            "cheapest_supplier": {"id": market.sid("Альфа"), "name": "Альфа"},
            "price": "1000.00",
        },
        {
            "material": {"id": market.mid("М2"), "name": "М2"},
            "cheapest_supplier": None,
            "price": None,
        },
        {
            "material": {"id": market.mid("М3"), "name": "М3"},
            "cheapest_supplier": None,
            "price": None,
        },
    ]


# REQ-F-057, contract: page "0"/"abc" — 422 page_invalid; past the end — 200 empty;
# an unknown query parameter is ignored.
def test_comparison_list_page_parameter(market, manager_client):
    for value in ("0", "abc"):
        problem = assert_problem(
            manager_client.get(f"{API}/material-comparisons?page={value}"),
            422,
            "validation_failed",
        )
        assert error_codes(problem) == [("page", "page_invalid")]
    body = manager_client.get(f"{API}/material-comparisons?page=2").json()
    assert (body["items"], body["page"], body["total_pages"]) == ([], 2, 1)
    assert (
        manager_client.get(f"{API}/material-comparisons?colour=red").status_code == 200
    )


# --- 19 GET /material-comparisons/{material_id} -------------------------------------------------------


# П-22, REQ-F-036, REQ-F-038: material.active and, per row, daily_price, stale,
# cheapest, difference_from_cheapest.
def test_material_comparison_positive(market, manager_client):
    body = manager_client.get(f"{API}/material-comparisons/{market.mid('М1')}").json()
    assert set(body) == {"material", "items"}
    assert body["material"] == {"id": market.mid("М1"), "name": "М1", "active": True}
    for r in body["items"]:
        assert set(r) == {
            "supplier",
            "daily_price",
            "stale",
            "cheapest",
            "difference_from_cheapest",
        }
        assert set(r["supplier"]) == {"id", "name"}


# REQ-NF-031 (section 0 of resources.md): "abc" — 422 invalid_type for material_id
# (before 404); an unknown material — 404 not_found.
def test_material_comparison_errors(market, manager_client):
    problem = assert_problem(
        manager_client.get(f"{API}/material-comparisons/abc"), 422, "validation_failed"
    )
    assert error_codes(problem) == [("material_id", "invalid_type")]
    assert_problem(
        manager_client.get(f"{API}/material-comparisons/9999"), 404, "not_found"
    )


# --- 20 GET /materials/{material_id}/price-history ----------------------------------------------------


# П-15, REQ-F-040: material, period and the rows with date, supplier, price, the
# marks; the manager may read it (operation for both roles).
def test_price_history_positive(market, manager_client):
    resp = manager_client.get(
        f"{API}/materials/{market.mid('М1')}/price-history?period=last_7_days"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"material", "period", "items"}
    assert body["material"] == {"id": market.mid("М1"), "name": "М1", "active": True}
    assert body["period"] == "last_7_days"
    assert body["items"][0] == {
        "date": "2026-10-10",
        "supplier": {"id": market.sid("Альфа"), "name": "Альфа"},
        "price": "1000.00",
        "unit_mismatch": False,
        "effective_at_period_start": False,
    }


# Н-22, contract: without period — 422 required; an unknown period — 422
# period_invalid; "abc" — 422 invalid_type for material_id; unknown — 404.
@pytest.mark.parametrize(
    ("path", "status", "expected"),
    [
        ("/materials/{m1}/price-history", 422, [("period", "required")]),
        (
            "/materials/{m1}/price-history?period=week",
            422,
            [("period", "period_invalid")],
        ),
        (
            "/materials/abc/price-history?period=all",
            422,
            [("material_id", "invalid_type")],
        ),
        ("/materials/9999/price-history?period=all", 404, None),
    ],
)
def test_price_history_errors(market, manager_client, path, status, expected):
    resp = manager_client.get(API + path.format(m1=market.mid("М1")))
    if status == 404:
        assert_problem(resp, 404, "not_found")
    else:
        assert error_codes(assert_problem(resp, 422, "validation_failed")) == expected


# REQ-F-049, REQ-F-070: the history of a deactivated material is open to the
# manager; material.active is false.
def test_price_history_of_deactivated_material(market, admin_client, manager_client):
    admin_client.patch(f"{API}/materials/{market.mid('М1')}", json={"active": False})
    body = manager_client.get(
        f"{API}/materials/{market.mid('М1')}/price-history?period=all"
    ).json()
    assert body["material"]["active"] is False
    assert sorted(r["price"] for r in body["items"]) == [
        "1000.00",
        "1010.00",
        "1100.00",
    ]


# --- 21 GET /events -----------------------------------------------------------------------------------


# П-23, REQ-F-042, REQ-F-058: with material_id the page holds the events of М1
# with id, kind, created_at, the prices and the page fields.
def test_events_positive(market, manager_client):
    body = manager_client.get(f"{API}/events?material_id={market.mid('М1')}").json()
    assert set(body) == PAGE_FIELDS
    assert body["items"]
    fields = {
        "id",
        "kind",
        "date",
        "created_at",
        "material",
        "supplier",
        "old_price",
        "new_price",
        "change_percent",
        "price",
    }
    for e in body["items"]:
        assert set(e) == fields
        assert e["material"] == {"id": market.mid("М1"), "name": "М1"}
        assert isinstance(e["id"], int)
    assert feed_keys(body["items"]) == [
        k for k in stored_feed_keys(market.world) if k[1] == market.mid("М1")
    ]


# Н-23, contract: kind "price_drop" — 422 kind_invalid; page "0" — page_invalid;
# material_id "abc" — invalid_type.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("kind=price_drop", [("kind", "kind_invalid")]),
        ("page=0", [("page", "page_invalid")]),
        ("material_id=abc", [("material_id", "invalid_type")]),
        ("supplier_id=x", [("supplier_id", "invalid_type")]),
    ],
)
def test_events_errors(manager_client, query, expected):
    problem = assert_problem(
        manager_client.get(f"{API}/events?{query}"), 422, "validation_failed"
    )
    assert error_codes(problem) == expected


# REQ-NF-031: date and time are ISO 8601 with the Kyiv offset — an event created
# in summer has +03:00, in winter +02:00; its date is РРРР-ММ-ДД.
@pytest.mark.parametrize(("month", "offset"), [(10, "+03:00"), (11, "+02:00")])
def test_event_dates_kyiv_offset(world, manager_client, month, offset):
    m = Market(world, {"Альфа": {"А-1": "М1"}}, start=D(1, month))
    m.day(D(5, month), {"Альфа": {"А-1": "1000.00"}}, hour=3, minute=30)
    (event,) = feed(manager_client)
    assert event["date"] == f"2026-{month:02d}-05"
    assert event["created_at"] == f"2026-{month:02d}-05T03:30:00{offset}"


# --- 500 ----------------------------------------------------------------------------------------------


# Н-45, REQ-NF-018, REQ-NF-031: an artificial storage failure (the daily prices
# table dropped after start) — the comparison list answers 500 internal_error
# without "errors" and without internal details.
def test_comparison_list_storage_failure_500(admin_client, manager_client, config):
    create_material(admin_client, "М1")
    with sqlite3.connect(config.database_path) as db:
        db.execute("DROP TABLE daily_prices")
    resp = manager_client.get(f"{API}/material-comparisons")
    body = assert_problem(resp, 500, "internal_error")
    assert "errors" not in body
    for detail in ("daily_prices", "Traceback", "sqlite", "OperationalError"):
        assert detail not in resp.text


# --- the same data as the screens --------------------------------------------------------------------


# REQ-NF-031, T-54: the manager gets through the API the same comparison list,
# material comparison, history, feed and supplier update statuses as on the
# screens.
def test_manager_api_same_as_screens(market, manager_client):
    listed = manager_client.get(f"{API}/material-comparisons").json()["items"]
    rows = all_screen_rows(manager_client, "/material-comparisons")
    assert [r[0] for r in rows] == [x["material"]["name"] for x in listed]
    for r, x in zip(rows, listed, strict=True):
        if x["cheapest_supplier"]:
            assert x["cheapest_supplier"]["name"] in row_text(r)
        assert screen_money(x["price"]) in compact(row_text(r))

    mid = market.mid("М1")
    by_supplier = {
        x["supplier"]["name"]: x
        for x in manager_client.get(f"{API}/material-comparisons/{mid}").json()["items"]
    }
    _, rows = data_table(screen(manager_client, f"/material-comparisons/{mid}"))
    assert len(rows) == len(by_supplier)
    for name, x in by_supplier.items():
        (r,) = [r for r in rows if name in row_text(r)]
        assert screen_money(x["daily_price"]["price"]) in compact(row_text(r))
        assert x["daily_price"]["date"] in row_text(r)

    api_history = manager_client.get(
        f"{API}/materials/{mid}/price-history?period=all"
    ).json()["items"]
    _, rows = data_table(
        screen(manager_client, f"/price-history?material_id={mid}&period=all")
    )
    assert [(r[0], r[1]) for r in rows] == [
        (x["date"], x["supplier"]["name"]) for x in api_history
    ]

    events = feed(manager_client)
    rows = all_screen_rows(manager_client, "/events")
    assert [(r[0], r[1]) for r in rows] == [
        (e["date"], KIND_TEXT[e["kind"]]) for e in events
    ]

    statuses = manager_client.get(f"{API}/supplier-update-statuses").json()["items"]
    rows = all_screen_rows(manager_client, "/supplier-update-statuses")
    assert [(r[0], r[1]) for r in rows] == [
        (s["supplier"]["name"], s["last_update_date"] or NEVER_UPDATED)
        for s in statuses
    ]
    assert ("Дельта", NEVER_UPDATED) in [(r[0], r[1]) for r in rows]

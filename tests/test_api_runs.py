"""API operations 22, 25–28 (docs/api/resources.md, section 3): update statuses,
manual run, one run, the run log, accepting a new volume.

Scenario IDs (П-…, Н-…) are from tests/contract/scenarios.json.
"""

from __future__ import annotations

import re

import pytest
from helpers import API, assert_problem, error_codes
from helpers_b2 import (
    RUN_IN_PROGRESS,
    iso_kyiv,
    item,
    items,
    kyiv,
    log_entries,
    move_to,
    row,
    start_manual,
    wait_run,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

ISO_KYIV = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+0[23]:00$")


def partial_run(world) -> dict:
    """Альфа: base 10, then a "частково" run with 7 items."""
    world.supplier("Альфа", "alfa", items("А", 10))
    world.at(2026, 10, 4)
    world.run()
    world.page("Альфа", items("А", 7))
    world.at(2026, 10, 5)
    return world.run()


# --- operation 22: GET /supplier-update-statuses -------------------------------------------


# П-24, REQ-F-034, BDD-035: the manager gets active suppliers with the date of the
# last update (РРРР-ММ-ДД) and the page fields.
def test_update_statuses_for_manager(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 5)
    world.run()
    body = manager_client.get(f"{API}/supplier-update-statuses").json()
    assert body["items"] == [
        {
            "supplier": {"id": world.supplier_ids["Альфа"], "name": "Альфа"},
            "last_update_date": "2026-10-05",
        },
        {
            "supplier": {"id": world.supplier_ids["Бета"], "name": "Бета"},
            "last_update_date": "2026-10-05",
        },
    ]
    assert (
        body["page"],
        body["page_size"],
        body["total_items"],
        body["total_pages"],
    ) == (1, 50, 2, 1)


# REQ-NF-031: the administrator gets the same statuses as the manager.
def test_update_statuses_same_for_both_roles(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.run()
    path = f"{API}/supplier-update-statuses"
    assert world.admin.get(path).json() == manager_client.get(path).json()


# REQ-F-057: page "0" is refused with page_invalid.
@pytest.mark.parametrize("path", ["/supplier-update-statuses", "/run-log-entries"])
def test_page_invalid(admin_client, path):
    body = assert_problem(
        admin_client.get(f"{API}{path}?page=0"), 422, "validation_failed"
    )
    assert error_codes(body) == [("page", "page_invalid")]


# --- operation 25: POST /runs ------------------------------------------------------------------------


# П-27, REQ-F-020, REQ-F-032: 202, the run "in_progress" with no finish time, the
# trigger manual, the starter's login and a Location header of the run.
def test_manual_run_accepted(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.hold("alfa")
    resp = world.admin.post(f"{API}/runs")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert resp.headers["location"] == f"{API}/runs/{body['id']}"
    assert (
        body["status"],
        body["finished_at"],
        body["trigger"],
        body["started_by"],
    ) == (
        "in_progress",
        None,
        "manual",
        "admin",
    )
    assert body["started_at"] == "2026-07-15T12:00:00+03:00"
    (supplier,) = body["supplier_run_statuses"]
    assert supplier["supplier"]["name"] == "Альфа"
    assert world.admin.get(resp.headers["location"]).status_code == 200
    world.sim.release()
    assert wait_run(world.admin, body["id"])["status"] == "success"


# Н-09, REQ-F-021, BDD-008: while a run is going a second request is 409
# run_in_progress "оновлення вже триває"; no new run appears in the log.
def test_manual_run_while_running(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.hold("alfa")
    first = start_manual(world.admin)
    body = assert_problem(world.admin.post(f"{API}/runs"), 409, "run_in_progress")
    assert body["detail"] == RUN_IN_PROGRESS
    world.sim.release()
    wait_run(world.admin, first["id"])
    assert [e["run"]["id"] for e in log_entries(world.admin)] == [first["id"]]
    assert world.sim.requests("alfa") == 1


# П-28, REQ-F-063: without active suppliers — 200 with the entry
# no_active_suppliers; no run is created.
def test_manual_run_without_active_suppliers(admin_client):
    resp = admin_client.post(f"{API}/runs")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["kind"], body["trigger"], body["run"], body["volume_acceptance"]) == (
        "no_active_suppliers",
        "manual",
        None,
        None,
    )
    assert body["occurred_at"] == "2026-07-15T12:00:00+03:00"
    assert "location" not in resp.headers


# REQ-NF-031: POST /runs has no body and needs no Content-Type (section 0).
def test_manual_run_needs_no_content_type(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    resp = world.admin.post(f"{API}/runs", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 202, resp.text
    wait_run(world.admin, resp.json()["id"])


# --- operation 26: GET /runs/{run_id} -------------------------------------------------------------------


# П-29, REQ-F-033: one run with the supplier rows (status, count, reason, warnings,
# the acceptance button flag).
def test_get_run(world):
    run = partial_run(world)
    body = world.admin.get(f"{API}/runs/{run['id']}").json()
    assert set(body) == {
        "id",
        "trigger",
        "started_at",
        "finished_at",
        "started_by",
        "status",
        "supplier_run_statuses",
    }
    alfa = row(body, "Альфа")
    assert set(alfa) == {
        "supplier",
        "status",
        "parsed_items_count",
        "reason_code",
        "error_reason",
        "warnings",
        "volume_acceptance_available",
    }
    assert (alfa["status"], alfa["parsed_items_count"], alfa["reason_code"]) == (
        "partial",
        7,
        None,
    )
    assert (alfa["error_reason"], alfa["warnings"]) == (None, [])
    assert alfa["volume_acceptance_available"] is True


# REQ-F-057, П-29: supplier rows of a run are ordered by supplier name.
def test_run_rows_by_supplier_name(world):
    for name, slug in (("Вега", "vega"), ("Альфа", "alfa"), ("Бета", "beta")):
        world.supplier(name, slug, [item(f"{slug}-1")])
    run = world.run()
    assert [r["supplier"]["name"] for r in run["supplier_run_statuses"]] == [
        "Альфа",
        "Бета",
        "Вега",
    ]


# REQ-NF-031: an unknown run is 404 not_found; "abc" is 422 invalid_type.
def test_get_run_errors(admin_client):
    assert_problem(admin_client.get(f"{API}/runs/999"), 404, "not_found")
    body = assert_problem(admin_client.get(f"{API}/runs/abc"), 422, "validation_failed")
    assert error_codes(body) == [("run_id", "invalid_type")]


# --- operation 27: GET /run-log-entries -------------------------------------------------------------------


# П-30, REQ-F-033: the entries have kind, occurred_at, trigger, run and
# volume_acceptance; a run entry carries the whole run.
def test_run_log_entries(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    run = world.run()
    body = world.admin.get(f"{API}/run-log-entries").json()
    (entry,) = body["items"]
    assert entry == {
        "kind": "run",
        "occurred_at": run["started_at"],
        "trigger": None,
        "run": run,
        "volume_acceptance": None,
    }
    assert (body["page"], body["total_items"]) == (1, 1)


# REQ-NF-019: run log entries are never deleted — no DELETE on the run log and
# the runs (405), the entry stays.
@pytest.mark.parametrize("path", ["/run-log-entries", "/runs/{id}"])
def test_run_log_cannot_be_deleted(world, path):
    world.supplier("Альфа", "alfa", [item("А-1")])
    run = world.run()
    resp = world.admin.delete(API + path.format(id=run["id"]))
    assert_problem(resp, 405, "method_not_allowed")
    assert len(log_entries(world.admin)) == 1


# --- operation 28: POST /volume-acceptances ------------------------------------------------------------


# П-31, REQ-F-031: 201 with id, run_id, supplier, accepted_by, accepted_at and the
# accepted count; no Location (no address of an acceptance, РА-10).
def test_accept_volume(world):
    run = partial_run(world)
    resp = world.admin.post(
        f"{API}/volume-acceptances",
        json={"run_id": run["id"], "supplier_id": world.supplier_ids["Альфа"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {
        "id",
        "run_id",
        "supplier",
        "accepted_by",
        "accepted_at",
        "volume_baseline",
    }
    assert body["supplier"] == {"id": world.supplier_ids["Альфа"], "name": "Альфа"}
    assert (body["run_id"], body["accepted_by"], body["volume_baseline"]) == (
        run["id"],
        "admin",
        7,
    )
    assert "location" not in resp.headers


# Н-15, REQ-F-031: the supplier is "успіх" in the run — 409
# volume_acceptance_unavailable; nothing is accepted.
def test_accept_volume_unavailable(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    run = world.run()
    resp = world.admin.post(
        f"{API}/volume-acceptances",
        json={"run_id": run["id"], "supplier_id": world.supplier_ids["Альфа"]},
    )
    assert_problem(resp, 409, "volume_acceptance_unavailable")
    assert [e["kind"] for e in log_entries(world.admin)] == ["run"]


# REQ-NF-031: body checks of operation 28 — required fields, unknown run or
# supplier (reference_not_found), unknown field, wrong type, malformed JSON.
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, {("run_id", "required"), ("supplier_id", "required")}),
        ({"run_id": 999, "supplier_id": "SUP"}, {("run_id", "reference_not_found")}),
        (
            {"run_id": "RUN", "supplier_id": 999},
            {("supplier_id", "reference_not_found")},
        ),
        (
            {"run_id": "RUN", "supplier_id": "SUP", "extra": 1},
            {("extra", "unknown_field")},
        ),
        ({"run_id": "x", "supplier_id": "SUP"}, {("run_id", "invalid_type")}),
    ],
)
def test_accept_volume_body_errors(world, body, expected):
    run = partial_run(world)
    sup = world.supplier_ids["Альфа"]
    body = {
        k: (run["id"] if v == "RUN" else sup if v == "SUP" else v)
        for k, v in body.items()
    }
    resp = world.admin.post(f"{API}/volume-acceptances", json=body)
    assert set(error_codes(assert_problem(resp, 422, "validation_failed"))) == expected
    assert (
        row(wait_run(world.admin, run["id"]), "Альфа")["volume_acceptance_available"]
        is True
    )


# REQ-NF-031: operation 28 — malformed JSON is 422 malformed_json; another
# Content-Type is 415.
def test_accept_volume_not_json(admin_client):
    resp = admin_client.post(
        f"{API}/volume-acceptances",
        content=b"{",
        headers={"Content-Type": "application/json"},
    )
    assert error_codes(assert_problem(resp, 422, "validation_failed")) == [
        (None, "malformed_json")
    ]
    resp = admin_client.post(
        f"{API}/volume-acceptances",
        content=b'{"run_id": 1, "supplier_id": 1}',
        headers={"Content-Type": "text/plain"},
    )
    assert_problem(resp, 415, "unsupported_media_type")


# --- 401 and 403 -----------------------------------------------------------------------------------------


OPERATIONS = [
    ("GET", "/supplier-update-statuses", None),
    ("POST", "/runs", None),
    ("GET", "/runs/1", None),
    ("GET", "/run-log-entries", None),
    ("POST", "/volume-acceptances", {"run_id": 1, "supplier_id": 1}),
]


# REQ-NF-031, REQ-F-001: without a session operations 22, 25–28 are 401.
@pytest.mark.parametrize(("method", "path", "body"), OPERATIONS)
def test_without_session_401(client, method, path, body):
    resp = client.request(method, API + path, json=body)
    assert_problem(resp, 401, "unauthenticated")


# Н-41, REQ-F-005, BDD-030: the manager's manual run is 403 "немає доступу"; the
# run did not start: no log entry, no request to the catalogue.
def test_manager_cannot_start_run(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1")])
    resp = manager_client.post(f"{API}/runs")
    assert assert_problem(resp, 403, "forbidden")["detail"] == "немає доступу"
    assert log_entries(world.admin) == []
    assert world.sim.requests("alfa") == 0


# Н-42, Н-43: the manager cannot read a run or the run log — 403, also for a run
# that does not exist.
@pytest.mark.parametrize("path", ["/runs/{id}", "/runs/999", "/run-log-entries"])
def test_manager_cannot_read_runs(world, manager_client, path):
    world.supplier("Альфа", "alfa", [item("А-1")])
    run = world.run()
    resp = manager_client.get(API + path.format(id=run["id"]))
    assert_problem(resp, 403, "forbidden")


# Н-44, REQ-F-005: the manager's acceptance is 403; the volume is not accepted —
# the button is still there and the log has no acceptance.
def test_manager_cannot_accept_volume(world, manager_client):
    run = partial_run(world)
    resp = manager_client.post(
        f"{API}/volume-acceptances",
        json={"run_id": run["id"], "supplier_id": world.supplier_ids["Альфа"]},
    )
    assert_problem(resp, 403, "forbidden")
    assert (
        row(wait_run(world.admin, run["id"]), "Альфа")["volume_acceptance_available"]
        is True
    )
    assert "volume_acceptance" not in [e["kind"] for e in log_entries(world.admin)]


# --- dates ---------------------------------------------------------------------------------------------------


# REQ-NF-031: date and time are ISO 8601 with the Kyiv offset — +03:00 in
# summer, +02:00 in winter; dates are РРРР-ММ-ДД.
@pytest.mark.parametrize(
    ("moment", "offset"),
    [(kyiv(2026, 10, 5, 10, 0), "+03:00"), (kyiv(2026, 11, 16, 10, 0), "+02:00")],
)
def test_dates_with_kyiv_offset(world, manager_client, moment, offset):
    world.supplier("Альфа", "alfa", [item("А-1")])
    move_to(world.clock, moment)
    run = wait_run(world.admin, start_manual(world.admin)["id"])
    for value in (
        run["started_at"],
        run["finished_at"],
        log_entries(world.admin)[0]["occurred_at"],
    ):
        assert ISO_KYIV.match(value) and value.endswith(offset), value
    assert run["started_at"] == iso_kyiv(moment)
    day = manager_client.get(f"{API}/supplier-update-statuses").json()["items"][0]
    assert day["last_update_date"] == run["started_at"][:10]

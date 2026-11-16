"""A-05 for block B2: action log records of runs, of the manual run and of
accepting a new volume; request ids and run ids; the technical log of supplier
errors; a failing log (REQ-NF-018, REQ-NF-032, REQ-NF-033, BDD-071).
"""

from __future__ import annotations

import pytest
from helpers import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    API,
    MANAGER_LOGIN,
    MANAGER_PASSWORD,
    api_login,
)
from helpers_b2 import (
    item,
    items,
    kyiv,
    log_entries,
    move_to,
    row,
    start_manual,
    wait_run,
    wait_until,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

COMMON = {"time", "level", "event", "login", "role", "request_id", "result"}
RUN_EVENTS = {"run_started", "supplier_status", "run_finished"}


def events(records: list[dict], event: str) -> list[dict]:
    return [r for r in records if r["event"] == event]


def http_records(records: list[dict], method: str, path: str) -> list[dict]:
    return [
        r
        for r in records
        if r["event"] == "http_request" and r["method"] == method and r["path"] == path
    ]


def run_records(records: list[dict], run_id: int) -> list[dict]:
    return [
        r for r in records if r["event"] in RUN_EVENTS and r.get("run_id") == run_id
    ]


def check_run_records(records, run: dict, request_id: str) -> None:
    """Start with the trigger, one status per supplier, finish with the overall
    status; all with the run id and the given request id."""
    found = run_records(records, run["id"])
    for record in found:
        assert COMMON <= set(record)
        assert str(record["request_id"]) == str(request_id)
        assert record["time"].endswith(("+03:00", "+02:00"))
    (started,) = events(found, "run_started")
    assert started["trigger"] == run["trigger"]
    statuses = {
        r["supplier_id"]: (r["status"], r["parsed_items_count"])
        for r in events(found, "supplier_status")
    }
    assert statuses == {
        r["supplier"]["id"]: (r["status"], r["parsed_items_count"])
        for r in run["supplier_run_statuses"]
    }
    (finished,) = events(found, "run_finished")
    assert finished["status"] == run["status"]


# --- BDD-071 ------------------------------------------------------------------------------------


# BDD-071, REQ-NF-032: admin logs in, sets the threshold 1 % -> 2 %, starts a
# manual run that finishes; the manager logs in and asks for 3 %. The action log
# has the login, "settings_update" (admin, success), the manual run and its start
# ("вручну"), each supplier's status and the finish; "access_denied" for the
# manager with the action and the object; an HTTP record for each request; one
# request id per request, different for different requests; the run records
# carry the id of the request that started the run and the run id; no test
# password in the file; the threshold is 2 %.
def test_bdd071_action_log(world, app, client_factory, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")])
    admin = client_factory(app)
    assert api_login(admin, ADMIN_LOGIN, ADMIN_PASSWORD).status_code == 201
    assert (
        admin.patch(f"{API}/settings", json={"notification_threshold": 2}).status_code
        == 200
    )
    run = wait_run(admin, start_manual(admin)["id"])
    manager = client_factory(app)
    assert api_login(manager, MANAGER_LOGIN, MANAGER_PASSWORD).status_code == 201
    assert (
        manager.patch(f"{API}/settings", json={"notification_threshold": 3}).status_code
        == 403
    )
    assert admin.get(f"{API}/settings").json()["notification_threshold"] == 2

    records = read_log(config.action_log_path)
    for record in records:
        assert COMMON <= set(record)
    logins = [
        r for r in events(records, "login_succeeded") if r["login"] == ADMIN_LOGIN
    ]
    settings = [
        r for r in events(records, "settings_update") if r["result"] == "success"
    ]
    assert settings and (settings[-1]["login"], settings[-1]["role"]) == (
        "admin",
        "admin",
    )
    assert settings[-1]["object_type"] == "settings"
    (manual,) = events(records, "manual_run")
    assert (manual["login"], manual["role"], manual["result"]) == (
        "admin",
        "admin",
        "success",
    )
    assert (manual["object_type"], manual["object_id"]) == ("run", run["id"])
    (denied,) = events(records, "access_denied")
    assert (denied["login"], denied["action"], denied["object_type"]) == (
        "manager",
        "settings_update",
        "settings",
    )

    post_runs = http_records(records, "POST", f"{API}/runs")
    (post_run,) = post_runs
    assert manual["request_id"] == post_run["request_id"]
    check_run_records(records, run, post_run["request_id"])
    assert run["trigger"] == "manual"

    patches = http_records(records, "PATCH", f"{API}/settings")
    assert [p["status"] for p in patches] == [200, 403]
    assert settings[-1]["request_id"] == patches[0]["request_id"]
    assert denied["request_id"] == patches[1]["request_id"]
    assert (
        logins[-1]["request_id"]
        == http_records(records, "POST", f"{API}/sessions")[-2]["request_id"]
    )
    for record in patches + post_runs:
        assert {"method", "path", "status", "duration_ms"} <= set(record)
    assert patches[0]["login"] == "admin" and patches[1]["login"] == "manager"
    ids = [
        r["request_id"] for r in http_records(records, "POST", f"{API}/sessions")[-2:]
    ]
    ids += [p["request_id"] for p in patches] + [post_run["request_id"]]
    assert len(set(ids)) == len(ids)

    text = config.action_log_path.read_text(encoding="utf-8")
    assert ADMIN_PASSWORD not in text and MANAGER_PASSWORD not in text


# --- records of runs -------------------------------------------------------------------------------


# REQ-NF-032: a scheduled run — start ("scheduled"), each supplier's status and
# the finish; the request id of every record is the run id.
def test_scheduled_run_records(world, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")])
    world.mode("Бета", "unavailable")
    move_to(world.clock, kyiv(2026, 10, 5, 3, 30))
    run = wait_run(world.admin, world.updates.tick())
    check_run_records(read_log(config.action_log_path), run, str(run["id"]))
    assert run["status"] == "partial"


# REQ-NF-032: the catch-up — the same records with "catch_up"; request id = run id.
def test_catch_up_records(world, restart, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    move_to(world.clock, kyiv(2026, 10, 5, 10, 0))
    app2, admin2 = restart()
    app2.state.updates.startup()
    (entry,) = log_entries(admin2)
    run = wait_run(admin2, entry["run"]["id"])
    assert run["trigger"] == "catch_up"
    check_run_records(read_log(config.action_log_path), run, str(run["id"]))


# REQ-NF-032, REQ-F-022: "пропущено" — a record with the id of its run log
# entry, which is also its request id.
def test_skipped_record(world, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.at(2026, 10, 5, 3, 25)
    world.sim.hold("alfa")
    manual = start_manual(world.admin)
    move_to(world.clock, kyiv(2026, 10, 5, 3, 30))
    assert world.updates.tick() is None
    world.sim.release()
    wait_run(world.admin, manual["id"])
    (record,) = events(read_log(config.action_log_path), "run_skipped")
    assert record["run_log_entry_id"] is not None
    assert str(record["request_id"]) == str(record["run_log_entry_id"])
    assert record["time"] == "2026-10-05T03:30:00+03:00"


# REQ-NF-032, REQ-F-063: "немає активних постачальників" at the configured time
# and after the button — records with the trigger and the entry id as request id.
def test_no_active_suppliers_records(admin_client, app, clock, config, read_log):
    move_to(clock, kyiv(2026, 10, 5, 3, 30))
    app.state.updates.tick()
    move_to(clock, kyiv(2026, 10, 5, 10, 0))
    assert admin_client.post(f"{API}/runs").status_code == 200
    records = events(read_log(config.action_log_path), "no_active_suppliers")
    assert [r["trigger"] for r in records] == ["scheduled", "manual"]
    for record in records:
        assert str(record["request_id"]) == str(record["run_log_entry_id"])
    assert records[0]["run_log_entry_id"] != records[1]["run_log_entry_id"]


# REQ-NF-032, REQ-F-024: the interrupted run gets a record with its run id after
# the start.
def test_interrupted_run_record(world, worker, restart, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.hold("alfa")
    proc = worker(kyiv(2026, 10, 5, 3, 30))
    wait_until(lambda: world.sim.requests("alfa") == 1, what="request to Альфа")
    proc.kill()
    proc.wait(timeout=10)
    world.sim.release()
    move_to(world.clock, kyiv(2026, 10, 5, 3, 35))
    app2, admin2 = restart()
    app2.state.updates.startup()
    interrupted = [
        e["run"] for e in log_entries(admin2) if e["run"]["status"] == "interrupted"
    ]
    (run,) = interrupted
    (record,) = events(read_log(config.action_log_path), "run_interrupted")
    assert record["run_id"] == run["id"]
    started = [
        r
        for r in events(read_log(config.action_log_path), "run_started")
        if r["run_id"] == run["id"]
    ]
    assert started and str(started[0]["request_id"]) == str(run["id"])


# --- actions: manual run, accepting a volume ------------------------------------------------------------


# REQ-NF-032: the manual run refused while another one is going — "manual_run"
# rejected with run_in_progress.
def test_manual_run_rejected_record(world, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.hold("alfa")
    first = start_manual(world.admin)
    assert world.admin.post(f"{API}/runs").status_code == 409
    world.sim.release()
    wait_run(world.admin, first["id"])
    manual = events(read_log(config.action_log_path), "manual_run")
    assert [(r["result"], r.get("reason_code")) for r in manual] == [
        ("success", None),
        ("rejected", "run_in_progress"),
    ]


# REQ-NF-032, REQ-F-005: the manager's manual run — one "access_denied" record
# with the action "manual_run" and no "manual_run" record.
def test_manual_run_access_denied_record(world, manager_client, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    assert manager_client.post(f"{API}/runs").status_code == 403
    records = read_log(config.action_log_path)
    (denied,) = events(records, "access_denied")
    assert (denied["login"], denied["action"], denied["object_type"]) == (
        "manager",
        "manual_run",
        "run",
    )
    assert events(records, "manual_run") == []
    assert [r for r in records if r["event"] in RUN_EVENTS] == []


# REQ-NF-032: accepting a new volume — "volume_accept" success with the
# acceptance id; refused (a run where Альфа is "успіх") — rejected with
# volume_acceptance_unavailable; the
# manager — "access_denied" with the action "volume_accept".
def test_volume_accept_records(world, manager_client, config, read_log):
    world.supplier("Альфа", "alfa", items("А", 10))
    first = world.run()
    world.page("Альфа", items("А", 7))
    world.at(2026, 10, 5)
    run = world.run()
    body = {"run_id": run["id"], "supplier_id": world.supplier_ids["Альфа"]}
    assert (
        manager_client.post(f"{API}/volume-acceptances", json=body).status_code == 403
    )
    accepted = world.admin.post(f"{API}/volume-acceptances", json=body)
    assert accepted.status_code == 201
    refused = {"run_id": first["id"], "supplier_id": world.supplier_ids["Альфа"]}
    assert (
        world.admin.post(f"{API}/volume-acceptances", json=refused).status_code == 409
    )
    records = read_log(config.action_log_path)
    (denied,) = events(records, "access_denied")
    assert (denied["action"], denied["object_type"]) == (
        "volume_accept",
        "volume_acceptance",
    )
    found = events(records, "volume_accept")
    assert [(r["result"], r.get("reason_code")) for r in found] == [
        ("success", None),
        ("rejected", "volume_acceptance_unavailable"),
    ]
    assert (found[0]["object_type"], found[0]["object_id"]) == (
        "volume_acceptance",
        accepted.json()["id"],
    )
    assert (found[0]["login"], found[0]["role"]) == ("admin", "admin")


# --- REQ-NF-018: the technical log ------------------------------------------------------------------------


def tech_records(read_log, config, run_id: int, supplier_id: int) -> list[dict]:
    return [
        r
        for r in read_log(config.technical_log_path)
        if r.get("run_id") == run_id and r.get("supplier_id") == supplier_id
    ]


# REQ-NF-018: a manual run with an unparsable page — the technical log has a
# record with the time, the supplier and the error description, the run id and
# the request id of the request that started the run.
def test_unparsable_page_in_technical_log(world, config, read_log):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.mode("Альфа", "broken")
    run = wait_run(world.admin, start_manual(world.admin)["id"])
    assert row(run, "Альфа")["reason_code"] == "unparsable"
    (record,) = tech_records(read_log, config, run["id"], world.supplier_ids["Альфа"])
    assert COMMON <= set(record)
    assert record["time"] and isinstance(record["error"], str) and record["error"]
    (post_run,) = http_records(read_log(config.action_log_path), "POST", f"{API}/runs")
    assert record["request_id"] == post_run["request_id"]


# REQ-NF-018, BDD-003: a scheduled run with a page that did not answer in time —
# a technical log record with the supplier and the description; the request id
# is the run id.
def test_timeout_in_technical_log(
    world, update_fetch_module, monkeypatch, config, read_log
):
    monkeypatch.setattr(update_fetch_module, "FETCH_TIMEOUT_SECONDS", 1)
    world.supplier("Вега", "vega", [item("В-1")])
    world.mode("Вега", "slow", delay_seconds=2)
    move_to(world.clock, kyiv(2026, 10, 5, 3, 30))
    run = wait_run(world.admin, world.updates.tick())
    assert row(run, "Вега")["reason_code"] == "timeout"
    (record,) = tech_records(read_log, config, run["id"], world.supplier_ids["Вега"])
    assert str(record["request_id"]) == str(run["id"])
    assert record["error"]


# --- REQ-NF-033: a log that cannot be written -------------------------------------------------------------


# REQ-NF-033: the technical log cannot be written (its path is a directory); the
# manual run with an unparsable page starts with the same answer as without the
# failure (202, Location, the run "in_progress") and the supplier is "помилка".
def test_manual_run_with_broken_technical_log(
    sim, spm_app_module, config_factory, clock, client_factory, accounts, tmp_path
):
    broken = tmp_path / "technical-log-dir"
    broken.mkdir()
    cfg = config_factory(technical_log_path=broken)
    app = spm_app_module.create_app(cfg, clock=clock)
    admin = client_factory(app)
    assert api_login(admin, ADMIN_LOGIN, ADMIN_PASSWORD).status_code == 201
    sim.put("alfa", [item("А-1")], mode="broken")
    resp = admin.post(
        f"{API}/suppliers",
        json={
            "name": "Альфа",
            "catalog_url": sim.url("alfa"),
            "parser": "table_layout",
            "active": True,
        },
    )
    assert resp.status_code == 201
    started = admin.post(f"{API}/runs")
    assert started.status_code == 202
    body = started.json()
    assert started.headers["location"] == f"{API}/runs/{body['id']}"
    assert (body["status"], body["finished_at"], body["started_by"]) == (
        "in_progress",
        None,
        "admin",
    )
    run = wait_run(admin, body["id"])
    assert (row(run, "Альфа")["status"], row(run, "Альфа")["reason_code"]) == (
        "error",
        "unparsable",
    )


# REQ-NF-033: the action log cannot be written; the manual run still starts (202)
# and finishes with the supplier "успіх".
def test_manual_run_with_broken_action_log(
    sim, spm_app_module, config_factory, clock, client_factory, accounts, tmp_path
):
    broken = tmp_path / "action-log-dir"
    broken.mkdir()
    app = spm_app_module.create_app(config_factory(action_log_path=broken), clock=clock)
    admin = client_factory(app)
    assert api_login(admin, ADMIN_LOGIN, ADMIN_PASSWORD).status_code == 201
    sim.put("alfa", [item("А-1")])
    admin.post(
        f"{API}/suppliers",
        json={
            "name": "Альфа",
            "catalog_url": sim.url("alfa"),
            "parser": "table_layout",
            "active": True,
        },
    )
    started = admin.post(f"{API}/runs")
    assert started.status_code == 202
    assert row(wait_run(admin, started.json()["id"]), "Альфа")["status"] == "success"

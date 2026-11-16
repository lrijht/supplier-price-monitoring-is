"""T-20 with addendum A-04: statuses, volume base, accepting a new volume, the
run log, "no active suppliers", the last update date, the run in progress.

Runs from code (T-19); the stopped process for "не завершено" is a killed
worker process (the mechanism of T-21).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from helpers import API, assert_problem
from helpers_b2 import (
    item,
    items,
    kyiv,
    latest_run,
    log_entries,
    move_to,
    parse_dt,
    row,
    runs_in_log,
    start_manual,
    supplier_written,
    update_statuses,
    wait_run,
    wait_until,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")


def next_day(world) -> None:
    world.clock.advance(timedelta(days=1))


def accept(client, run: dict, supplier_id: int):
    return client.post(
        f"{API}/volume-acceptances",
        json={"run_id": run["id"], "supplier_id": supplier_id},
    )


def runs_with(world, counts: list[int], total: int = 120) -> list[str]:
    """Supplier Альфа; one run a day with the first ``n`` of ``total`` items."""
    page = items("А", total)
    world.supplier("Альфа", "alfa", page[: counts[0]])
    statuses = []
    for n in counts:
        world.page("Альфа", page[:n])
        next_day(world)
        statuses.append(row(world.run(), "Альфа")["status"])
    return statuses


# --- REQ-F-030, REQ-F-052: statuses and the volume base ------------------------------------


# REQ-F-030, BDD-006: for base 100, 79 parsed items give "частково" and their 79
# daily prices are written; 80 give "успіх".
@pytest.mark.parametrize(("parsed", "status"), [(79, "partial"), (80, "success")])
def test_incomplete_crawl_threshold(world, parsed, status):
    assert runs_with(world, [100, parsed], total=100) == ["success", status]


# REQ-F-030: in a "частково" run the prices of the parsed items are written.
def test_partial_run_writes_prices(world):
    page = items("А", 100)
    world.supplier("Альфа", "alfa", page)
    world.at(2026, 10, 1)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    world.page("Альфа", page[:79], mode="reduced", keep_items=79)
    world.at(2026, 10, 2)
    assert row(world.run(), "Альфа")["status"] == "partial"
    assert world.price_on("А-1", kyiv(2026, 10, 2).date()) is not None


# REQ-F-052, BDD-046: runs with 100, 120, 100, 85 and 69 items give "успіх" (base
# 100), "успіх" (base 120), "успіх" (83 % of 120), "частково" (71 %), "частково".
def test_volume_base_grows_never_drops(world):
    statuses = runs_with(world, [100, 120, 100, 85, 69])
    assert statuses == ["success", "success", "success", "partial", "partial"]


# REQ-F-052: for base 100, 85 items give "успіх" and the base stays 100; the
# next run with 69 items gives "частково".
def test_volume_base_stays_after_smaller_success(world):
    assert runs_with(world, [100, 85, 69]) == ["success", "success", "partial"]


# REQ-F-052: a run with status "помилка" creates no base — the first successful
# run after it sets the base (here 10, so 7 then is "частково").
def test_error_run_creates_no_base(world):
    world.supplier("Альфа", "alfa", items("А", 10))
    world.mode("Альфа", "unavailable")
    assert row(world.run(), "Альфа")["status"] == "error"
    world.mode("Альфа", "normal")
    next_day(world)
    assert row(world.run(), "Альфа")["status"] == "success"
    world.page("Альфа", items("А", 7))
    next_day(world)
    assert row(world.run(), "Альфа")["status"] == "partial"


# --- REQ-F-031: accepting a new volume -----------------------------------------------------------


def partial_runs(world, days: list[int]) -> list[dict]:
    """Base 100 on 2026-10-01, then a 70-item "частково" run on each day."""
    page = items("А", 100)
    world.supplier("Альфа", "alfa", page)
    world.at(2026, 10, 1)
    world.run()
    world.page("Альфа", page[:70])
    runs = []
    for day in days:
        world.at(2026, 10, day)
        runs.append(world.run())
    return runs


# REQ-F-031: "частково" on 2026-10-04 and 2026-10-05 — the button is only in
# Альфа's row of the 2026-10-05 run; accepting the 2026-10-04 run is refused.
def test_accept_button_only_in_last_partial_run(world):
    run04, run05 = partial_runs(world, [4, 5])
    run04, run05 = (
        wait_run(world.admin, run04["id"]),
        wait_run(world.admin, run05["id"]),
    )
    assert row(run04, "Альфа")["volume_acceptance_available"] is False
    assert row(run05, "Альфа")["volume_acceptance_available"] is True
    resp = accept(world.admin, run04, world.supplier_ids["Альфа"])
    assert_problem(resp, 409, "volume_acceptance_unavailable")


# REQ-F-031, BDD-007: accepting — the log records the administrator's login,
# the time and the accepted count 70; the next run with 70 items is "успіх".
def test_accept_new_volume(world):
    (run05,) = partial_runs(world, [5])
    world.at(2026, 10, 5, 9, 15)
    resp = accept(world.admin, run05, world.supplier_ids["Альфа"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["accepted_by"], body["volume_baseline"], body["run_id"]) == (
        "admin",
        70,
        run05["id"],
    )
    assert body["accepted_at"] == "2026-10-05T09:15:00+03:00"
    (entry,) = [e for e in log_entries(world.admin) if e["kind"] == "volume_acceptance"]
    assert entry["volume_acceptance"] == body
    assert entry["occurred_at"] == body["accepted_at"]
    world.at(2026, 10, 6)
    assert row(world.run(), "Альфа")["status"] == "success"


# REQ-F-031: without accepting, Альфа stays "частково" in every next run with
# the same count; there is no automatic switch to the new base.
def test_no_automatic_new_volume(world):
    runs = partial_runs(world, [4, 5, 6, 7])
    assert [row(r, "Альфа")["status"] for r in runs] == ["partial"] * 4


# REQ-F-031: "частково" on 2026-10-05, "помилка" on 2026-10-06 — no button any
# more, and accepting the 2026-10-05 run is refused.
def test_error_after_partial_removes_button(world):
    (run05,) = partial_runs(world, [5])
    world.mode("Альфа", "unavailable")
    world.at(2026, 10, 6)
    run06 = world.run()
    assert row(run06, "Альфа")["volume_acceptance_available"] is False
    run05 = wait_run(world.admin, run05["id"])
    assert row(run05, "Альфа")["volume_acceptance_available"] is False
    assert_problem(
        accept(world.admin, run05, world.supplier_ids["Альфа"]),
        409,
        "volume_acceptance_unavailable",
    )


# REQ-F-031: "частково" on 2026-10-05, then "не завершено" in the run of
# 2026-10-06 interrupted by a stop of the process — no button.
def test_not_finished_after_partial_removes_button(world, worker, restart):
    world.supplier("Бета", "beta", [item("Б-1")])
    (run05,) = partial_runs(world, [5])
    world.sim.hold("alfa")
    moment = kyiv(2026, 10, 6)
    proc = worker(moment)
    wait_until(lambda: world.sim.requests("alfa") == 3, what="request to Альфа")
    proc.kill()
    proc.wait(timeout=10)
    world.sim.release()
    move_to(world.clock, moment + timedelta(minutes=5))
    app2, admin2 = restart()
    app2.state.updates.startup()
    interrupted = [r for r in runs_in_log(admin2) if r["status"] == "interrupted"]
    (run06,) = interrupted
    assert row(run06, "Альфа")["status"] == "not_finished"
    run05 = wait_run(admin2, run05["id"])
    assert row(run05, "Альфа")["volume_acceptance_available"] is False


# --- REQ-F-032: the overall status ------------------------------------------------------------------


# REQ-F-032: "успіх, успіх, успіх" -> "успіх"; "успіх, помилка, успіх" ->
# "частково"; "успіх, частково, успіх" -> "частково"; "помилка ×3" -> "помилка".
@pytest.mark.parametrize(
    ("beta", "all_down", "expected"),
    [
        ("normal", False, "success"),
        ("unavailable", False, "partial"),
        ("reduced", False, "partial"),
        ("normal", True, "error"),
    ],
)
def test_overall_status(world, beta, all_down, expected):
    for name, slug in (("Альфа", "alfa"), ("Бета", "beta"), ("Вега", "vega")):
        world.supplier(name, slug, items(slug, 10))
    world.run()
    if beta == "reduced":
        world.mode("Бета", "reduced", keep_items=5)
    else:
        world.mode("Бета", beta)
    if all_down:
        for name in ("Альфа", "Бета", "Вега"):
            world.mode(name, "unavailable")
    next_day(world)
    run = world.run()
    expected_beta = {"normal": "success", "unavailable": "error", "reduced": "partial"}
    if not all_down:
        assert row(run, "Бета")["status"] == expected_beta[beta]
    assert run["status"] == expected


# REQ-F-032: a finished run has a finish time; the trigger is as started.
def test_finished_run_fields(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.at(2026, 10, 5, 3, 30, 5)
    run = world.run()
    assert run["trigger"] == "scheduled"
    assert run["started_at"] == "2026-10-05T03:30:05+03:00"
    assert parse_dt(run["finished_at"]) >= parse_dt(run["started_at"])
    assert run["started_by"] is None


# --- REQ-F-033, REQ-NF-019: the run log --------------------------------------------------------------


# REQ-F-033: after a manual run with one supplier "помилка" the log has the run
# with every field: start and finish, trigger "вручну", the starter's login, the
# overall status, and per supplier the status, the count (null for "помилка")
# and the error text.
def test_log_entry_has_every_field(world):
    world.supplier("Альфа", "alfa", items("А", 3))
    world.supplier("Бета", "beta", [item("Б-1")])
    world.mode("Бета", "unavailable")
    world.at(2026, 10, 5, 10, 0)
    run = wait_run(world.admin, start_manual(world.admin)["id"])
    (entry,) = log_entries(world.admin)
    assert entry["kind"] == "run" and entry["run"] == run
    assert entry["occurred_at"] == run["started_at"] == "2026-10-05T10:00:00+03:00"
    assert (run["trigger"], run["started_by"], run["status"]) == (
        "manual",
        "admin",
        "partial",
    )
    assert run["finished_at"] is not None
    alfa, beta = run["supplier_run_statuses"]
    assert (alfa["supplier"]["name"], alfa["status"], alfa["parsed_items_count"]) == (
        "Альфа",
        "success",
        3,
    )
    assert (beta["status"], beta["parsed_items_count"]) == ("error", None)
    assert beta["error_reason"] == "сторінка недоступна"


# REQ-F-057, REQ-NF-019: 120 log entries — pages of 50, 50 and 20, newest first;
# every entry from the first is kept.
def test_log_pages_newest_first(world):
    for _ in range(120):
        resp = world.admin.post(f"{API}/runs")
        assert resp.status_code == 200, resp.text
        world.clock.advance(timedelta(minutes=1))
    pages = [
        world.admin.get(f"{API}/run-log-entries?page={n}").json() for n in (1, 2, 3)
    ]
    assert [len(p["items"]) for p in pages] == [50, 50, 20]
    assert pages[0]["total_items"] == 120 and pages[0]["total_pages"] == 3
    times = [parse_dt(e["occurred_at"]) for p in pages for e in p["items"]]
    assert times == sorted(times, reverse=True)
    assert len(set(times)) == 120


# REQ-F-063: all suppliers deactivated — the manual button gives the entry
# "немає активних постачальників" (trigger manual) and no run with a status.
def test_no_active_suppliers_manual(world):
    world.supplier("Альфа", "alfa", [item("А-1")], active=False)
    world.at(2026, 10, 5, 10, 0)
    resp = world.admin.post(f"{API}/runs")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "kind": "no_active_suppliers",
        "occurred_at": "2026-10-05T10:00:00+03:00",
        "trigger": "manual",
        "run": None,
        "volume_acceptance": None,
    }
    assert [e["kind"] for e in log_entries(world.admin)] == ["no_active_suppliers"]
    assert world.sim.requests("alfa") == 0


# REQ-F-063: at the configured time with no active supplier the log gets the
# entry with trigger scheduled and no run.
def test_no_active_suppliers_at_scheduled_time(world):
    world.supplier("Альфа", "alfa", [item("А-1")], active=False)
    world.at(2026, 10, 5, 3, 29, 59)
    world.updates.tick()
    world.at(2026, 10, 5, 3, 30, 0)
    assert world.updates.tick() is None
    (entry,) = log_entries(world.admin)
    assert (entry["kind"], entry["trigger"], entry["run"]) == (
        "no_active_suppliers",
        "scheduled",
        None,
    )
    assert entry["occurred_at"] == "2026-10-05T03:30:00+03:00"


# --- REQ-F-034, BDD-035, BDD-039: the last update date ----------------------------------------------


# REQ-F-034: a new supplier has "ще не оновлювався" (null); a deactivated one is
# not on the screen.
def test_new_supplier_never_updated(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")], active=False)
    assert update_statuses(manager_client) == {"Альфа": None}


# REQ-F-034, BDD-035: "успіх" 2026-10-03, "частково" 2026-10-04, "помилка"
# 2026-10-05, the run of 2026-10-06 interrupted before Альфа's data — the
# screen shows 2026-10-04.
def test_last_update_counts_partial_not_error(world, manager_client, worker):
    page = items("А", 10)
    world.supplier("Альфа", "alfa", page)
    world.at(2026, 10, 3)
    world.run()
    world.page("Альфа", page[:5])
    world.at(2026, 10, 4)
    assert row(world.run(), "Альфа")["status"] == "partial"
    world.mode("Альфа", "unavailable")
    world.at(2026, 10, 5)
    world.run()
    assert update_statuses(manager_client) == {"Альфа": "2026-10-04"}
    world.mode("Альфа", "normal")
    world.sim.hold("alfa")
    proc = worker(kyiv(2026, 10, 6))
    wait_until(lambda: world.sim.requests("alfa") == 4, what="request to Альфа")
    proc.kill()
    proc.wait(timeout=10)
    world.sim.release()
    assert update_statuses(manager_client) == {"Альфа": "2026-10-04"}


# REQ-F-034, BDD-039: if Альфа's data was written in the run of 2026-10-06
# interrupted later, the screen shows 2026-10-06.
def test_last_update_counts_interrupted_run_with_data(
    world, manager_client, worker, restart
):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 3)
    world.run()
    world.sim.hold("beta")
    proc = worker(kyiv(2026, 10, 6))
    wait_until(supplier_written(world.admin, "Альфа"), what="Альфа's data")
    proc.kill()
    proc.wait(timeout=10)
    world.sim.release()
    move_to(world.clock, kyiv(2026, 10, 6, 3, 35))
    app2, _ = restart()
    app2.state.updates.startup()
    assert update_statuses(manager_client)["Альфа"] == "2026-10-06"


# REQ-F-057, П-4: the screen lists active suppliers by name in the alphabet of
# REQ-F-057 ("2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак",
# "Alpha"), 50 per page.
def test_update_statuses_order_and_pages(world, manager_client):
    names = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
    for n, name in enumerate(names):
        world.supplier(name, f"s{n}", [item(f"S{n}-1")])
    rows = manager_client.get(f"{API}/supplier-update-statuses").json()["items"]
    assert [r["supplier"]["name"] for r in rows] == [
        "2 Плита",
        "Альфа",
        "бета",
        "Гама",
        "Ґанок",
        "Іскра",
        "Їжак",
        "Alpha",
    ]
    for n in range(112):
        world.supplier(f"Постачальник {n:03d}", f"p{n}", [item(f"P{n}-1")])
    pages = [
        manager_client.get(f"{API}/supplier-update-statuses?page={p}").json()
        for p in (1, 2, 3)
    ]
    assert [len(p["items"]) for p in pages] == [50, 50, 20]


# --- A-04 to T-20, BDD-069: the run in progress -------------------------------------------------------


# REQ-F-032, REQ-F-033, REQ-F-034, BDD-069: a manual run started at 10:00:00;
# Альфа's data is written ("успіх"), Бета's not yet. The log shows the run at
# once with "триває", start 10:00:00 and no finish; Альфа's row "успіх", Бета's
# status and count empty; the manager sees 2026-10-07 for Альфа.
def test_run_in_progress_in_log(world, manager_client):
    world.supplier("Альфа", "alfa", items("А", 2))
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 7, 10, 0, 0)
    world.sim.hold("beta")
    run_id = start_manual(world.admin)["id"]
    run = wait_until(supplier_written(world.admin, "Альфа"), what="Альфа's data")
    assert run["id"] == run_id
    (entry,) = log_entries(world.admin)
    assert entry["occurred_at"] == "2026-10-07T10:00:00+03:00"
    assert (run["status"], run["finished_at"]) == ("in_progress", None)
    assert (row(run, "Альфа")["status"], row(run, "Альфа")["parsed_items_count"]) == (
        "success",
        2,
    )
    beta = row(run, "Бета")
    assert (beta["status"], beta["parsed_items_count"]) == (None, None)
    assert update_statuses(manager_client)["Альфа"] == "2026-10-07"
    world.sim.release()
    assert wait_run(world.admin, run_id)["status"] == "success"


# REQ-F-033: the run is in the log right after its start, before any supplier
# data is written: "триває", no finish, every row without status.
def test_run_in_log_right_after_start(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.hold("alfa")
    started = start_manual(world.admin)
    run = latest_run(world.admin)
    assert run["id"] == started["id"]
    assert (run["status"], run["finished_at"]) == ("in_progress", None)
    assert row(run, "Альфа")["status"] is None
    world.sim.release()
    wait_run(world.admin, started["id"])

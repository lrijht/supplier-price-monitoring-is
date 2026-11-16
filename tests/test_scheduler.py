"""T-21 with addendum A-04: scheduler, manual run, catch-up, interrupted run.

The scheduler is driven by the controlled clock without real waiting: the test
moves the clock and calls ``app.state.updates.tick()`` — one check of the
scheduler at the clock's moment. ``startup()`` is what the system does right
after it starts. A stop of the process is a killed worker process
(``tests/update_worker.py``); a start is a new application on the same data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from helpers import API
from helpers_b2 import (
    item,
    kyiv,
    log_entries,
    move_to,
    parse_dt,
    row,
    runs_in_log,
    start_manual,
    supplier_written,
    wait_run,
    wait_until,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")


def suppliers(world) -> None:
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00"), item("А-2")])
    world.supplier("Бета", "beta", [item("Б-1")])


def tick_at(world, *moment, fold: int = 0):
    move_to(world.clock, kyiv(*moment, fold=fold))
    return world.updates.tick()


def runs(client, trigger: str | None = None) -> list[dict]:
    """Runs in the log, oldest first."""
    found = list(reversed(runs_in_log(client)))
    return [r for r in found if trigger is None or r["trigger"] == trigger]


def kyiv_day(run: dict) -> date:
    return parse_dt(run["started_at"]).date()


def stop_during(world, worker, moment, *, hold: str, written: str | None = None, **kw):
    """Start a run in a worker process, wait until it reaches the held page of
    ``hold`` (and, if given, until ``written`` has its data), then kill it."""
    slug = world.slugs[hold]
    before = world.sim.requests(slug)
    world.sim.hold(slug)
    proc = worker(moment, **kw)
    wait_until(lambda: world.sim.requests(slug) > before, what=f"request to {hold}")
    if written:
        wait_until(supplier_written(world.admin, written), what=f"{written}'s data")
    proc.kill()
    proc.wait(timeout=10)
    world.sim.release()


def start_again(restart, world, *moment):
    """The system starts at the moment; returns the new admin client."""
    move_to(world.clock, kyiv(*moment))
    app2, admin2 = restart()
    app2.state.updates.startup()
    return app2, admin2


# --- REQ-F-018: the run on schedule --------------------------------------------------------


# REQ-F-018, BDD-001: with the default settings the run "за розкладом" starts
# not before 03:30 and not after 03:31 Kyiv time; only once that day.
def test_scheduled_run_at_0330(world):
    suppliers(world)
    assert tick_at(world, 2026, 10, 5, 3, 29, 59) is None
    assert log_entries(world.admin) == []
    run_id = tick_at(world, 2026, 10, 5, 3, 30, 0)
    run = wait_run(world.admin, run_id)
    assert (run["trigger"], run["status"]) == ("scheduled", "success")
    assert run["started_at"] == "2026-10-05T03:30:00+03:00"
    assert tick_at(world, 2026, 10, 5, 3, 30, 40) is None
    assert tick_at(world, 2026, 10, 5, 12, 0) is None
    assert len(runs(world.admin)) == 1


# REQ-F-018: after the time is changed to 05:00 the next scheduled run starts
# within 05:00–05:01.
def test_scheduled_run_at_changed_time(world):
    suppliers(world)
    move_to(world.clock, kyiv(2026, 10, 4, 12, 0))
    world.settings(update_time="05:00")
    assert tick_at(world, 2026, 10, 5, 3, 30) is None
    assert tick_at(world, 2026, 10, 5, 4, 59, 59) is None
    run = wait_run(world.admin, tick_at(world, 2026, 10, 5, 5, 0, 30))
    assert run["started_at"] == "2026-10-05T05:00:30+03:00"


# --- REQ-F-054, BDD-047: summer time -------------------------------------------------------------


# REQ-F-054, BDD-047: on the spring day (2027-03-28, 03:00 -> 04:00) 03:30 does
# not exist; the scheduled run starts within 04:00–04:01.
def test_spring_forward_day(world):
    suppliers(world)
    assert tick_at(world, 2027, 3, 28, 2, 59, 59) is None
    run = wait_run(world.admin, tick_at(world, 2027, 3, 28, 4, 0, 0))
    assert run["started_at"] == "2027-03-28T04:00:00+03:00"
    assert tick_at(world, 2027, 3, 28, 4, 30) is None


# REQ-F-054, BDD-047: on the autumn day (2026-10-25, 04:00 -> 03:00) 03:30
# comes twice; the log of the day has exactly one scheduled run.
def test_fall_back_day(world):
    suppliers(world)
    first = tick_at(world, 2026, 10, 25, 3, 30, 0, fold=0)
    assert first is not None
    assert wait_run(world.admin, first)["started_at"] == "2026-10-25T03:30:00+03:00"
    assert tick_at(world, 2026, 10, 25, 3, 59, 0, fold=0) is None
    assert tick_at(world, 2026, 10, 25, 3, 30, 0, fold=1) is None
    assert tick_at(world, 2026, 10, 25, 3, 31, 0, fold=1) is None
    assert tick_at(world, 2026, 10, 25, 12, 0) is None
    day_runs = [
        r for r in runs(world.admin, "scheduled") if kyiv_day(r) == date(2026, 10, 25)
    ]
    assert len(day_runs) == 1


# --- REQ-F-055: one scheduled run a day ------------------------------------------------------------


# REQ-F-055, BDD-054: 03:30 run done; at 04:00 the time is changed to 05:00 —
# no run at 05:00 that day; the next day the run starts at 05:00.
def test_time_change_after_todays_run(world):
    suppliers(world)
    assert tick_at(world, 2026, 10, 5, 3, 30) is not None
    move_to(world.clock, kyiv(2026, 10, 5, 4, 0))
    world.settings(update_time="05:00")
    assert tick_at(world, 2026, 10, 5, 5, 0) is None
    assert tick_at(world, 2026, 10, 6, 3, 30) is None
    run = wait_run(world.admin, tick_at(world, 2026, 10, 6, 5, 0))
    assert run["started_at"] == "2026-10-06T05:00:00+03:00"


# REQ-F-055: at 02:00 the time is changed 03:30 -> 05:00; that day the scheduled
# run starts at 05:00.
def test_time_change_before_todays_run(world):
    suppliers(world)
    move_to(world.clock, kyiv(2026, 10, 5, 2, 0))
    world.settings(update_time="05:00")
    assert tick_at(world, 2026, 10, 5, 3, 30) is None
    assert tick_at(world, 2026, 10, 5, 5, 0) is not None


# REQ-F-055, BDD-061: at 02:00 the time is changed 03:30 -> 01:00 (already
# past) — no scheduled run that day, no catch-up after a restart at 02:30; the
# next day the run starts at 01:00.
def test_time_changed_to_past_time(world, restart):
    suppliers(world)
    move_to(world.clock, kyiv(2026, 10, 5, 2, 0))
    world.settings(update_time="01:00")
    assert tick_at(world, 2026, 10, 5, 2, 0, 30) is None
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 2, 30)
    assert runs(admin2) == []
    for moment in ((2, 30, 30), (3, 30, 0), (23, 59, 0)):
        move_to(world.clock, kyiv(2026, 10, 5, *moment))
        assert app2.state.updates.tick() is None
    move_to(world.clock, kyiv(2026, 10, 6, 0, 59))
    assert app2.state.updates.tick() is None
    move_to(world.clock, kyiv(2026, 10, 6, 1, 0))
    run = wait_run(admin2, app2.state.updates.tick())
    assert run["started_at"] == "2026-10-06T01:00:00+03:00"


# REQ-F-055: a manual run at 02:00 does not cancel the scheduled run at 03:30.
def test_manual_run_does_not_cancel_scheduled(world):
    suppliers(world)
    world.at(2026, 10, 5, 2, 0)
    world.run("manual")
    assert tick_at(world, 2026, 10, 5, 3, 30) is not None
    assert [r["trigger"] for r in runs(world.admin)] == ["manual", "scheduled"]


# REQ-F-055, REQ-F-063: "немає активних постачальників" after the manual button
# does not count as the scheduled run; at the configured time the day gets its
# own entry, which does count: no run later that day.
def test_manual_no_active_entry_does_not_count(world):
    world.supplier("Альфа", "alfa", [item("А-1")], active=False)
    world.at(2026, 10, 5, 2, 0)
    assert world.admin.post(f"{API}/runs").status_code == 200
    assert tick_at(world, 2026, 10, 5, 3, 30) is None
    triggers = [(e["kind"], e["trigger"]) for e in reversed(log_entries(world.admin))]
    assert triggers == [
        ("no_active_suppliers", "manual"),
        ("no_active_suppliers", "scheduled"),
    ]
    world.set_active("Альфа", True)
    assert tick_at(world, 2026, 10, 5, 3, 31) is None
    assert runs(world.admin) == []


# REQ-F-022, REQ-F-055, BDD-009, BDD-059: a manual run started at 03:25 is
# still going at 03:30 — no second run starts and the log has "пропущено: оновлення
# вже триває" at 03:30. Restarted at 10:00: no catch-up, no scheduled run that
# day; the next day the run starts at 03:30.
def test_skipped_counts_as_scheduled(world, restart):
    suppliers(world)
    world.at(2026, 10, 5, 3, 25)
    world.sim.hold("alfa")
    manual = start_manual(world.admin)
    assert tick_at(world, 2026, 10, 5, 3, 30, 0) is None
    world.sim.release()
    wait_run(world.admin, manual["id"])
    kinds = [(e["kind"], e["occurred_at"]) for e in reversed(log_entries(world.admin))]
    assert kinds == [
        ("run", "2026-10-05T03:25:00+03:00"),
        ("skipped", "2026-10-05T03:30:00+03:00"),
    ]
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 10, 0)
    assert len(runs(admin2)) == 1
    assert app2.state.updates.tick() is None
    move_to(world.clock, kyiv(2026, 10, 6, 3, 30))
    assert app2.state.updates.tick() is not None


# REQ-F-055, REQ-F-063: "немає активних постачальників" at 03:30; after a restart
# at 10:00 there is no catch-up and no scheduled run that day.
def test_no_active_at_scheduled_time_counts(world, restart):
    world.supplier("Альфа", "alfa", [item("А-1")], active=False)
    assert tick_at(world, 2026, 10, 5, 3, 30) is None
    world.set_active("Альфа", True)
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 10, 0)
    assert app2.state.updates.tick() is None
    assert runs(admin2) == []


# --- REQ-F-023: catch-up ------------------------------------------------------------------------------


# REQ-F-023: the system was off at 03:30 and starts at 08:00 — right after the
# start the log has a run "доганяння".
def test_catch_up_after_missed_time(world, restart):
    suppliers(world)
    assert tick_at(world, 2026, 10, 4, 3, 30) is not None
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 8, 0)
    last = runs(admin2)[-1]
    assert (last["trigger"], last["started_at"]) == (
        "catch_up",
        "2026-10-05T08:00:00+03:00",
    )
    assert wait_run(admin2, last["id"])["status"] == "success"


# REQ-F-023, BDD-012: off from 2026-10-01 to 2026-10-04 (four scheduled runs
# missed), started 2026-10-04 at 10:00 — exactly one catch-up, prices dated
# 2026-10-04; it replaces the scheduled run of the day.
def test_catch_up_once_after_days_off(world, restart):
    world.supplier("Альфа", "alfa", [item("А-1", "1000.00")])
    world.at(2026, 9, 30)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    world.at(2026, 9, 30, 12, 0)
    world.run("manual")
    app2, admin2 = start_again(restart, world, 2026, 10, 4, 10, 0)
    catch_ups = runs(admin2, "catch_up")
    assert len(catch_ups) == 1
    assert [p.price_date for p in world.prices("А-1")] == [
        date(2026, 9, 30),
        date(2026, 10, 4),
    ]
    assert app2.state.updates.tick() is None
    assert len(runs(admin2)) == 3


# REQ-F-023: a new system is started for the first time at 10:00 with the
# update time 03:30 — right after the start a catch-up runs.
def test_catch_up_on_first_start(world, restart):
    suppliers(world)
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 10, 0)
    assert [r["trigger"] for r in runs(admin2)] == ["catch_up"]


# REQ-F-023: started at 02:00, the last run not interrupted — no catch-up; the
# scheduled run at 03:30.
def test_no_catch_up_before_time(world, restart):
    suppliers(world)
    assert tick_at(world, 2026, 10, 4, 3, 30) is not None
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 2, 0)
    assert len(runs(admin2)) == 1
    move_to(world.clock, kyiv(2026, 10, 5, 3, 30))
    assert app2.state.updates.tick() is not None
    assert [r["trigger"] for r in runs(admin2)] == ["scheduled", "scheduled"]


# REQ-F-055: off at 03:00, started at 04:00 — after the catch-up for condition
# (a) there is no scheduled run that day.
def test_catch_up_replaces_scheduled_run(world, restart):
    suppliers(world)
    assert tick_at(world, 2026, 10, 4, 3, 30) is not None
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 4, 0)
    for moment in ((4, 0, 30), (5, 0, 0), (23, 59, 0)):
        move_to(world.clock, kyiv(2026, 10, 5, *moment))
        assert app2.state.updates.tick() is None
    assert [r["trigger"] for r in runs(admin2)] == ["scheduled", "catch_up"]


# --- REQ-F-024: interrupted run -----------------------------------------------------------------------


# REQ-F-024, REQ-F-032, BDD-011, BDD-039, A-04 to T-21: the scheduled run of
# 2026-10-06 is "триває"; the process stops after Альфа's data ("успіх") and
# before Бета's. Started again the same day: the run is "перервано" with Альфа
# "успіх" and Бета "не завершено"; a catch-up runs right after the start, and
# each Альфа item has one daily price of 2026-10-06 — written by the catch-up.
def test_interrupted_run_and_catch_up(world, worker, restart):
    suppliers(world)
    world.at(2026, 10, 1)
    world.run()
    world.material("М1")
    world.link("А-1", "М1")
    stop_during(
        world, worker, kyiv(2026, 10, 6, 3, 30, 2), hold="Бета", written="Альфа"
    )
    before = runs(world.admin)[-1]
    assert (before["status"], before["finished_at"]) == ("in_progress", None)
    assert world.price_on("А-1", date(2026, 10, 6)).price == Decimal("1000.00")

    world.page("Альфа", [item("А-1", "1010.00"), item("А-2")])
    app2, admin2 = start_again(restart, world, 2026, 10, 6, 3, 40)
    interrupted, catch_up = runs(admin2)[-2:]
    assert interrupted["id"] == before["id"]
    assert (interrupted["status"], interrupted["finished_at"]) == ("interrupted", None)
    assert row(interrupted, "Альфа")["status"] == "success"
    beta = row(interrupted, "Бета")
    assert (beta["status"], beta["parsed_items_count"]) == ("not_finished", None)
    assert catch_up["trigger"] == "catch_up"
    assert wait_run(admin2, catch_up["id"])["status"] == "success"
    price = world.price_on("А-1", date(2026, 10, 6))
    assert price.price == Decimal("1010.00")


# BDD-066: the scheduled run started 2026-10-06 at 03:30:02; Альфа "успіх",
# Бета "помилка", Вега not written yet when the process stops. After the start
# the interrupted run has start 03:30:02 and no finish; Бета's count is empty;
# Вега is "не завершено" with an empty count.
def test_interrupted_run_rows(world, worker, restart):
    suppliers(world)
    world.supplier("Вега", "vega", [item("В-1")])
    world.mode("Бета", "unavailable")
    stop_during(world, worker, kyiv(2026, 10, 6, 3, 30, 2), hold="Вега", written="Бета")
    app2, admin2 = start_again(restart, world, 2026, 10, 6, 3, 40)
    run = runs(admin2)[0]
    assert (run["status"], run["started_at"], run["finished_at"]) == (
        "interrupted",
        "2026-10-06T03:30:02+03:00",
        None,
    )
    assert row(run, "Альфа")["status"] == "success"
    assert (row(run, "Бета")["status"], row(run, "Бета")["parsed_items_count"]) == (
        "error",
        None,
    )
    assert (row(run, "Вега")["status"], row(run, "Вега")["parsed_items_count"]) == (
        "not_finished",
        None,
    )


# REQ-F-023, REQ-F-024, BDD-048: the scheduled run at 03:30 happened; the
# manual run started at 10:00 is stopped at 10:02; at 10:05 the system starts —
# the manual run is "перервано" and a catch-up starts right away.
def test_catch_up_after_interrupted_manual_run(world, worker, restart):
    suppliers(world)
    assert tick_at(world, 2026, 10, 5, 3, 30) is not None
    stop_during(
        world,
        worker,
        kyiv(2026, 10, 5, 10, 0),
        hold="Альфа",
        trigger="manual",
        started_by="admin",
    )
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 10, 5)
    scheduled, manual, catch_up = runs(admin2)
    assert (manual["trigger"], manual["started_by"], manual["status"]) == (
        "manual",
        "admin",
        "interrupted",
    )
    assert catch_up["trigger"] == "catch_up"
    assert catch_up["started_at"] == "2026-10-05T10:05:00+03:00"


# REQ-F-055: after a catch-up at 01:05 for an interrupted run (condition b) the
# scheduled run at 03:30 of the same day happens.
def test_catch_up_for_interrupted_does_not_replace_scheduled(world, worker, restart):
    suppliers(world)
    stop_during(
        world,
        worker,
        kyiv(2026, 10, 5, 1, 0),
        hold="Альфа",
        trigger="manual",
        started_by="admin",
    )
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 1, 5)
    assert [r["trigger"] for r in runs(admin2)] == ["manual", "catch_up"]
    move_to(world.clock, kyiv(2026, 10, 5, 3, 30))
    assert app2.state.updates.tick() is not None
    assert runs(admin2)[-1]["trigger"] == "scheduled"


# REQ-F-023: one catch-up even when both conditions hold (time passed and the
# last run interrupted).
def test_one_catch_up_for_both_conditions(world, worker, restart):
    suppliers(world)
    stop_during(
        world,
        worker,
        kyiv(2026, 10, 4, 22, 0),
        hold="Альфа",
        trigger="manual",
        started_by="admin",
    )
    app2, admin2 = start_again(restart, world, 2026, 10, 5, 9, 0)
    assert [r["trigger"] for r in runs(admin2)] == ["manual", "catch_up"]
    assert app2.state.updates.tick() is None


# --- REQ-F-020, BDD-043: manual run ----------------------------------------------------------------------


# REQ-F-020, BDD-043: the manual run by "admin" is in the log with "вручну" and
# the login; on the same simulator pages the scheduled run gives the same
# supplier statuses, parsed counts and daily prices.
def test_manual_and_scheduled_runs_give_same_results(world):
    suppliers(world)
    world.supplier("Вега", "vega", [item("В-1", "64.20")])
    world.at(2026, 10, 4)
    world.run()
    world.material("М1")
    world.material("М2")
    world.link("А-1", "М1")
    world.link("В-1", "М2")
    world.at(2026, 10, 5, 2, 0)
    manual = wait_run(world.admin, start_manual(world.admin)["id"])
    assert (manual["trigger"], manual["started_by"]) == ("manual", "admin")
    manual_prices = {
        s: world.price_on(s, date(2026, 10, 5)).price for s in ("А-1", "В-1")
    }
    scheduled = wait_run(world.admin, tick_at(world, 2026, 10, 5, 3, 30))

    def outcome(run):
        return [
            (r["supplier"]["name"], r["status"], r["parsed_items_count"])
            for r in run["supplier_run_statuses"]
        ]

    assert outcome(manual) == outcome(scheduled)
    assert manual_prices == {
        s: world.price_on(s, date(2026, 10, 5)).price for s in ("А-1", "В-1")
    }


# --- REQ-NF-014: one process ------------------------------------------------------------------------------


def background_app(spm_app_module, config, clock, client_factory):
    from helpers import ADMIN_LOGIN, ADMIN_PASSWORD

    application = spm_app_module.create_app(
        config, clock=clock, background_updates=True
    )
    tc = client_factory(application)
    assert (
        tc.post(
            f"{API}/sessions", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD}
        ).status_code
        == 201
    )
    return tc


# REQ-NF-014: one process started with background updates serves the web
# interface and performs the scheduled run when 03:30 comes (the scheduler
# checks the clock at least once a second).
def test_one_process_serves_web_and_scheduler(
    world, spm_app_module, config, client_factory
):
    suppliers(world)
    move_to(world.clock, kyiv(2026, 10, 5, 3, 29, 50))
    tc = background_app(spm_app_module, config, world.clock, client_factory)
    assert tc.get("/suppliers").status_code == 200
    assert runs(tc) == []
    move_to(world.clock, kyiv(2026, 10, 5, 3, 30, 0))
    found = wait_until(lambda: runs(tc, "scheduled"), timeout=10, what="scheduled run")
    assert found[0]["started_at"] == "2026-10-05T03:30:00+03:00"
    assert tc.get("/run-log-entries").status_code == 200


# REQ-F-023, UC-15: started with background updates at 10:00 (time 03:30 passed,
# no run that day), the system performs the catch-up right after the start by
# itself.
def test_catch_up_starts_by_itself(world, spm_app_module, config, client_factory):
    suppliers(world)
    move_to(world.clock, kyiv(2026, 10, 5, 10, 0))
    tc = background_app(spm_app_module, config, world.clock, client_factory)
    found = wait_until(lambda: runs(tc, "catch_up"), timeout=10, what="catch-up")
    assert len(found) == 1

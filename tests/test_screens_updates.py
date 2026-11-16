"""Screens of block B2: the run log with the manual run and "прийняти новий
обсяг" buttons, and "стан оновлення постачальників". Server-side HTML, as in B1.

The run log is ``GET /run-log-entries`` (administrator), the update statuses
``GET /supplier-update-statuses`` (both roles); the buttons are forms that post
to ``/runs`` and ``/volume-acceptances``.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from helpers import NO_ACCESS, data_table, forms, page_text
from helpers_b2 import (
    DASH,
    NEVER_UPDATED,
    NO_ACTIVE,
    RUN_IN_PROGRESS,
    item,
    items,
    kyiv,
    log_entries,
    move_to,
    start_manual,
    supplier_written,
    wait_run,
    wait_until,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

STATUS_WORDS = ("успіх", "частково", "помилка", "не завершено")


def supplier_rows(html: str, name: str) -> list[list[str]]:
    """Rows of the log table that show the supplier."""
    _, rows = data_table(html)
    return [r for r in rows if name in r]


def acceptance_forms(html: str) -> list[dict]:
    found = []
    for form in forms(html):
        if form["method"] == "post" and form["action"].endswith("/volume-acceptances"):
            found.append({i.get("name"): i.get("value") for i in form["inputs"]})
    return found


def run_forms(html: str) -> list[dict]:
    return [
        f
        for f in forms(html)
        if f["method"] == "post" and f["action"].endswith("/runs")
    ]


# --- the run log ------------------------------------------------------------------------------


# REQ-F-033, REQ-NF-030: after a manual run with Бета "помилка" the log shows the
# start and finish time ГГ:ХХ:СС, the date РРРР-ММ-ДД, "вручну", the login, the
# overall status, each supplier's status and count, Бета's error text and "—"
# instead of its count.
def test_log_screen_fields(world):
    world.supplier("Альфа", "alfa", items("А", 3))
    world.supplier("Бета", "beta", [item("Б-1")])
    world.mode("Бета", "unavailable")
    world.at(2026, 10, 5, 3, 30, 5)
    wait_run(world.admin, start_manual(world.admin)["id"])
    resp = world.admin.get("/run-log-entries")
    assert resp.status_code == 200
    text = page_text(resp.text)
    for fragment in (
        "2026-10-05",
        "03:30:05",
        "вручну",
        "admin",
        "частково",
        "сторінка недоступна",
    ):
        assert fragment in text, fragment
    (alfa,) = supplier_rows(resp.text, "Альфа")
    assert "успіх" in alfa and "3" in alfa
    (beta,) = supplier_rows(resp.text, "Бета")
    assert "помилка" in beta and DASH in beta and "0" not in beta


# REQ-F-033: a run with a warning shows it in the supplier's row (here the
# duplicate sku А-2).
def test_log_screen_warning(world):
    world.supplier("Альфа", "alfa", [item("А-1"), item("А-2"), item("А-2", "1.00")])
    world.run()
    (alfa,) = supplier_rows(world.admin.get("/run-log-entries").text, "Альфа")
    assert any("А-2" in cell for cell in alfa)


# REQ-F-033, BDD-069: the run in progress — "триває", start "10:00:00", finish
# "—"; Альфа's row "успіх"; in Бета's row status and count "—".
def test_log_screen_run_in_progress(world):
    world.supplier("Альфа", "alfa", items("А", 2))
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 7, 10, 0, 0)
    world.sim.hold("beta")
    run_id = start_manual(world.admin)["id"]
    wait_until(supplier_written(world.admin, "Альфа"), what="Альфа's data")
    html = world.admin.get("/run-log-entries").text
    text = page_text(html)
    assert "триває" in text and "10:00:00" in text and DASH in text
    (alfa,) = supplier_rows(html, "Альфа")
    assert "успіх" in alfa
    (beta,) = supplier_rows(html, "Бета")
    assert beta.count(DASH) >= 2
    assert not any(word in beta for word in STATUS_WORDS)
    world.sim.release()
    wait_run(world.admin, run_id)


# BDD-066, REQ-F-033: the interrupted run — start "03:30:02", finish "—"; Бета
# ("помилка") with count "—"; Вега "не завершено" with count "—".
def test_log_screen_interrupted_run(world, worker, restart):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")])
    world.supplier("Вега", "vega", [item("В-1")])
    world.mode("Бета", "unavailable")
    world.sim.hold("vega")
    proc = worker(kyiv(2026, 10, 6, 3, 30, 2))
    wait_until(lambda: world.sim.requests("vega") == 1, what="request to Вега")
    proc.kill()
    proc.wait(timeout=10)
    world.sim.release()
    move_to(world.clock, kyiv(2026, 10, 6, 3, 40))
    app2, admin2 = restart()
    app2.state.updates.startup()
    for entry in log_entries(admin2):
        wait_run(admin2, entry["run"]["id"])
    html = admin2.get("/run-log-entries?page=1").text
    text = page_text(html)
    assert "перервано" in text and "03:30:02" in text
    beta_rows = supplier_rows(html, "Бета")
    assert any("помилка" in r and DASH in r for r in beta_rows)
    vega_rows = supplier_rows(html, "Вега")
    assert any("не завершено" in r and DASH in r for r in vega_rows)


# REQ-F-063: the entry "немає активних постачальників".
def test_log_screen_no_active_suppliers(admin_client):
    admin_client.post("/api/v1/runs")
    assert NO_ACTIVE in page_text(admin_client.get("/run-log-entries").text)


# REQ-F-057: 120 log entries — the first page links to page 2, page 3 shows 20.
def test_log_screen_pages(admin_client, clock):
    for _ in range(120):
        assert admin_client.post("/api/v1/runs").status_code == 200
        clock.advance(timedelta(minutes=1))
    first = admin_client.get("/run-log-entries").text
    assert "page=2" in first
    _, rows = data_table(admin_client.get("/run-log-entries?page=3").text)
    assert len(rows) == 20


# REQ-NF-019: the log screen has no delete action.
def test_log_screen_has_no_delete(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.run()
    text = page_text(world.admin.get("/run-log-entries").text).lower()
    assert "видалити" not in text and "вилучити" not in text


# REQ-F-005, REQ-NF-003: the manager sees "немає доступу" on the run log (403).
def test_manager_no_access_to_log(manager_client):
    resp = manager_client.get("/run-log-entries")
    assert resp.status_code == 403
    assert NO_ACCESS in page_text(resp.text)


# --- the manual run button ------------------------------------------------------------------------


# REQ-F-020, UC-12: the log has the manual run button; pressing it starts a run
# "вручну" by admin and returns to the log.
def test_manual_run_button(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    html = world.admin.get("/run-log-entries").text
    assert len(run_forms(html)) == 1
    resp = world.admin.post("/runs", follow_redirects=False)
    assert resp.status_code in (302, 303), resp.status_code
    (entry,) = log_entries(world.admin)
    run = wait_run(world.admin, entry["run"]["id"])
    assert (run["trigger"], run["started_by"]) == ("manual", "admin")


# REQ-F-021, BDD-008: pressing the button while a run is going shows "оновлення
# вже триває" and no new run appears in the log.
def test_manual_run_button_while_running(world):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.sim.hold("alfa")
    first = start_manual(world.admin)
    resp = world.admin.post("/runs", follow_redirects=False)
    assert resp.status_code not in (302, 303)
    assert RUN_IN_PROGRESS in page_text(resp.text)
    world.sim.release()
    wait_run(world.admin, first["id"])
    assert len(log_entries(world.admin)) == 1


# REQ-F-063: the button with no active supplier — the log has "немає активних
# постачальників".
def test_manual_run_button_without_active_suppliers(admin_client):
    resp = admin_client.post("/runs")
    assert resp.status_code == 200
    assert NO_ACTIVE in page_text(resp.text)


# REQ-F-005, BDD-030: the manager's button press is 403 "немає доступу"; no run.
def test_manager_cannot_press_manual_run(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1")])
    resp = manager_client.post("/runs", follow_redirects=False)
    assert resp.status_code == 403
    assert NO_ACCESS in page_text(resp.text)
    assert log_entries(world.admin) == []
    assert world.sim.requests("alfa") == 0


# --- "прийняти новий обсяг" ------------------------------------------------------------------------


def partial_days(world, days):
    page = items("А", 100)
    world.supplier("Альфа", "alfa", page)
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 1)
    world.run()
    world.page("Альфа", page[:70])
    runs = []
    for d in days:
        world.at(2026, 10, d)
        runs.append(world.run())
    return runs


# REQ-F-031: "частково" 2026-10-04 and 2026-10-05 — the only button is in
# Альфа's row of the 2026-10-05 run (a form with run_id and supplier_id).
def test_accept_button_only_in_last_partial_run(world):
    run04, run05 = partial_days(world, [4, 5])
    html = world.admin.get("/run-log-entries").text
    found = [
        {k: v for k, v in f.items() if k in ("run_id", "supplier_id")}
        for f in acceptance_forms(html)
    ]
    expected = {
        "run_id": str(run05["id"]),
        "supplier_id": str(world.supplier_ids["Альфа"]),
    }
    assert found == [expected]
    assert run04["id"] != run05["id"]
    assert "прийняти новий обсяг" in page_text(html).lower()


# REQ-F-031, BDD-007: pressing the button returns to the log, which shows the
# acceptance with the administrator's login, the time ГГ:ХХ:СС and the count 70.
def test_accept_button(world):
    (run05,) = partial_days(world, [5])
    move_to(world.clock, kyiv(2026, 10, 5, 9, 15, 7))
    resp = world.admin.post(
        "/volume-acceptances",
        data={
            "run_id": str(run05["id"]),
            "supplier_id": str(world.supplier_ids["Альфа"]),
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.status_code
    html = world.admin.get("/run-log-entries").text
    text = page_text(html)
    assert "09:15:07" in text and "admin" in text and "70" in text
    kinds = [e["kind"] for e in log_entries(world.admin)]
    assert kinds[0] == "volume_acceptance"


# REQ-F-031: "помилка" after "частково" — no button.
def test_no_accept_button_after_error(world):
    partial_days(world, [5])
    world.mode("Альфа", "unavailable")
    world.at(2026, 10, 6)
    world.run()
    assert acceptance_forms(world.admin.get("/run-log-entries").text) == []


# REQ-F-005: the manager's acceptance through the form is 403; nothing accepted.
def test_manager_cannot_accept_volume_on_screen(world, manager_client):
    (run05,) = partial_days(world, [5])
    resp = manager_client.post(
        "/volume-acceptances",
        data={
            "run_id": str(run05["id"]),
            "supplier_id": str(world.supplier_ids["Альфа"]),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert NO_ACCESS in page_text(resp.text)
    assert "volume_acceptance" not in [e["kind"] for e in log_entries(world.admin)]


# --- "стан оновлення постачальників" ---------------------------------------------------------------


# REQ-F-034, REQ-NF-003: the manager opens the screen: columns "постачальник" and
# "дата останнього оновлення"; a supplier never updated shows "ще не оновлювався";
# a deactivated supplier is not listed.
def test_update_statuses_screen(world, manager_client):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.at(2026, 10, 5)
    world.run()
    world.supplier("Бета", "beta", [item("Б-1")])
    world.supplier("Вега", "vega", [item("В-1")], active=False)
    resp = manager_client.get("/supplier-update-statuses")
    assert resp.status_code == 200
    headers, rows = data_table(resp.text)
    norm = [re.sub(r"[«»\"]", "", h).lower() for h in headers]
    assert norm == ["постачальник", "дата останнього оновлення"]
    assert [r[:2] for r in rows] == [["Альфа", "2026-10-05"], ["Бета", NEVER_UPDATED]]


# REQ-F-057, П-4: names by the alphabet of REQ-F-057, 50 rows a page.
def test_update_statuses_screen_order_and_pages(world, admin_client):
    names = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
    for n, name in enumerate(names):
        world.supplier(name, f"s{n}", [item(f"S{n}-1")])
    _, rows = data_table(admin_client.get("/supplier-update-statuses").text)
    assert [r[0] for r in rows] == [
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
    first = admin_client.get("/supplier-update-statuses").text
    assert len(data_table(first)[1]) == 50 and "page=2" in first
    assert (
        len(data_table(admin_client.get("/supplier-update-statuses?page=3").text)[1])
        == 20
    )


# --- REQ-NF-017 ------------------------------------------------------------------------------------------


# REQ-NF-017, BDD-004: during and after a run in which every supplier is
# "помилка" the screens open and show the last written data.
@pytest.mark.parametrize(
    "path",
    [
        "/run-log-entries",
        "/supplier-update-statuses",
        "/suppliers",
        "/materials",
        "/unlinked-items",
        "/settings",
    ],
)
def test_screens_work_during_and_after_failed_run(world, path):
    world.supplier("Альфа", "alfa", [item("А-1")])
    world.supplier("Бета", "beta", [item("Б-1")])
    world.at(2026, 10, 4)
    world.run()
    world.mode("Альфа", "unavailable")
    world.mode("Бета", "unavailable")
    world.at(2026, 10, 5)
    world.sim.hold("beta")
    run_id = start_manual(world.admin)["id"]
    assert world.admin.get(path).status_code == 200
    world.sim.release()
    assert wait_run(world.admin, run_id)["status"] == "error"
    resp = world.admin.get(path)
    assert resp.status_code == 200
    if path == "/supplier-update-statuses":
        assert "2026-10-04" in page_text(resp.text)
    if path == "/unlinked-items":
        assert "А-1" in page_text(resp.text)

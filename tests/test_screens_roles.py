"""T-43: the set of screens, navigation and the rights of the roles.

REQ-F-003, REQ-F-004, REQ-F-005, REQ-F-010 (no deletion of any record),
REQ-NF-001, REQ-NF-003, REQ-NF-015, REQ-NF-017, REQ-F-001; BDD-004 (screens
open), BDD-029, BDD-030, BDD-031; UC-01 (step 3, 3а).

The 11 screens of REQ-NF-003 by address (helpers_b3): the manager's 5 —
``/material-comparisons``, ``/material-comparisons/{id}``, ``/price-history``,
``/events``, ``/supplier-update-statuses``; the administrator's 6 more —
``/suppliers``, ``/materials``, ``/unlinked-items``, ``/attention-items``,
``/run-log-entries``, ``/settings``. Navigation: every screen links (``<a
href>``) to the screens of the role that need no record id.
"""

from __future__ import annotations

import pytest
from helpers import API, NO_ACCESS, all_pages, data_table, has_login_form, page_text
from helpers_b2 import items, row, start_manual, wait_run
from helpers_b3 import (
    ADMIN_ONLY_SCREENS,
    MANAGER_SCREENS,
    D,
    Market,
    hrefs,
    path_of,
    post_forms,
    screen,
)

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

REDIRECT = (302, 303)
NAV_MANAGER = [s for s in MANAGER_SCREENS if "{" not in s]


@pytest.fixture
def market(world):
    """Альфа (А-1 → М1) and Бета (Б-1 → М1, Б-9 unlinked) with prices of
    2026-10-02 and 2026-10-03; Б-1 has the unit "уп" on 10-03 (the attention
    list); events exist ("з'явився", "зміна ціни")."""
    m = Market(
        world,
        {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М1"}},
    )
    m.day(
        D(2), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00", "Б-9": "70.00"}}
    )
    m.day(
        D(3),
        {
            "Альфа": {"А-1": "1100.00"},
            "Бета": {"Б-1": ("1100.00", "уп"), "Б-9": "70.00"},
        },
    )
    return m


def addresses(m: Market, names: list[str]) -> list[str]:
    return [s.format(material=m.mid("М1")) for s in names]


def state(admin_client) -> dict:
    """Everything a manager's request could change (through the administrator)."""
    return {
        "suppliers": all_pages(admin_client, f"{API}/suppliers"),
        "materials": all_pages(admin_client, f"{API}/materials"),
        "unlinked": all_pages(admin_client, f"{API}/unlinked-items"),
        "attention": all_pages(admin_client, f"{API}/attention-items"),
        "settings": admin_client.get(f"{API}/settings").json(),
        "log": all_pages(admin_client, f"{API}/run-log-entries"),
    }


# --- REQ-NF-003: exactly 5 and 11 screens ------------------------------------------------------------


# REQ-NF-003 criterion, BDD-031, REQ-F-004, REQ-NF-015, BDD-004: the administrator
# opens all 11 screens — each is a complete HTML page made on the server with the
# data in it (visible without JavaScript).
@pytest.mark.parametrize("path", MANAGER_SCREENS + ADMIN_ONLY_SCREENS)
def test_admin_opens_all_11_screens(market, admin_client, path):
    html = screen(admin_client, path.format(material=market.mid("М1")))
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html.lower()
    assert not has_login_form(html)


# REQ-NF-003 criterion, REQ-F-003: the manager opens exactly the 5 screens of the
# list.
@pytest.mark.parametrize("path", MANAGER_SCREENS)
def test_manager_opens_5_screens(market, manager_client, path):
    html = screen(manager_client, path.format(material=market.mid("М1")))
    assert not has_login_form(html)


# REQ-NF-003 criterion, REQ-F-005, BDD-030: every other screen answers the manager
# "немає доступу" (403) — not its content and not "не знайдено".
@pytest.mark.parametrize("path", ADMIN_ONLY_SCREENS)
def test_manager_other_screens_no_access(market, manager_client, path):
    resp = manager_client.get(path)
    assert resp.status_code == 403
    text = page_text(resp.text)
    assert NO_ACCESS in text
    assert "не знайдено" not in text.lower()
    for secret in ("А-1", "Б-9", "http://127.0.0.1"):
        assert secret not in text


# REQ-F-001, BDD-029: without a session each screen of block B3 leads to the login
# form.
@pytest.mark.parametrize(
    "path",
    [
        "/material-comparisons",
        "/material-comparisons/1",
        "/price-history",
        "/events",
        "/attention-items",
    ],
)
def test_b3_screens_need_login(accounts, client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    assert path_of(resp.headers["location"]).endswith("/login")
    assert has_login_form(client.get(path).text)


# --- navigation ---------------------------------------------------------------------------------------


# REQ-NF-003, REQ-F-003, UC-01 step 3: every manager screen links to the manager's
# screens and to none of the administrator's.
@pytest.mark.parametrize("path", MANAGER_SCREENS)
def test_manager_navigation(market, manager_client, path):
    links = {
        path_of(h)
        for h in hrefs(screen(manager_client, path.format(material=market.mid("М1"))))
    }
    assert set(NAV_MANAGER) <= links
    assert not links & set(ADMIN_ONLY_SCREENS)


# REQ-NF-003, REQ-F-004: every screen of the administrator links to all 10 screens
# that need no record id.
@pytest.mark.parametrize("path", MANAGER_SCREENS + ADMIN_ONLY_SCREENS)
def test_admin_navigation(market, admin_client, path):
    links = {
        path_of(h)
        for h in hrefs(screen(admin_client, path.format(material=market.mid("М1"))))
    }
    assert set(NAV_MANAGER) | set(ADMIN_ONLY_SCREENS) <= links


# REQ-F-003 criterion: the manager's screens have no element to change data or
# start an update — the only form that posts is "Вийти".
@pytest.mark.parametrize("path", MANAGER_SCREENS)
def test_manager_screens_have_no_change_elements(market, manager_client, path):
    html = screen(manager_client, path.format(material=market.mid("М1")))
    actions = [f["action"] for f in post_forms(html)]
    assert actions and all(a.endswith("/logout") for a in actions)


# --- REQ-F-003, REQ-F-005: the manager's direct requests ------------------------------------------------


# REQ-F-003 criterion, REQ-F-005, BDD-030: every action that changes data,
# settings or starts an update, sent by the manager straight to the form address,
# answers "немає доступу" (403, not 404) and changes nothing — no run, no link,
# no record.
@pytest.mark.parametrize(
    ("path", "data"),
    [
        (
            "/suppliers",
            {
                "name": "Дельта",
                "catalog_url": "http://localhost:8001/d",
                "parser": "table_layout",
                "active": "on",
            },
        ),
        (
            "/suppliers/{alfa}",
            {
                "name": "Альфа",
                "catalog_url": "http://localhost:8001/a",
                "parser": "table_layout",
            },
        ),
        ("/materials", {"name": "Кромка", "unit": "п.м.", "active": "on"}),
        ("/materials/{m1}", {"name": "М1", "unit": "шт"}),
        ("/supplier-items/{b9}/link", {"material_id": "{m2}"}),
        ("/supplier-items/{a1}/unlink", {}),
        ("/settings", {"update_time": "05:00", "notification_threshold": "2"}),
        ("/runs", {}),
        ("/volume-acceptances", {"run_id": "{run}", "supplier_id": "{beta}"}),
    ],
)
def test_manager_actions_no_access(market, admin_client, manager_client, path, data):
    w = market.world
    w.material("М2")
    ids = {
        "alfa": market.sid("Альфа"),
        "beta": market.sid("Бета"),
        "m1": market.mid("М1"),
        "m2": market.mid("М2"),
        "a1": w.item_ids["А-1"],
        "b9": w.item_ids["Б-9"],
        "run": all_pages(admin_client, f"{API}/run-log-entries")[0]["run"]["id"],
    }
    before = state(admin_client)
    requests_before = w.sim.requests("alfa")
    resp = manager_client.post(
        path.format(**ids),
        data={k: v.format(**ids) for k, v in data.items()},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert NO_ACCESS in page_text(resp.text)
    assert state(admin_client) == before
    assert w.sim.requests("alfa") == requests_before


# --- REQ-F-004: the administrator's actions ------------------------------------------------------------


# REQ-F-004 criterion: the administrator does every action of REQ-F-007…REQ-F-017,
# REQ-F-019, REQ-F-020, REQ-F-031, REQ-F-048, REQ-F-050, REQ-F-051, REQ-F-056,
# REQ-F-069 through the screens: create and edit a supplier and a material,
# deactivate and activate both, link, relink, unlink, change the settings, start
# a run and accept a new volume.
def test_admin_does_all_actions_on_screens(world, admin_client):
    page = items("А", 10, "100.00")
    world.supplier("Альфа", "alfa", page)
    world.at(2026, 10, 1)
    world.run()

    def post(path: str, data: dict) -> None:
        resp = admin_client.post(path, data=data, follow_redirects=False)
        assert resp.status_code in REDIRECT, (
            path,
            resp.status_code,
            page_text(resp.text)[:300],
        )

    post(
        "/suppliers",
        {
            "name": "Бета",
            "catalog_url": "http://localhost:8001/b",
            "parser": "cards_layout",
            "active": "on",
        },
    )
    beta = [
        s for s in all_pages(admin_client, f"{API}/suppliers") if s["name"] == "Бета"
    ][0]
    supplier_form = {
        "name": "Бета Плюс",
        "catalog_url": "http://localhost:8001/b2",
        "parser": "list_layout",
    }
    post(f"/suppliers/{beta['id']}", supplier_form)
    post(f"/suppliers/{beta['id']}", {**supplier_form, "active": "on"})
    assert (
        admin_client.get(f"{API}/suppliers/{beta['id']}").json()["name"] == "Бета Плюс"
    )
    post(f"/suppliers/{beta['id']}", supplier_form)
    post("/materials", {"name": "М1", "unit": "шт", "active": "on"})
    post("/materials", {"name": "М2", "unit": "шт", "active": "on"})
    mats = {m["name"]: m["id"] for m in all_pages(admin_client, f"{API}/materials")}
    post(f"/materials/{mats['М2']}", {"name": "М2 нова", "unit": "шт"})
    post(f"/materials/{mats['М2']}", {"name": "М2 нова", "unit": "шт", "active": "on"})
    a1 = [i for i in world.unlinked() if i["sku"] == "А-1"][0]["id"]
    post(f"/supplier-items/{a1}/link", {"material_id": str(mats["М1"])})
    post(f"/supplier-items/{a1}/link", {"material_id": str(mats["М2"])})
    post(f"/supplier-items/{a1}/unlink", {})
    post("/settings", {"update_time": "04:00", "notification_threshold": "2"})
    assert admin_client.get(f"{API}/settings").json()["notification_threshold"] == 2
    world.page("Альфа", page)
    world.at(2026, 10, 2)
    post("/runs", {})
    run = wait_run(
        admin_client, all_pages(admin_client, f"{API}/run-log-entries")[0]["run"]["id"]
    )
    assert row(run, "Альфа")["status"] == "success"
    world.page("Альфа", page[:5])
    world.at(2026, 10, 3)
    run = wait_run(admin_client, start_manual(admin_client)["id"])
    assert row(run, "Альфа")["status"] == "partial"
    post(
        "/volume-acceptances",
        {"run_id": str(run["id"]), "supplier_id": str(world.supplier_ids["Альфа"])},
    )
    entries = all_pages(admin_client, f"{API}/run-log-entries")
    assert entries[0]["kind"] == "volume_acceptance"


# --- REQ-F-010: no deletion -----------------------------------------------------------------------------


# REQ-F-010 criterion, REQ-NF-031: no screen offers deletion — no "видалити" or
# "вилучити" and no form posting to a ".../delete" address, for the
# administrator, whose screens have the most actions.
@pytest.mark.parametrize("path", MANAGER_SCREENS + ADMIN_ONLY_SCREENS)
def test_no_screen_offers_deletion(market, admin_client, path):
    html = screen(admin_client, path.format(material=market.mid("М1")))
    text = page_text(html).lower()
    assert "видалити" not in text and "вилучити" not in text
    assert not [f for f in post_forms(html) if "delete" in f["action"].lower()]


# REQ-F-010, REQ-NF-031: no address deletes prices, events or log entries — DELETE
# on the view operations is 405 and nothing disappears.
@pytest.mark.parametrize(
    "path",
    [
        "/material-comparisons",
        "/material-comparisons/{m1}",
        "/materials/{m1}/price-history",
        "/events",
        "/attention-items",
    ],
)
def test_view_operations_not_deletable(market, admin_client, path):
    before = (
        admin_client.get(f"{API}/events").json(),
        admin_client.get(
            f"{API}/materials/{market.mid('М1')}/price-history?period=all"
        ).json(),
    )
    resp = admin_client.delete(API + path.format(m1=market.mid("М1")))
    assert resp.status_code == 405
    assert resp.json()["code"] == "method_not_allowed"
    after = (
        admin_client.get(f"{API}/events").json(),
        admin_client.get(
            f"{API}/materials/{market.mid('М1')}/price-history?period=all"
        ).json(),
    )
    assert after == before


# --- REQ-NF-017, REQ-NF-001 -------------------------------------------------------------------------------


# REQ-NF-017 criterion, BDD-004: after a run in which every supplier has "помилка",
# all 11 screens open and show the last written data (А-1's price 1100,00 from
# 2026-10-03 in the history, the materials, the suppliers).
def test_all_screens_open_after_failed_run(market, admin_client, manager_client):
    w = market.world
    w.mode("Альфа", "unavailable")
    w.mode("Бета", "broken")
    w.at(2026, 10, 4)
    run = w.run()
    assert {r["status"] for r in run["supplier_run_statuses"]} == {"error"}
    for path in MANAGER_SCREENS + ADMIN_ONLY_SCREENS:
        screen(admin_client, path.format(material=market.mid("М1")))
    for path in MANAGER_SCREENS:
        screen(manager_client, path.format(material=market.mid("М1")))
    html = screen(
        manager_client, f"/price-history?material_id={market.mid('М1')}&period=all"
    )
    _, rows = data_table(html)
    assert rows[0][0] == "2026-10-03"
    assert "Альфа" in page_text(screen(admin_client, "/suppliers"))
    assert "М1" in page_text(screen(manager_client, "/material-comparisons"))


# REQ-NF-001: the screens of block B3 are in Ukrainian (lang="uk" and Ukrainian
# headings), and the data are shown as entered or read from the page.
@pytest.mark.parametrize(
    "path",
    [
        "/material-comparisons",
        "/material-comparisons/{material}",
        "/price-history",
        "/events",
        "/attention-items",
    ],
)
def test_b3_screens_in_ukrainian(market, admin_client, path):
    html = screen(admin_client, path.format(material=market.mid("М1")))
    assert 'lang="uk"' in html
    text = page_text(html)
    assert "Вийти" in text
    for english in ("Comparison", "History", "Events", "Supplier", "Price"):
        assert english not in text


# BDD-030 on the API side is in test_api_runs.py (Н-41); here the screens of
# BDD-030: the manager opens the run log — "немає доступу"; posts a manual run —
# "немає доступу", and no new run appears in the log.
def test_manager_run_log_and_manual_run_bdd030(market, admin_client, manager_client):
    log_before = all_pages(admin_client, f"{API}/run-log-entries")
    resp = manager_client.get("/run-log-entries")
    assert resp.status_code == 403 and NO_ACCESS in page_text(resp.text)
    resp = manager_client.post("/runs", follow_redirects=False)
    assert resp.status_code == 403 and NO_ACCESS in page_text(resp.text)
    assert all_pages(admin_client, f"{API}/run-log-entries") == log_before

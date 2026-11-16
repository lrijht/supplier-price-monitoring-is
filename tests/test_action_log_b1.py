"""A-05 for block B1: action log records of login, logout, session end, state
changes in the directories, links and settings, "немає доступу", the account
command; secrets; log failure; technical log of a failure during login.

REQ-NF-032, REQ-NF-033, REQ-NF-018 (Р-123…Р-128). Run records are block B2.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from helpers import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    API,
    MANAGER_LOGIN,
    MANAGER_PASSWORD,
    api_login,
    create_material,
    create_supplier,
    link,
    page_text,
)

COMMON = {"time", "level", "event", "login", "role", "request_id", "result"}


def events(records: list[dict], event: str) -> list[dict]:
    return [r for r in records if r["event"] == event]


def http_record(records: list[dict], method: str, path: str) -> dict:
    found = [
        r
        for r in records
        if r["event"] == "http_request" and r["method"] == method and r["path"] == path
    ]
    assert found, f"no http_request record for {method} {path}"
    return found[-1]


def same_request(records: list[dict], record: dict, method: str, path: str) -> None:
    assert record["request_id"] == http_record(records, method, path)["request_id"]


# --- login, logout, session end ----------------------------------------------------------


# REQ-NF-032: a successful login through the API — record with the stored login
# and the role, same request id as the HTTP request record of the login.
def test_login_success_record(accounts, client, config, read_log):
    api_login(client, "Admin", ADMIN_PASSWORD)
    records = read_log(config.action_log_path)
    (record,) = events(records, "login_succeeded")
    assert COMMON <= set(record)
    assert (record["login"], record["role"]) == ("admin", "admin")
    same_request(records, record, "POST", f"{API}/sessions")


# REQ-NF-032 criterion: a failed login "nobody" — record with the entered login in
# the event field and empty common login and role.
@pytest.mark.parametrize("login", ["nobody", "admin"])
def test_login_failed_record(accounts, client, config, read_log, login):
    api_login(client, login, "wrong-password")
    records = read_log(config.action_log_path)
    (record,) = events(records, "login_failed")
    assert record["entered_login"] == login
    assert record["login"] is None and record["role"] is None
    same_request(records, record, "POST", f"{API}/sessions")
    assert events(records, "login_succeeded") == []


# REQ-NF-032: login and failed login through the login form are recorded too.
def test_login_form_records(accounts, client, config, read_log):
    client.post(
        "/login", data={"login": "nobody", "password": "x"}, follow_redirects=False
    )
    client.post(
        "/login",
        data={"login": MANAGER_LOGIN, "password": MANAGER_PASSWORD},
        follow_redirects=False,
    )
    records = read_log(config.action_log_path)
    (failed,) = events(records, "login_failed")
    assert failed["entered_login"] == "nobody"
    (ok,) = events(records, "login_succeeded")
    assert (ok["login"], ok["role"]) == ("manager", "manager")


# REQ-NF-032: logout (API and form) — a logout record with the login.
@pytest.mark.parametrize("how", ["api", "form"])
def test_logout_record(admin_client, config, read_log, how):
    if how == "api":
        admin_client.delete(f"{API}/sessions/current")
        method, path = "DELETE", f"{API}/sessions/current"
    else:
        admin_client.post("/logout", follow_redirects=False)
        method, path = "POST", "/logout"
    records = read_log(config.action_log_path)
    (record,) = events(records, "logout")
    assert (record["login"], record["role"]) == ("admin", "admin")
    same_request(records, record, method, path)


# REQ-NF-032 criterion: a request after 8 h of inactivity gives a session end
# record, written when the system detects it (by that request).
def test_session_expired_record(admin_client, config, read_log, clock):
    clock.advance(timedelta(hours=8))
    admin_client.get(f"{API}/sessions/current")
    records = read_log(config.action_log_path)
    (record,) = events(records, "session_expired")
    same_request(records, record, "GET", f"{API}/sessions/current")
    http = http_record(records, "GET", f"{API}/sessions/current")
    assert http["status"] == 401


# REQ-NF-032: no session end record after 7 h 59 min.
def test_no_session_expired_record_before_8h(admin_client, config, read_log, clock):
    clock.advance(timedelta(hours=7, minutes=59))
    admin_client.get(f"{API}/sessions/current")
    assert events(read_log(config.action_log_path), "session_expired") == []


# REQ-NF-032: the HTTP request record of a request with a session has the login
# (and the role in the common fields).
def test_http_record_has_login(admin_client, config, read_log):
    admin_client.get(f"{API}/suppliers?page=1")
    record = http_record(read_log(config.action_log_path), "GET", f"{API}/suppliers")
    assert (record["login"], record["role"]) == ("admin", "admin")
    assert record["status"] == 200


# --- state changes -------------------------------------------------------------------------


def _do(admin_client, add_item, action: str) -> tuple[str, str, int | None]:
    """Perform one state-changing action; return method, path, object id."""
    supplier = create_supplier(admin_client, "Альфа")
    material = create_material(admin_client, "ЛДСП Білий 18 мм", unit="шт")
    item = add_item(supplier["id"], "А-1")
    sid, mid = supplier["id"], material["id"]
    if action in ("link_change", "link_remove"):
        link(admin_client, item, mid)
    if action == "supplier_activate":
        admin_client.patch(f"{API}/suppliers/{sid}", json={"active": False})
    if action == "material_activate":
        admin_client.patch(f"{API}/materials/{mid}", json={"active": False})
    if action == "supplier_create":
        resp = admin_client.post(
            f"{API}/suppliers",
            json={
                "name": "Бета",
                "catalog_url": "http://localhost:8001/b",
                "parser": "cards_layout",
                "active": True,
            },
        )
        return "POST", f"{API}/suppliers", resp.json()["id"]
    if action == "material_create":
        resp = admin_client.post(
            f"{API}/materials", json={"name": "Кромка", "unit": "п.м.", "active": True}
        )
        return "POST", f"{API}/materials", resp.json()["id"]
    bodies = {
        "supplier_update": (
            "PATCH",
            f"{API}/suppliers/{sid}",
            {"name": "Альфа Плюс"},
            sid,
        ),
        "supplier_deactivate": (
            "PATCH",
            f"{API}/suppliers/{sid}",
            {"active": False},
            sid,
        ),
        "supplier_activate": ("PATCH", f"{API}/suppliers/{sid}", {"active": True}, sid),
        "material_update": (
            "PATCH",
            f"{API}/materials/{mid}",
            {"name": "ЛДСП Білий 16 мм"},
            mid,
        ),
        "material_deactivate": (
            "PATCH",
            f"{API}/materials/{mid}",
            {"active": False},
            mid,
        ),
        "material_activate": ("PATCH", f"{API}/materials/{mid}", {"active": True}, mid),
        "link_create": (
            "PUT",
            f"{API}/supplier-items/{item}/link",
            {"material_id": mid},
            item,
        ),
        "settings_update": (
            "PATCH",
            f"{API}/settings",
            {"notification_threshold": 2},
            None,
        ),
    }
    if action == "link_change":
        other = create_material(admin_client, "ЛДСП Сірий 18 мм", unit="шт")
        resp = link(admin_client, item, other["id"])
        assert resp.status_code == 200
        return "PUT", f"{API}/supplier-items/{item}/link", item
    if action == "link_remove":
        resp = admin_client.delete(f"{API}/supplier-items/{item}/link")
        assert resp.status_code == 204
        return "DELETE", f"{API}/supplier-items/{item}/link", item
    method, path, body, object_id = bodies[action]
    resp = admin_client.request(method, path, json=body)
    assert resp.status_code in (200, 201), resp.text
    return method, path, object_id


OBJECT_TYPE = {
    "supplier": "supplier",
    "material": "material",
    "link": "supplier_item",
    "settings": "settings",
}
ACTIONS = [
    "supplier_create",
    "supplier_update",
    "supplier_deactivate",
    "supplier_activate",
    "material_create",
    "material_update",
    "material_deactivate",
    "material_activate",
    "link_create",
    "link_change",
    "link_remove",
    "settings_update",
]


# REQ-NF-032: every state-changing action in the directories, links and settings —
# a record with login, role, object (type and id) and result "success".
@pytest.mark.parametrize("action", ACTIONS)
def test_state_change_success_record(admin_client, add_item, config, read_log, action):
    method, path, object_id = _do(admin_client, add_item, action)
    records = read_log(config.action_log_path)
    found = events(records, action)
    assert found, f"no {action} record"
    record = found[-1]
    assert (record["login"], record["role"]) == ("admin", "admin")
    assert record["result"] == "success"
    assert record["object_type"] == OBJECT_TYPE[action.split("_")[0]]
    assert record["object_id"] == object_id
    same_request(records, record, method, path)


# REQ-NF-032 criterion: linking an item whose unit differs — record of the link
# with result "rejected" and reason code link_units_differ (API and web).
@pytest.mark.parametrize("how", ["api", "web"])
def test_link_rejected_record(admin_client, add_item, config, read_log, how):
    supplier = create_supplier(admin_client, "Бета")
    material = create_material(admin_client, "Кромка біла 2 мм", unit="п.м.")
    item = add_item(supplier["id"], "Б-2", "Кромка", "м.п.")
    if how == "api":
        assert link(admin_client, item, material["id"]).status_code == 409
    else:
        admin_client.post(
            f"/supplier-items/{item}/link",
            data={"material_id": str(material["id"])},
            follow_redirects=False,
        )
    (record,) = events(read_log(config.action_log_path), "link_create")
    assert record["result"] == "rejected"
    assert record["reason_code"] == "link_units_differ"
    assert (record["object_type"], record["object_id"]) == ("supplier_item", item)
    assert (record["login"], record["role"]) == ("admin", "admin")


# REQ-NF-032: the reason code is the contract's code — e.g. supplier_name_taken,
# unit_locked, material_inactive, validation_failed.
@pytest.mark.parametrize(
    ("case", "event", "reason"),
    [
        ("name_taken", "supplier_create", "supplier_name_taken"),
        ("unit_locked", "material_update", "unit_locked"),
        ("inactive", "link_create", "material_inactive"),
        ("already_linked", "link_create", "material_supplier_already_linked"),
        ("threshold", "settings_update", "validation_failed"),
    ],
)
def test_rejected_records_have_contract_codes(
    admin_client, add_item, config, read_log, case, event, reason
):
    supplier = create_supplier(admin_client, "Альфа")
    material = create_material(admin_client, "ЛДСП Білий 18 мм", unit="шт")
    first, second = add_item(supplier["id"], "А-1"), add_item(supplier["id"], "А-2")
    if case == "name_taken":
        admin_client.post(
            f"{API}/suppliers",
            json={
                "name": "альфа",
                "catalog_url": "http://localhost:8001/a",
                "parser": "table_layout",
                "active": True,
            },
        )
    elif case == "unit_locked":
        link(admin_client, first, material["id"])
        admin_client.patch(f"{API}/materials/{material['id']}", json={"unit": "уп"})
    elif case == "inactive":
        admin_client.patch(f"{API}/materials/{material['id']}", json={"active": False})
        link(admin_client, first, material["id"])
    elif case == "already_linked":
        link(admin_client, first, material["id"])
        link(admin_client, second, material["id"])
    else:
        admin_client.patch(f"{API}/settings", json={"notification_threshold": 0.05})
    rejected = [
        r
        for r in events(read_log(config.action_log_path), event)
        if r["result"] == "rejected"
    ]
    assert [r["reason_code"] for r in rejected] == [reason]


# REQ-NF-032 criterion: the manager's request to change the threshold gives one
# "немає доступу" record with the action and the object and no settings record.
def test_access_denied_settings_record(manager_client, config, read_log):
    manager_client.patch(f"{API}/settings", json={"notification_threshold": 3})
    records = read_log(config.action_log_path)
    (record,) = events(records, "access_denied")
    assert (record["login"], record["role"]) == ("manager", "manager")
    assert record["action"] == "settings_update"
    assert record["object_type"] == "settings"
    assert events(records, "settings_update") == []
    same_request(records, record, "PATCH", f"{API}/settings")


# REQ-NF-032: "немає доступу" on a material — action and object (type and id); the
# same for the web form.
@pytest.mark.parametrize("how", ["api", "web"])
def test_access_denied_material_record(
    admin_client, manager_client, config, read_log, how
):
    mid = create_material(admin_client, "ЛДСП Білий 18 мм")["id"]
    if how == "api":
        manager_client.patch(f"{API}/materials/{mid}", json={"name": "Інший"})
    else:
        manager_client.post(
            f"/materials/{mid}",
            data={"name": "Інший", "unit": "шт", "active": "on"},
            follow_redirects=False,
        )
    records = read_log(config.action_log_path)
    (record,) = events(records, "access_denied")
    assert record["action"] == "material_update"
    assert (record["object_type"], record["object_id"]) == ("material", mid)
    assert events(records, "material_update") == []


# REQ-NF-032: web actions are recorded with the same event and reason codes.
def test_web_settings_change_record(admin_client, config, read_log):
    admin_client.post(
        "/settings",
        data={"update_time": "03:30", "notification_threshold": "2"},
        follow_redirects=False,
    )
    admin_client.post(
        "/settings",
        data={"update_time": "25:00", "notification_threshold": "2"},
        follow_redirects=False,
    )
    records = events(read_log(config.action_log_path), "settings_update")
    assert [r["result"] for r in records] == ["success", "rejected"]
    assert records[1]["reason_code"] == "validation_failed"


# --- the account command -----------------------------------------------------------------------


# REQ-NF-032 criterion: the set-up command gives an account creation record with
# login and role and an empty request id.
def test_account_created_record(run_account_command, config, read_log):
    assert run_account_command(["ivan.petrenko_1", "manager"], "password-8") == 0
    (record,) = events(read_log(config.action_log_path), "account_created")
    assert COMMON <= set(record)
    assert record["account_login"] == "ivan.petrenko_1"
    assert record["account_role"] == "manager"
    assert record["request_id"] in (None, "")
    assert record["time"][-6:] in ("+03:00", "+02:00")


# REQ-NF-032: a refused command creates no account creation record.
def test_refused_command_no_record(run_account_command, config, read_log):
    run_account_command(["ab", "manager"], "password-8")
    assert events(read_log(config.action_log_path), "account_created") == []


# --- secrets (Р-125) --------------------------------------------------------------------------


# REQ-NF-032, REQ-NF-018: neither log holds passwords, password hashes or cookie
# values — after command, logins (API and form), failed logins, logout.
def test_logs_have_no_passwords_hashes_or_cookies(
    run_account_command, app, client_factory, config, read_log
):
    assert run_account_command([ADMIN_LOGIN, "admin"], ADMIN_PASSWORD) == 0
    assert run_account_command([MANAGER_LOGIN, "manager"], MANAGER_PASSWORD) == 0
    api_client, web_client = client_factory(app), client_factory(app)
    api_login(api_client, ADMIN_LOGIN, "wrong-secret-password")
    resp = api_login(api_client, ADMIN_LOGIN, ADMIN_PASSWORD)
    cookies = [resp.cookies.get("spm_session")]
    api_client.patch(f"{API}/settings", json={"notification_threshold": 2})
    web_client.post(
        "/login", data={"login": MANAGER_LOGIN, "password": "wrong-secret-password"}
    )
    web_client.post(
        "/login", data={"login": MANAGER_LOGIN, "password": MANAGER_PASSWORD}
    )
    cookies.append(web_client.cookies.get("spm_session"))
    web_client.post("/logout")
    api_client.delete(f"{API}/sessions/current")
    with closing(sqlite3.connect(config.database_path)) as db:
        hashes = [row[0] for row in db.execute("SELECT password_hash FROM accounts")]
    secrets = [
        ADMIN_PASSWORD,
        MANAGER_PASSWORD,
        "wrong-secret-password",
        *hashes,
        *cookies,
    ]
    assert all(secrets)
    for path in (config.action_log_path, config.technical_log_path):
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        for secret in secrets:
            assert secret not in text, f"secret found in {path.name}"


# --- REQ-NF-033: log failure ----------------------------------------------------------------------


@pytest.fixture
def broken_action_log(config_factory, tmp_path):
    """A configuration whose action log path is a directory: writes are impossible."""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "actions.log").mkdir()
    return config_factory(
        database_path=broken / "spm.db",
        action_log_path=broken / "actions.log",
        technical_log_path=broken / "technical.log",
    )


def _admin_of(app, client_factory, run_account_command, cfg):
    assert run_account_command([ADMIN_LOGIN, "admin"], ADMIN_PASSWORD, cfg=cfg) == 0
    tc = client_factory(app)
    assert api_login(tc, ADMIN_LOGIN, ADMIN_PASSWORD).status_code == 201
    return tc


# REQ-NF-033 criterion (API): with the action log unwritable the administrator
# changes the threshold 1 % → 2 % and gets 200 with the same data; threshold 2 %.
def test_threshold_change_api_with_broken_action_log(
    app_factory, client_factory, run_account_command, config, broken_action_log
):
    normal = _admin_of(app_factory(config), client_factory, run_account_command, config)
    broken = _admin_of(
        app_factory(broken_action_log),
        client_factory,
        run_account_command,
        broken_action_log,
    )
    expected = normal.patch(f"{API}/settings", json={"notification_threshold": 2})
    resp = broken.patch(f"{API}/settings", json={"notification_threshold": 2})
    assert resp.status_code == expected.status_code == 200
    assert resp.json() == expected.json()
    assert resp.headers["content-type"] == expected.headers["content-type"]
    assert broken.get(f"{API}/settings").json()["notification_threshold"] == 2


# REQ-NF-033 criterion (web): the same through the web interface — threshold 2 %,
# the page is the same as without the failure.
def test_threshold_change_web_with_broken_action_log(
    app_factory, client_factory, run_account_command, config, broken_action_log
):
    normal = _admin_of(app_factory(config), client_factory, run_account_command, config)
    broken = _admin_of(
        app_factory(broken_action_log),
        client_factory,
        run_account_command,
        broken_action_log,
    )
    form = {"update_time": "03:30", "notification_threshold": "2"}
    expected = normal.post("/settings", data=form)
    resp = broken.post("/settings", data=form)
    assert resp.status_code == expected.status_code
    assert page_text(resp.text) == page_text(expected.text)
    assert broken.get(f"{API}/settings").json()["notification_threshold"] == 2


# --- REQ-NF-018: technical log of a failure during login ---------------------------------------


def _break_storage(config) -> None:
    """Artificial storage failure: the accounts table disappears."""
    with closing(sqlite3.connect(config.database_path)) as db:
        db.execute("DROP TABLE accounts")
        db.commit()


# REQ-NF-018 criterion: an unexpected exception during the login request (storage
# failure) — 500 internal_error; a technical log record with the request id of
# that HTTP request; no password and no cookie in either log.
@pytest.mark.parametrize("how", ["api", "form"])
def test_login_failure_goes_to_technical_log(accounts, client, config, read_log, how):
    client.get(f"{API}/no-such-resource")  # the app has started
    _break_storage(config)
    password = "typed-secret-password-77"
    client.cookies.set("spm_session", "stale-cookie-value-123")
    if how == "api":
        resp = client.post(
            f"{API}/sessions", json={"login": ADMIN_LOGIN, "password": password}
        )
        assert resp.status_code == 500
        assert resp.json()["code"] == "internal_error"
        method, path = "POST", f"{API}/sessions"
    else:
        resp = client.post(
            "/login",
            data={"login": ADMIN_LOGIN, "password": password},
            follow_redirects=False,
        )
        assert resp.status_code == 500
        method, path = "POST", "/login"
    http = http_record(read_log(config.action_log_path), method, path)
    technical = read_log(config.technical_log_path)
    mine = [r for r in technical if r["request_id"] == http["request_id"]]
    assert mine and all(COMMON <= set(r) for r in mine)
    for log_path in (config.action_log_path, config.technical_log_path):
        text = log_path.read_text(encoding="utf-8")
        assert password not in text
        assert "stale-cookie-value-123" not in text

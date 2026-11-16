"""T-52 (rest): session, login and logout through the API; 401, 405, 415, 422.

REQ-NF-031, REQ-F-071, REQ-F-001 and REQ-F-002 (through the API), REQ-NF-021
(through the API), REQ-NF-001 (error texts); BDD-065; contract scenarios
П-01…П-03, Н-02, Н-08, Н-16, Н-27 from tests/contract/scenarios.json.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from helpers import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    API,
    MANAGER_LOGIN,
    MANAGER_PASSWORD,
    api_login,
    assert_problem,
    error_codes,
    has_login_form,
)

SESSIONS = f"{API}/sessions"
CURRENT = f"{API}/sessions/current"


def session_cookie(resp) -> str:
    header = resp.headers.get("set-cookie", "")
    assert "spm_session=" in header
    return header


# П-01, BDD-065, REQ-F-001: login "Admin" for the account "admin" opens a session:
# 201, session cookie with SameSite=Lax, Location of the current session.
def test_login_admin_case_insensitive(accounts, client):
    resp = api_login(client, "Admin", ADMIN_PASSWORD)
    assert resp.status_code == 201
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"account": {"login": "admin", "role": "admin"}}
    assert resp.headers["location"] == CURRENT
    cookie = session_cookie(resp).lower()
    assert "samesite=lax" in cookie
    assert ADMIN_PASSWORD not in resp.text


# Н-02, REQ-F-001: wrong password — 401 invalid_credentials, no session.
@pytest.mark.parametrize(
    ("login", "password"),
    [
        (ADMIN_LOGIN, "wrong-password"),
        ("nobody", ADMIN_PASSWORD),
        ("admin", ADMIN_PASSWORD.upper()),
    ],
)
def test_login_wrong_credentials(accounts, client, login, password):
    resp = api_login(client, login, password)
    assert_problem(resp, 401, "invalid_credentials")
    assert "spm_session=" not in resp.headers.get("set-cookie", "")
    assert_problem(client.get(CURRENT), 401, "unauthenticated")


# Contract SessionCreate: login and password are required, no other fields — 422.
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"login": "admin"}, ("password", "required")),
        ({"password": ADMIN_PASSWORD}, ("login", "required")),
        ({"login": "", "password": ADMIN_PASSWORD}, ("login", "required")),
        (
            {"login": "admin", "password": ADMIN_PASSWORD, "role": "admin"},
            ("role", "unknown_field"),
        ),
        ({"login": 5, "password": ADMIN_PASSWORD}, ("login", "invalid_type")),
    ],
)
def test_login_body_validation(accounts, client, body, expected):
    body = assert_problem(client.post(SESSIONS, json=body), 422, "validation_failed")
    assert expected in error_codes(body)


# П-02, REQ-F-071: the current session — login as stored and the role.
def test_current_session_admin_logged_in_as_Admin(accounts, client):
    api_login(client, "Admin", ADMIN_PASSWORD)
    resp = client.get(CURRENT)
    assert resp.status_code == 200
    assert resp.json() == {"account": {"login": "admin", "role": "admin"}}


# REQ-F-071: the manager gets his login and the manager role.
def test_current_session_manager(manager_client):
    resp = manager_client.get(CURRENT)
    assert resp.status_code == 200
    assert resp.json() == {"account": {"login": MANAGER_LOGIN, "role": "manager"}}


# REQ-F-071, REQ-NF-031: the current session without a session — 401.
def test_current_session_without_session(client):
    assert_problem(client.get(CURRENT), 401, "unauthenticated")


# REQ-NF-031: after login through the API later requests need no new login.
def test_session_serves_following_requests(admin_client):
    for _ in range(3):
        assert admin_client.get(CURRENT).status_code == 200
    assert admin_client.get(f"{API}/suppliers").status_code == 200


# П-03, REQ-F-002: logout — 204; the next request gets 401.
def test_logout_through_api(admin_client):
    resp = admin_client.delete(CURRENT)
    assert resp.status_code == 204
    assert resp.content == b""
    assert_problem(admin_client.get(CURRENT), 401, "unauthenticated")
    assert_problem(admin_client.get(f"{API}/suppliers"), 401, "unauthenticated")


# REQ-F-002, REQ-NF-031: logout without a session — 401.
def test_logout_without_session(client):
    assert_problem(client.delete(CURRENT), 401, "unauthenticated")


# REQ-NF-021 through the API: after 7 h 59 min of inactivity the request is served.
def test_api_session_alive_after_7h59m(admin_client, clock):
    clock.advance(timedelta(hours=7, minutes=59))
    assert admin_client.get(CURRENT).status_code == 200


# REQ-NF-021 through the API: after 8 h of inactivity — 401.
def test_api_session_expires_after_8h(admin_client, clock):
    clock.advance(timedelta(hours=8))
    assert_problem(admin_client.get(CURRENT), 401, "unauthenticated")


# REQ-NF-031: the session opened through the API works for the web screens.
def test_api_session_works_for_screens(admin_client):
    page = admin_client.get("/suppliers")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert not has_login_form(page.text)


# REQ-NF-031: the session from the login form works for the API.
def test_form_session_works_for_api(accounts, client):
    resp = client.post(
        "/login",
        data={"login": MANAGER_LOGIN, "password": MANAGER_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    current = client.get(CURRENT)
    assert current.status_code == 200
    assert current.json()["account"]["role"] == "manager"


# REQ-F-002, REQ-NF-031: logout through the API ends the session for screens too,
# and logout on the screen ends it for the API.
def test_logout_is_shared_between_api_and_screens(accounts, admin_client, client):
    admin_client.delete(CURRENT)
    page = admin_client.get("/suppliers")
    assert has_login_form(page.text)
    client.post("/login", data={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD})
    client.post("/logout")
    assert_problem(client.get(CURRENT), 401, "unauthenticated")


# REQ-NF-031: without a session the API answers 401 in the error model, not with a
# redirect to the login form.
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", CURRENT),
        ("DELETE", CURRENT),
        ("GET", f"{API}/suppliers"),
        ("GET", f"{API}/settings"),
    ],
)
def test_api_without_session_is_401_not_redirect(client, method, path):
    resp = client.request(method, path, follow_redirects=False)
    assert_problem(resp, 401, "unauthenticated")
    assert "location" not in resp.headers


# REQ-NF-031, info.description of the contract: a method the address does not
# have — 405 method_not_allowed (the session addresses).
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", SESSIONS),
        ("PUT", SESSIONS),
        ("DELETE", SESSIONS),
        ("POST", CURRENT),
        ("PUT", CURRENT),
        ("PATCH", CURRENT),
    ],
)
def test_session_addresses_method_not_allowed(admin_client, method, path):
    body = assert_problem(admin_client.request(method, path), 405, "method_not_allowed")
    assert method in body["detail"]


# REQ-NF-031, section 0 of docs/api/resources.md: a body not in JSON — 415.
@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/plain", "login=admin&password=x"),
        ("application/x-www-form-urlencoded", "login=admin&password=x"),
    ],
)
def test_login_body_not_json_is_415(accounts, client, content_type, content):
    resp = client.post(
        SESSIONS, content=content, headers={"Content-Type": content_type}
    )
    assert_problem(resp, 415, "unsupported_media_type")
    assert_problem(client.get(CURRENT), 401, "unauthenticated")


# Н-27 (for the session address): a body that is not valid JSON — 422 with
# errors[] = {field: null, code: malformed_json}.
@pytest.mark.parametrize("raw", ['{"login": ', "not json", ""])
def test_login_malformed_json_is_422(accounts, client, raw):
    resp = client.post(
        SESSIONS, content=raw, headers={"Content-Type": "application/json"}
    )
    body = assert_problem(resp, 422, "validation_failed")
    assert error_codes(body) == [(None, "malformed_json")]


# REQ-NF-031, REQ-F-006: the API has no operations with accounts.
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{API}/accounts"),
        ("POST", f"{API}/accounts"),
        ("GET", f"{API}/users"),
        ("POST", f"{API}/users"),
        ("PATCH", f"{API}/accounts/1"),
        ("DELETE", f"{API}/accounts/1"),
    ],
)
def test_no_account_operations_in_api(admin_client, method, path):
    resp = admin_client.request(method, path, json={"login": "x", "role": "admin"})
    assert_problem(resp, 404, "not_found")


# REQ-NF-031: API and web interface are served by the same application.
def test_api_and_web_served_by_same_app(admin_client):
    api = admin_client.get(f"{API}/settings")
    web = admin_client.get("/settings")
    assert api.headers["content-type"].startswith("application/json")
    assert web.headers["content-type"].startswith("text/html")

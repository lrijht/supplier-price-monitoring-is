"""T-11: accounts, login, logout and session lifetime (web interface).

REQ-F-001, REQ-F-002, REQ-F-006, REQ-NF-020, REQ-NF-021; BDD-029, BDD-065;
UC-01, UC-16.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from helpers import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    MANAGER_PASSWORD,
    WRONG_CREDENTIALS,
    has_login_form,
    has_logout_button,
    page_text,
)

ROOT = Path(__file__).resolve().parents[1]

# Screens of REQ-NF-003 built in block B1 (addresses mirror the API paths).
B1_SCREENS = ["/suppliers", "/materials", "/unlinked-items", "/settings"]
# BDD-029 uses the comparison screen; without a session every screen address
# leads to the login form, whether or not the screen is built yet.
COMPARISON_SCREEN = "/material-comparisons"


def accounts_rows(database_path: Path) -> list[tuple[str, str, str]]:
    with closing(sqlite3.connect(database_path)) as db:
        return db.execute(
            "SELECT login, role, password_hash FROM accounts ORDER BY login"
        ).fetchall()


def web_login(client, login: str, password: str):
    return client.post(
        "/login", data={"login": login, "password": password}, follow_redirects=False
    )


def assert_leads_to_login_form(client, path: str) -> None:
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code in (302, 303, 307), resp.status_code
    assert urlsplit(resp.headers["location"]).path == "/login"
    final = client.get(path)
    assert final.status_code == 200
    assert final.headers["content-type"].startswith("text/html")
    assert has_login_form(final.text)


# --- REQ-F-006: the account set-up command ---------------------------------------


# REQ-F-006, BDD-065: login "ivan.petrenko_1", role manager, 8-character password
# typed interactively — the account is created; login "Ivan.Petrenko_1" works.
def test_command_creates_account_and_login_works(
    run_account_command, config, app, client
):
    assert run_account_command(["ivan.petrenko_1", "manager"], "8chars!!") == 0
    assert run_account_command.prompts, "the password is asked interactively"
    assert [(r[0], r[1]) for r in accounts_rows(config.database_path)] == [
        ("ivan.petrenko_1", "manager")
    ]
    resp = web_login(client, "Ivan.Petrenko_1", "8chars!!")
    assert resp.status_code in (302, 303)
    assert urlsplit(resp.headers["location"]).path != "/login"


# REQ-F-006: the command works on a new system before the application ever ran.
def test_command_creates_database_if_missing(run_account_command, config):
    assert not Path(config.database_path).exists()
    assert run_account_command(["admin", "admin"], ADMIN_PASSWORD) == 0
    assert accounts_rows(config.database_path)[0][:2] == ("admin", "admin")


# REQ-F-006: both roles can be created; an unknown role is refused.
@pytest.mark.parametrize(
    ("role", "ok"), [("manager", True), ("admin", True), ("boss", False)]
)
def test_command_roles(run_account_command, config, role, ok):
    code = run_account_command(["petro", role], "password-8")
    assert (code == 0) is ok
    rows = (
        accounts_rows(config.database_path)
        if Path(config.database_path).exists()
        else []
    )
    assert ([(r[0], r[1]) for r in rows] == [("petro", role)]) is ok


# REQ-F-006: the command has no parameter for the password; an attempt to pass it
# is refused and nothing is created.
@pytest.mark.parametrize(
    "argv",
    [
        ["petro", "manager", "--password", "password-8"],
        ["petro", "manager", "-p", "password-8"],
        ["petro", "manager", "password-8"],
    ],
)
def test_command_has_no_password_parameter(run_account_command, config, argv):
    assert run_account_command(argv, "password-8") != 0
    if Path(config.database_path).exists():
        assert accounts_rows(config.database_path) == []


# REQ-F-006: the command's help lists no password option. It runs as
# ``python -m spm.auth.cli`` from the command line.
def test_command_help_has_no_password_option(tmp_path):
    env = dict(os.environ)
    env.update(
        {
            "SPM_SESSION_SECRET": "help-only-test-value",
            "SPM_DATABASE_PATH": str(tmp_path / "spm.db"),
            "SPM_ACTION_LOG_PATH": str(tmp_path / "actions.log"),
            "SPM_TECHNICAL_LOG_PATH": str(tmp_path / "technical.log"),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "spm.auth.cli", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--password" not in result.stdout
    assert "-p " not in result.stdout


# REQ-F-006 criterion: logins "ab", "admin user", longer than 32 characters and a
# 7-character password are refused with an explanation; nothing changes.
@pytest.mark.parametrize(
    ("login", "password"),
    [
        ("ab", "password-8"),
        ("admin user", "password-8"),
        ("a" * 33, "password-8"),
        ("петро", "password-8"),
        ("petro!", "password-8"),
        ("", "password-8"),
        ("petro", "7chars!"),
        ("petro", ""),
    ],
)
def test_command_refuses_invalid_login_or_password(
    run_account_command, config, capsys, login, password
):
    assert run_account_command(["existing", "admin"], ADMIN_PASSWORD) == 0
    before = accounts_rows(config.database_path)
    capsys.readouterr()
    assert run_account_command([login, "manager"], password) != 0
    out = capsys.readouterr()
    assert (out.out + out.err).strip(), "the refusal has an explanation"
    assert accounts_rows(config.database_path) == before


# REQ-F-006 (boundaries): 3 and 32 characters, letters, digits, ".", "_", "-" and
# an 8-character password are accepted.
@pytest.mark.parametrize("login", ["abc", "a" * 32, "Ivan.P-2_x"])
def test_command_accepts_boundary_logins(run_account_command, config, login):
    assert run_account_command([login, "manager"], "12345678") == 0
    assert [r[0] for r in accounts_rows(config.database_path)] == [login]


# REQ-F-006, BDD-065: login "Admin" when "admin" exists — the command says the login
# exists; the password and role of "admin" stay as before.
def test_command_refuses_existing_login_case_insensitively(
    run_account_command, config, capsys, app, client
):
    assert run_account_command(["admin", "admin"], ADMIN_PASSWORD) == 0
    before = accounts_rows(config.database_path)
    capsys.readouterr()
    assert run_account_command(["Admin", "manager"], "other-password-9") != 0
    out = capsys.readouterr()
    assert "існує" in out.out + out.err
    assert accounts_rows(config.database_path) == before
    assert web_login(client, "admin", "other-password-9").status_code not in (302, 303)
    resp = web_login(client, "admin", ADMIN_PASSWORD)
    assert resp.status_code in (302, 303)
    current = client.get("/api/v1/sessions/current").json()
    assert current["account"] == {"login": "admin", "role": "admin"}


# --- REQ-NF-020: password storage ------------------------------------------------


# REQ-NF-020: no password in clear text in the database; equal passwords of two
# users have different hashes (salt).
def test_password_stored_only_as_salted_hash(run_account_command, config):
    password = "same-password-42"
    assert run_account_command(["olena", "manager"], password) == 0
    assert run_account_command(["taras", "admin"], password) == 0
    rows = accounts_rows(config.database_path)
    hashes = [r[2] for r in rows]
    assert len(hashes) == 2 and hashes[0] != hashes[1]
    for value in hashes:
        assert value and password not in value
    raw = b"".join(
        p.read_bytes()
        for p in Path(config.database_path).parent.glob(
            Path(config.database_path).name + "*"
        )
    )
    assert password.encode("utf-8") not in raw


# --- REQ-F-001, BDD-029: login is required ----------------------------------------


# BDD-029, REQ-F-001: without login the comparison screen address shows the
# login form.
def test_comparison_screen_without_login_shows_login_form(client):
    assert_leads_to_login_form(client, COMPARISON_SCREEN)


# REQ-F-001: a request to any screen without login leads to the login form.
@pytest.mark.parametrize("path", [*B1_SCREENS, "/materials/1/links", "/suppliers/new"])
def test_any_screen_without_login_leads_to_login_form(client, path):
    assert_leads_to_login_form(client, path)


# REQ-F-001: the login form is a server page in Ukrainian with login and password.
def test_login_form_page(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert has_login_form(resp.text)
    assert "Вхід" in page_text(resp.text)


# REQ-F-001: with the right login and password the user gets into the system.
# The login is compared case-insensitively. (The manager's screens come in B3,
# so the manager's session is checked through the API, REQ-NF-031.)
@pytest.mark.parametrize(
    ("login", "password", "screen", "account"),
    [
        (ADMIN_LOGIN, ADMIN_PASSWORD, "/suppliers", ("admin", "admin")),
        ("ADMIN", ADMIN_PASSWORD, "/settings", ("admin", "admin")),
        ("Manager", MANAGER_PASSWORD, None, ("manager", "manager")),
    ],
)
def test_login_with_right_credentials(
    accounts, client, login, password, screen, account
):
    resp = web_login(client, login, password)
    assert resp.status_code in (302, 303)
    assert urlsplit(resp.headers["location"]).path != "/login"
    if screen:
        page = client.get(screen)
        assert page.status_code == 200
        assert not has_login_form(page.text)
    current = client.get("/api/v1/sessions/current")
    assert current.status_code == 200
    assert current.json()["account"] == {"login": account[0], "role": account[1]}


# REQ-F-001: with wrong data the user sees an error message and stays on the form.
@pytest.mark.parametrize(
    ("login", "password"),
    [(ADMIN_LOGIN, "wrong-password"), ("nobody", ADMIN_PASSWORD), ("Admin", "x")],
)
def test_login_with_wrong_credentials_stays_on_form(accounts, client, login, password):
    resp = web_login(client, login, password)
    assert resp.status_code not in (301, 302, 303, 307)
    assert has_login_form(resp.text)
    assert WRONG_CREDENTIALS in page_text(resp.text)
    assert_leads_to_login_form(client, "/suppliers")


# REQ-F-001: the password is checked as typed (case-sensitive), unlike the login.
def test_password_is_case_sensitive(accounts, client):
    resp = web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD.upper())
    assert resp.status_code not in (302, 303)
    assert has_login_form(resp.text)


# --- REQ-F-002: logout -----------------------------------------------------------


# REQ-F-002: screens have the "Вийти" button; after it any screen leads to the
# login form.
def test_logout_leads_back_to_login_form(accounts, client):
    assert web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD).status_code in (302, 303)
    page = client.get("/suppliers")
    assert page.status_code == 200
    assert has_logout_button(page.text)
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert urlsplit(resp.headers["location"]).path == "/login"
    for path in B1_SCREENS:
        assert_leads_to_login_form(client, path)


# REQ-F-002: logout of one user does not end another user's session.
def test_logout_keeps_other_sessions(accounts, app, client_factory):
    first, second = client_factory(app), client_factory(app)
    web_login(first, ADMIN_LOGIN, ADMIN_PASSWORD)
    web_login(second, ADMIN_LOGIN, ADMIN_PASSWORD)
    first.post("/logout")
    assert second.get("/suppliers").status_code == 200
    assert not has_login_form(second.get("/suppliers").text)


# --- REQ-NF-021: session lifetime, controlled clock ---------------------------------


# REQ-NF-021: a request after 7 h 59 min of inactivity is served without login.
def test_session_alive_after_7h59m(accounts, client, clock):
    web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD)
    clock.advance(timedelta(hours=7, minutes=59))
    page = client.get("/suppliers")
    assert page.status_code == 200
    assert not has_login_form(page.text)


# REQ-NF-021: after 8 h without requests the next request leads to the login form.
@pytest.mark.parametrize("idle", [timedelta(hours=8), timedelta(hours=8, minutes=1)])
def test_session_ends_after_8h_idle(accounts, client, clock, idle):
    web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD)
    clock.advance(idle)
    assert_leads_to_login_form(client, "/suppliers")


# REQ-NF-021: inactivity counts from the last request, not from login.
def test_session_lifetime_counts_from_last_request(accounts, client, clock):
    web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD)
    clock.advance(timedelta(hours=7, minutes=59))
    assert client.get("/suppliers").status_code == 200
    clock.advance(timedelta(hours=7, minutes=59))
    page = client.get("/suppliers")
    assert page.status_code == 200
    assert not has_login_form(page.text)


# REQ-NF-021: an expired session stays ended; a new login opens a new session.
def test_new_login_after_expiry(accounts, client, clock):
    web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD)
    clock.advance(timedelta(hours=8))
    assert_leads_to_login_form(client, "/suppliers")
    assert web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD).status_code in (302, 303)
    assert client.get("/suppliers").status_code == 200


# --- REQ-F-006: no user management in the web interface ---------------------------


# REQ-F-006: the web interface has no registration or user management.
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/register"),
        ("GET", "/signup"),
        ("GET", "/accounts"),
        ("GET", "/users"),
        ("POST", "/accounts"),
        ("POST", "/users"),
    ],
)
def test_no_user_management_screens(accounts, client, config, method, path):
    web_login(client, ADMIN_LOGIN, ADMIN_PASSWORD)
    before = accounts_rows(config.database_path)
    resp = client.request(method, path, follow_redirects=False)
    assert resp.status_code in (404, 405)
    assert accounts_rows(config.database_path) == before

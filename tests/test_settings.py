"""T-17 and operations 23, 24: settings — update time and notification threshold.

REQ-F-019, REQ-F-043 (default values), REQ-NF-031; UC-11 (steps 1–3, 3а);
BDD-068 (threshold part); contract scenarios П-25, П-26, П-32…П-35, Н-03, Н-16,
Н-17, Н-20, Н-21, Н-40.
"""

from __future__ import annotations

import re

import pytest
from helpers import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    API,
    NO_ACCESS,
    assert_problem,
    error_codes,
    forms,
    page_text,
)

SETTINGS = f"{API}/settings"
THRESHOLD_ERROR = "від 0,1 до 50"
TIME_ERROR = "ГГ:ХХ"


def settings(client) -> dict:
    resp = client.get(SETTINGS)
    assert resp.status_code == 200
    return resp.json()


def input_value(html: str, name: str) -> str | None:
    for form in forms(html):
        for field in form["inputs"]:
            if field.get("name") == name:
                return field.get("value")
    return None


def shows_threshold(html: str, value: str) -> bool:
    """The screen shows the threshold as "<value> %" — in the text or as the value
    of the form field (the "%" sign next to it)."""
    text = page_text(html)
    in_text = re.search(rf"(?<![\d,.]){re.escape(value)} ?%", text) is not None
    return in_text or input_value(html, "notification_threshold") == value


def shows_time(html: str, value: str) -> bool:
    return value in page_text(html) or input_value(html, "update_time") == value


def post_settings_form(client, **fields):
    return client.post("/settings", data=fields, follow_redirects=False)


# --- operation 23 GET /settings, REQ-F-043 defaults -------------------------------------


# П-25, REQ-F-043, REQ-F-019: on a new system the update time is 03:30 and the
# threshold 1 %.
def test_default_settings_api(admin_client):
    body = settings(admin_client)
    assert set(body) == {"update_time", "notification_threshold"}
    assert body["update_time"] == "03:30"
    assert body["notification_threshold"] == 1


# T-17: the settings screen of a new system shows 03:30 and 1 %.
def test_default_settings_screen(admin_client):
    page = admin_client.get("/settings")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert shows_time(page.text, "03:30")
    assert shows_threshold(page.text, "1")


# --- operation 24 PATCH /settings --------------------------------------------------------


# П-26, П-32, П-34, П-35, П-33, REQ-F-019: 2, 0.1, 0.5, 50 and 0.3 are accepted.
@pytest.mark.parametrize("value", [2, 0.1, 0.5, 50, 0.3, 49.9])
def test_threshold_accepted_api(admin_client, value):
    resp = admin_client.patch(SETTINGS, json={"notification_threshold": value})
    assert resp.status_code == 200
    assert resp.json()["notification_threshold"] == pytest.approx(value)
    assert resp.json()["update_time"] == "03:30"
    assert settings(admin_client)["notification_threshold"] == pytest.approx(value)


# Н-20, Н-21, REQ-F-019: 0, 0.05, 50.1, 1.25 — 422
# notification_threshold_out_of_range; the previous value stays.
@pytest.mark.parametrize("value", [0, 0.05, 50.1, 1.25, -1, 100])
def test_threshold_rejected_api(admin_client, value):
    admin_client.patch(SETTINGS, json={"notification_threshold": 2})
    resp = admin_client.patch(SETTINGS, json={"notification_threshold": value})
    problem = assert_problem(resp, 422, "validation_failed")
    assert error_codes(problem) == [
        ("notification_threshold", "notification_threshold_out_of_range")
    ]
    assert settings(admin_client)["notification_threshold"] == 2


# Contract: the threshold in the API is a JSON number; "0,5" as a string — 422.
@pytest.mark.parametrize("value", ["0,5", "0.5", None, True])
def test_threshold_wrong_type_api(admin_client, value):
    resp = admin_client.patch(SETTINGS, json={"notification_threshold": value})
    problem = assert_problem(resp, 422, "validation_failed")
    assert error_codes(problem)[0][0] == "notification_threshold"
    assert settings(admin_client)["notification_threshold"] == 1


# REQ-F-019: "03:30", "00:00", "23:59" are accepted.
@pytest.mark.parametrize("value", ["03:30", "00:00", "23:59", "14:05"])
def test_update_time_accepted_api(admin_client, value):
    resp = admin_client.patch(SETTINGS, json={"update_time": value})
    assert resp.status_code == 200
    assert resp.json() == {"update_time": value, "notification_threshold": 1}


# REQ-F-019: "3:30", "25:00" and other formats — 422 update_time_invalid; the
# previous value stays.
@pytest.mark.parametrize(
    "value", ["3:30", "25:00", "24:00", "03:60", "0330", "03:30:00", ""]
)
def test_update_time_rejected_api(admin_client, value):
    resp = admin_client.patch(SETTINGS, json={"update_time": value})
    problem = assert_problem(resp, 422, "validation_failed")
    assert ("update_time", "update_time_invalid") in error_codes(problem) or (
        "update_time",
        "required",
    ) in error_codes(problem)
    assert settings(admin_client)["update_time"] == "03:30"


# Н-17: both values wrong — 422 with both errors; nothing changes.
def test_both_settings_rejected_api(admin_client):
    resp = admin_client.patch(
        SETTINGS, json={"notification_threshold": 0.05, "update_time": "3:30"}
    )
    problem = assert_problem(resp, 422, "validation_failed")
    assert sorted(error_codes(problem)) == [
        ("notification_threshold", "notification_threshold_out_of_range"),
        ("update_time", "update_time_invalid"),
    ]
    assert settings(admin_client) == {
        "update_time": "03:30",
        "notification_threshold": 1,
    }


# REQ-F-019: one wrong value rejects the whole request; the valid one is not saved.
def test_one_wrong_value_saves_nothing(admin_client):
    resp = admin_client.patch(
        SETTINGS, json={"notification_threshold": 2, "update_time": "25:00"}
    )
    assert_problem(resp, 422, "validation_failed")
    assert settings(admin_client) == {
        "update_time": "03:30",
        "notification_threshold": 1,
    }


# Contract SettingsUpdate: unknown field — 422 unknown_field.
def test_settings_unknown_field(admin_client):
    resp = admin_client.patch(SETTINGS, json={"timezone": "Europe/Kyiv"})
    problem = assert_problem(resp, 422, "validation_failed")
    assert ("timezone", "unknown_field") in error_codes(problem)


# Н-16: Content-Type not JSON — 415.
def test_settings_body_not_json(admin_client):
    resp = admin_client.patch(
        SETTINGS,
        content="notification_threshold=2",
        headers={"Content-Type": "text/plain"},
    )
    assert_problem(resp, 415, "unsupported_media_type")
    assert settings(admin_client)["notification_threshold"] == 1


# BDD-068 (threshold part), Н-03, REQ-F-005: threshold 1 %; the manager asks for
# 2 % — 403 "немає доступу", threshold stays 1 %; the administrator — 200, 2 %.
def test_bdd068_threshold_by_role(admin_client, manager_client):
    resp = manager_client.patch(SETTINGS, json={"notification_threshold": 2})
    assert assert_problem(resp, 403, "forbidden")["detail"] == NO_ACCESS
    assert settings(admin_client)["notification_threshold"] == 1
    resp = admin_client.patch(SETTINGS, json={"notification_threshold": 2})
    assert resp.status_code == 200
    assert settings(admin_client)["notification_threshold"] == 2


# Н-40: the manager cannot read the settings either — 403.
def test_manager_cannot_read_settings(manager_client):
    resp = manager_client.get(SETTINGS)
    assert assert_problem(resp, 403, "forbidden")["detail"] == NO_ACCESS


# REQ-F-019: values are kept after a restart of the system.
def test_settings_kept_after_restart(admin_client, app_factory, client_factory):
    admin_client.patch(
        SETTINGS, json={"notification_threshold": 2.5, "update_time": "04:15"}
    )
    restarted = client_factory(app_factory())
    resp = restarted.post(
        f"{API}/sessions", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD}
    )
    assert resp.status_code == 201
    assert settings(restarted) == {
        "update_time": "04:15",
        "notification_threshold": 2.5,
    }
    page = restarted.get("/settings")
    assert shows_time(page.text, "04:15")
    assert shows_threshold(page.text, "2,5")


# --- the settings screen (web) ---------------------------------------------------------------


# REQ-F-019: the form has the update time and the threshold.
def test_settings_screen_has_form(admin_client):
    page = admin_client.get("/settings")
    names = {
        i.get("name")
        for f in forms(page.text)
        if f["method"] == "post"
        for i in f["inputs"]
    }
    assert {"update_time", "notification_threshold"} <= names


# REQ-F-019 criterion: "0.5" and "0,5" are accepted and shown as "0,5 %".
@pytest.mark.parametrize("typed", ["0.5", "0,5"])
def test_threshold_point_and_comma_screen(admin_client, typed):
    resp = post_settings_form(
        admin_client, update_time="03:30", notification_threshold=typed
    )
    assert resp.status_code in (302, 303)
    assert settings(admin_client)["notification_threshold"] == pytest.approx(0.5)
    html = admin_client.get("/settings").text
    assert shows_threshold(html, "0,5")
    assert not shows_threshold(html, "0.5")


# REQ-F-019 criterion: 0, 0,05, 50,1 and 1,25 are rejected with an explanation; the
# previous value stays; 0,1 and 50 are accepted.
@pytest.mark.parametrize(
    ("typed", "ok", "expected"),
    [
        ("0", False, 1),
        ("0,05", False, 1),
        ("50,1", False, 1),
        ("1,25", False, 1),
        ("abc", False, 1),
        ("", False, 1),
        ("0,1", True, 0.1),
        ("50", True, 50),
    ],
)
def test_threshold_limits_screen(admin_client, typed, ok, expected):
    resp = post_settings_form(
        admin_client, update_time="03:30", notification_threshold=typed
    )
    if ok:
        assert resp.status_code in (302, 303)
    else:
        assert resp.status_code not in (302, 303)
        if typed not in ("abc", ""):
            assert THRESHOLD_ERROR in page_text(resp.text)
    assert settings(admin_client)["notification_threshold"] == pytest.approx(expected)


# REQ-F-019 criterion: time "3:30" and "25:00" is rejected with an explanation,
# "03:30" is accepted.
@pytest.mark.parametrize(
    ("typed", "ok", "expected"),
    [("3:30", False, "03:30"), ("25:00", False, "03:30"), ("05:45", True, "05:45")],
)
def test_update_time_screen(admin_client, typed, ok, expected):
    resp = post_settings_form(
        admin_client, update_time=typed, notification_threshold="1"
    )
    if ok:
        assert resp.status_code in (302, 303)
    else:
        assert resp.status_code not in (302, 303)
        assert TIME_ERROR in page_text(resp.text)
    assert settings(admin_client)["update_time"] == expected


# UC-11 3а: after a rejection the other value is not saved either.
def test_rejected_form_saves_nothing(admin_client):
    post_settings_form(admin_client, update_time="25:00", notification_threshold="2")
    assert settings(admin_client) == {
        "update_time": "03:30",
        "notification_threshold": 1,
    }


# REQ-F-005, REQ-NF-003: the manager on the settings screen sees "немає доступу";
# a direct form request changes nothing.
def test_manager_settings_screen_no_access(admin_client, manager_client):
    page = manager_client.get("/settings")
    assert page.status_code == 403
    assert NO_ACCESS in page_text(page.text)
    assert "03:30" not in page.text
    resp = post_settings_form(
        manager_client, update_time="05:00", notification_threshold="2"
    )
    assert resp.status_code == 403
    assert NO_ACCESS in page_text(resp.text)
    assert settings(admin_client) == {
        "update_time": "03:30",
        "notification_threshold": 1,
    }

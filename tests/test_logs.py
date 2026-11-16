"""A-05 basis: action log and technical log (REQ-NF-018, REQ-NF-032, REQ-NF-033).

Only what exists in block B1.1: HTTP request records, the request identifier,
technical records of an unexpected exception and log write failures. Login,
action and run records are tested in B1.2 and B2.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest

# Common fields of every record (Р-126): time, level, event code, login, role,
# request identifier, result. Event fields come in addition.
COMMON_FIELDS = {"time", "level", "event", "login", "role", "request_id", "result"}
HTTP_EVENT = "http_request"


def http_records(records: list[dict], path: str) -> list[dict]:
    return [r for r in records if r["event"] == HTTP_EVENT and r.get("path") == path]


# REQ-NF-032, Р-126: every action log line is one JSON object with the common fields.
def test_action_log_lines_are_json_with_common_fields(client, config, read_log):
    client.get("/api/v1/no-such-resource")
    client.get("/api/v1/other-missing")
    records = read_log(config.action_log_path)
    assert len(records) >= 2
    for record in records:
        assert COMMON_FIELDS <= set(record)
        assert isinstance(record["level"], str) and record["level"]
        assert isinstance(record["event"], str) and record["event"]


# REQ-NF-032: an HTTP request record has method, path, status code, duration in
# ms and an empty login (and role) without a session.
def test_http_request_record_without_session(client, config, read_log):
    client.get("/api/v1/no-such-resource")
    (record,) = http_records(
        read_log(config.action_log_path), "/api/v1/no-such-resource"
    )
    assert record["method"] == "GET"
    assert record["status"] == 404
    assert isinstance(record["duration_ms"], int) and record["duration_ms"] >= 0
    assert record["login"] is None
    assert record["role"] is None


# REQ-NF-032: the method of each request is recorded as sent.
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_http_request_record_keeps_method(client, config, read_log, method):
    client.request(method, "/api/v1/no-such-resource")
    (record,) = http_records(
        read_log(config.action_log_path), "/api/v1/no-such-resource"
    )
    assert record["method"] == method


# REQ-NF-032: the path is recorded without the query string.
def test_http_request_record_path_has_no_query_string(client, config, read_log):
    client.get("/api/v1/no-such-resource?q=secret-filter&page=2")
    records = read_log(config.action_log_path)
    assert http_records(records, "/api/v1/no-such-resource")
    raw = config.action_log_path.read_text(encoding="utf-8")
    assert "secret-filter" not in raw
    assert "page=2" not in raw


# REQ-NF-032: requests outside /api/v1 (web interface) are recorded too.
def test_web_request_is_recorded(client, config, read_log):
    resp = client.get("/no-such-page", follow_redirects=False)
    (record,) = http_records(read_log(config.action_log_path), "/no-such-page")
    assert record["status"] == resp.status_code


# REQ-NF-032, Р-126: time is ISO 8601 with the Kyiv offset, +03:00 in summer.
def test_record_time_has_kyiv_summer_offset(client, config, read_log):
    client.get("/api/v1/no-such-resource")
    (record,) = http_records(
        read_log(config.action_log_path), "/api/v1/no-such-resource"
    )
    moment = datetime.fromisoformat(record["time"])
    assert moment.utcoffset() == timedelta(hours=3)
    assert moment == datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    assert record["time"].startswith("2026-07-15T12:00:00")


# REQ-NF-032, Р-126: +02:00 in winter (controlled clock, no waiting).
def test_record_time_has_kyiv_winter_offset(
    app_factory, client_factory, spm_clock_module, config, read_log
):
    winter = spm_clock_module.ManualClock(datetime(2026, 1, 15, 10, 0, tzinfo=UTC))
    tc = client_factory(app_factory(clk=winter))
    tc.get("/api/v1/no-such-resource")
    (record,) = http_records(
        read_log(config.action_log_path), "/api/v1/no-such-resource"
    )
    moment = datetime.fromisoformat(record["time"])
    assert moment.utcoffset() == timedelta(hours=2)
    assert record["time"].startswith("2026-01-15T12:00:00")


# REQ-NF-032, Р-126: the record time follows the controlled clock (DST switch
# 2026-10-25 04:00 Kyiv: +03:00 before, +02:00 after).
def test_record_time_follows_clock_across_dst_switch(
    app_factory, client_factory, spm_clock_module, config, read_log
):
    clk = spm_clock_module.ManualClock(datetime(2026, 10, 24, 23, 30, tzinfo=UTC))
    tc = client_factory(app_factory(clk=clk))
    tc.get("/api/v1/before-switch")
    clk.advance(timedelta(hours=2))
    tc.get("/api/v1/after-switch")
    records = read_log(config.action_log_path)
    (before,) = http_records(records, "/api/v1/before-switch")
    (after,) = http_records(records, "/api/v1/after-switch")
    assert before["time"].startswith("2026-10-25T02:30:00+03:00")
    assert after["time"].startswith("2026-10-25T03:30:00+02:00")


# REQ-NF-032, Р-126: each HTTP request has its own request identifier.
def test_different_requests_have_different_identifiers(client, config, read_log):
    for _ in range(3):
        client.get("/api/v1/no-such-resource")
    records = http_records(read_log(config.action_log_path), "/api/v1/no-such-resource")
    ids = [r["request_id"] for r in records]
    assert len(ids) == 3
    assert all(isinstance(i, str) and i for i in ids)
    assert len(set(ids)) == 3


# REQ-NF-032, Р-126: the identifier is not returned in the response.
def test_identifier_is_not_in_response(client, config, read_log):
    resp = client.get("/api/v1/no-such-resource")
    (record,) = http_records(
        read_log(config.action_log_path), "/api/v1/no-such-resource"
    )
    request_id = record["request_id"]
    assert request_id not in resp.text
    assert all(request_id not in value for value in resp.headers.values())


# REQ-NF-018, Р-128: every technical log line is JSON with the same common fields.
def test_technical_log_lines_are_json_with_common_fields(
    app, client, config, read_log, add_failing_route
):
    add_failing_route(app, "/api/v1/test-failure", "boom-marker")
    client.get("/api/v1/test-failure")
    records = read_log(config.technical_log_path)
    assert records
    for record in records:
        assert COMMON_FIELDS <= set(record)


# REQ-NF-018: an exception during a request gives a technical record with the
# same request identifier as the action log record of that request, and a
# description of the error.
def test_exception_record_shares_request_identifier(
    app, client, config, read_log, add_failing_route
):
    add_failing_route(app, "/api/v1/test-failure", "boom-marker")
    client.get("/api/v1/no-such-resource")
    client.get("/api/v1/test-failure")
    (http,) = http_records(read_log(config.action_log_path), "/api/v1/test-failure")
    assert http["status"] == 500
    technical = [
        r
        for r in read_log(config.technical_log_path)
        if r["request_id"] == http["request_id"]
    ]
    assert technical
    assert any("boom-marker" in str(r) for r in technical)
    others = http_records(read_log(config.action_log_path), "/api/v1/no-such-resource")
    other_ids = {r["request_id"] for r in others}
    assert not [
        r for r in read_log(config.technical_log_path) if r["request_id"] in other_ids
    ]


# REQ-NF-018, REQ-NF-032, Р-125: no password, session cookie value or whole
# request body in either log, also when the exception text and stack trace
# would carry them.
def test_no_password_or_cookie_in_logs_after_exception(
    app, client, config, add_failing_route
):
    password = "Pw-" + secrets.token_hex(8)
    cookie = "ck-" + secrets.token_hex(8)
    add_failing_route(
        app,
        "/api/v1/test-failure",
        f"boom-marker password={password} spm_session={cookie}",
    )
    client.cookies.set("spm_session", cookie)
    client.post(
        "/api/v1/test-failure",
        json={"login": "admin", "password": password, "note": "whole-body-marker"},
    )
    for path in (config.action_log_path, config.technical_log_path):
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        assert password not in text
        assert cookie not in text
        assert "whole-body-marker" not in text
    assert "boom-marker" in config.technical_log_path.read_text(encoding="utf-8")


def _unwritable(tmp_path, name):
    target = tmp_path / name
    target.mkdir()  # a directory cannot be opened for appending
    return target


# REQ-NF-033, Р-127: if writing the action log fails, the response is the same.
def test_action_log_failure_keeps_response(
    config, config_factory, app_factory, client_factory, tmp_path
):
    normal = client_factory(app_factory()).get("/api/v1/no-such-resource")
    broken_cfg = config_factory(
        action_log_path=_unwritable(tmp_path, "actions-dir"),
        database_path=tmp_path / "other.db",
    )
    resp = client_factory(app_factory(broken_cfg)).get("/api/v1/no-such-resource")
    assert resp.status_code == normal.status_code == 404
    assert resp.json() == normal.json()
    assert resp.headers["content-type"] == normal.headers["content-type"]


# REQ-NF-033, Р-127: if writing the technical log fails, the response is the same.
def test_technical_log_failure_keeps_response(
    config_factory, app_factory, client_factory, add_failing_route, tmp_path
):
    normal_app = app_factory()
    add_failing_route(normal_app, "/api/v1/test-failure", "boom-marker")
    normal = client_factory(normal_app).get("/api/v1/test-failure")
    broken_cfg = config_factory(
        technical_log_path=_unwritable(tmp_path, "technical-dir"),
        action_log_path=_unwritable(tmp_path, "actions-dir"),
        database_path=tmp_path / "other.db",
    )
    broken_app = app_factory(broken_cfg)
    add_failing_route(broken_app, "/api/v1/test-failure", "boom-marker")
    resp = client_factory(broken_app).get("/api/v1/test-failure")
    assert resp.status_code == normal.status_code == 500
    assert resp.json() == normal.json()

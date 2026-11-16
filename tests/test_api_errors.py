"""T-52 (part without login): /api/v1 prefix and the API error model.

REQ-NF-031, REQ-NF-001, REQ-NF-018; contract spec/openapi.yaml, schema Problem.
"""

from __future__ import annotations

import re

import pytest

PROBLEM_TYPE = "application/problem+json"
PROBLEM_FIELDS = {"type", "title", "status", "detail", "code"}
PROBLEM_OPTIONAL = {"errors"}
# Problem.title enum of the contract: Ukrainian names of HTTP statuses.
TITLES = {404: "Не знайдено", 500: "Внутрішня помилка сервера"}
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")


def assert_problem(resp, status: int, code: str) -> dict:
    assert resp.status_code == status
    assert resp.headers["content-type"].split(";")[0].strip() == PROBLEM_TYPE
    body = resp.json()
    assert PROBLEM_FIELDS <= set(body)
    assert set(body) <= PROBLEM_FIELDS | PROBLEM_OPTIONAL
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["code"] == code
    assert body["title"] == TITLES[status]
    assert isinstance(body["detail"], str) and CYRILLIC.search(body["detail"])
    return body


# REQ-NF-031, contract NotFound; scenario Н-07 (here without a session: an
# unknown address is not a contract operation, so no session check applies).
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_unknown_api_address_is_404_problem(client, method):
    resp = client.request(method, "/api/v1/no-such-resource")
    assert_problem(resp, 404, "not_found")


# REQ-NF-031: nested unknown address under the prefix is also 404 not_found.
def test_unknown_nested_api_address_is_404_problem(client):
    assert_problem(client.get("/api/v1/no/such/resource"), 404, "not_found")


# REQ-NF-031: the API lives under /api/v1; the same unknown address outside
# the prefix is not answered by the API error model.
def test_api_error_model_only_under_api_v1_prefix(client):
    resp = client.get("/no-such-resource", follow_redirects=False)
    assert resp.status_code != 200
    content_type = resp.headers.get("content-type", "")
    assert not content_type.startswith(PROBLEM_TYPE)


# REQ-NF-031, contract InternalServerError (example internal_error), REQ-NF-001:
# an artificial failure gives 500 internal_error without internal details.
def test_failure_gives_500_problem_without_details(app, client, add_failing_route):
    add_failing_route(app, "/api/v1/test-failure", "boom-internal-detail in table x")
    resp = client.get("/api/v1/test-failure")
    body = assert_problem(resp, 500, "internal_error")
    text = resp.text
    for leaked in ("boom-internal-detail", "table x", "RuntimeError", "Traceback"):
        assert leaked not in text
    assert "failing_endpoint" not in text
    assert "errors" not in body or body["errors"] in ([], None)


# REQ-NF-031: the 500 answer is the same for every request method.
def test_failure_gives_500_problem_for_post(app, client, add_failing_route):
    add_failing_route(app, "/api/v1/test-failure", "boom")
    resp = client.post("/api/v1/test-failure", json={"a": 1})
    assert_problem(resp, 500, "internal_error")

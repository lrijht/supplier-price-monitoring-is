"""A-05 for block B3: deactivation and activation through the screens, the
manager's refused deactivation, the HTTP records of the view operations, and no
action log record in any screen or operation of the block.

REQ-NF-032 (Р-123…Р-126). B1 checked these actions through the API
(test_action_log_b1.py); here — the forms of the screens "постачальники" and
"матеріали" (UC-06 2а/2б, UC-07 2б/2в) and the new views.
"""

from __future__ import annotations

import pytest
from helpers import API, create_material, create_supplier, page_text

REDIRECT = (302, 303)


def events(records: list[dict], event: str) -> list[dict]:
    return [r for r in records if r["event"] == event]


def http_records(records: list[dict], method: str, path: str) -> list[dict]:
    return [
        r
        for r in records
        if r["event"] == "http_request" and r["method"] == method and r["path"] == path
    ]


def supplier_form(active: bool) -> dict:
    data = {
        "name": "Альфа",
        "catalog_url": "http://localhost:8001/a",
        "parser": "table_layout",
    }
    if active:
        data["active"] = "on"
    return data


def material_form(active: bool) -> dict:
    data = {"name": "М1", "unit": "шт"}
    if active:
        data["active"] = "on"
    return data


# REQ-NF-032: deactivation and activation of a supplier and of a material through
# the form — records supplier_deactivate, supplier_activate, material_deactivate,
# material_activate with the login, the role, the object (type and id), result
# "success" and the request id of the form's HTTP request.
@pytest.mark.parametrize("kind", ["supplier", "material"])
def test_form_deactivate_activate_records(admin_client, config, read_log, kind):
    if kind == "supplier":
        object_id = create_supplier(
            admin_client, "Альфа", catalog_url="http://localhost:8001/a"
        )["id"]
        form = supplier_form
    else:
        object_id = create_material(admin_client, "М1")["id"]
        form = material_form
    path = f"/{kind}s/{object_id}"
    for active in (False, True):
        resp = admin_client.post(path, data=form(active), follow_redirects=False)
        assert resp.status_code in REDIRECT
    records = read_log(config.action_log_path)
    posts = http_records(records, "POST", path)
    assert len(posts) == 2
    for action, post in zip(
        (f"{kind}_deactivate", f"{kind}_activate"), posts, strict=True
    ):
        (record,) = events(records, action)
        assert (record["login"], record["role"]) == ("admin", "admin")
        assert record["result"] == "success"
        assert (record["object_type"], record["object_id"]) == (kind, object_id)
        assert record["request_id"] == post["request_id"]
    assert events(records, f"{kind}_update") == []


# REQ-NF-032, REQ-F-005: the manager's deactivation through the form — one
# "немає доступу" record with the supplier as the object, and no record of the
# deactivation itself; the supplier stays active.
def test_manager_form_deactivation_access_denied(
    admin_client, manager_client, config, read_log
):
    sid = create_supplier(admin_client, "Альфа", catalog_url="http://localhost:8001/a")[
        "id"
    ]
    resp = manager_client.post(
        f"/suppliers/{sid}", data=supplier_form(False), follow_redirects=False
    )
    assert resp.status_code == 403
    records = read_log(config.action_log_path)
    (record,) = events(records, "access_denied")
    assert (record["login"], record["role"]) == ("manager", "manager")
    assert (record["object_type"], record["object_id"]) == ("supplier", sid)
    assert isinstance(record["action"], str) and record["action"].startswith(
        "supplier_"
    )
    (post,) = http_records(records, "POST", f"/suppliers/{sid}")
    assert record["request_id"] == post["request_id"]
    assert events(records, "supplier_deactivate") == []
    assert admin_client.get(f"{API}/suppliers/{sid}").json()["active"] is True


# REQ-NF-032: requests of the view operations and screens are recorded with the
# path without the query string, the status and the login.
@pytest.mark.parametrize(
    ("url", "path"),
    [
        (f"{API}/events?kind=appeared&page=1", f"{API}/events"),
        (f"{API}/material-comparisons?q=лдсп", f"{API}/material-comparisons"),
        ("/events?kind=appeared", "/events"),
        ("/price-history?period=all", "/price-history"),
    ],
)
def test_view_requests_recorded_without_query(
    manager_client, config, read_log, url, path
):
    resp = manager_client.get(url)
    records = http_records(read_log(config.action_log_path), "GET", path)
    assert records, f"no http_request record for {path}"
    record = records[-1]
    assert record["status"] == resp.status_code
    assert (record["login"], record["role"]) == ("manager", "manager")


# REQ-NF-032 criterion: no screen of REQ-NF-003 and no operation returns action
# log records — no request id of the log is in the answers: all 11 screens and
# every reading operation of the contract (the CSV export included), after
# changes, a run and a refused manager request have written records.
def test_views_do_not_return_action_log(admin_client, manager_client, config, read_log):
    from helpers_b2 import start_manual, wait_run

    mid = create_material(admin_client, "М1")["id"]
    sid = create_supplier(admin_client, "Альфа")["id"]
    admin_client.patch(f"{API}/settings", json={"notification_threshold": 2})
    run_id = wait_run(admin_client, start_manual(admin_client)["id"])["id"]
    assert manager_client.patch(f"{API}/settings", json={}).status_code == 403
    urls = [
        f"{API}/material-comparisons",
        f"{API}/material-comparisons/{mid}",
        f"{API}/materials/{mid}/price-history?period=all",
        f"{API}/events",
        f"{API}/attention-items",
        "/material-comparisons",
        f"/material-comparisons/{mid}",
        f"/price-history?material_id={mid}&period=all",
        "/events",
        "/attention-items",
        # the other screens of REQ-NF-003
        "/supplier-update-statuses",
        "/suppliers",
        "/materials",
        "/unlinked-items",
        "/run-log-entries",
        "/settings",
        # the other reading operations of spec/openapi.yaml
        f"{API}/sessions/current",
        f"{API}/suppliers",
        f"{API}/suppliers/{sid}",
        f"{API}/parsers",
        f"{API}/materials",
        f"{API}/materials/{mid}",
        f"{API}/materials/{mid}/links",
        f"{API}/unlinked-items",
        f"{API}/exports/material-comparisons",
        f"{API}/supplier-update-statuses",
        f"{API}/settings",
        f"{API}/runs/{run_id}",
        f"{API}/run-log-entries",
    ]
    answers = [admin_client.get(u) for u in urls] + [manager_client.get(urls[0])]
    assert all(resp.status_code == 200 for resp in answers), [
        (u, r.status_code) for u, r in zip(urls, answers, strict=False)
    ]
    # Ids long enough not to match by chance (a uuid or a long token).
    records = read_log(config.action_log_path)
    assert records
    ids = {
        str(r["request_id"]) for r in records if len(str(r["request_id"] or "")) >= 8
    }
    for resp in answers:
        body = resp.text
        assert not [i for i in ids if i in body]
        for word in ("http_request", "settings_update", "request_id"):
            assert word not in page_text(body) and word not in body

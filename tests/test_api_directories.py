"""T-53 (operations 4–14, 16, 17): suppliers, materials, parsers, links, unlinked
items through the API.

REQ-NF-031, REQ-F-070 and the REQ-ID of the operations (docs/api/resources.md,
section 3); BDD-070, BDD-027, BDD-032, BDD-037, BDD-063; contract scenarios from
tests/contract/scenarios.json (ID above each test). Operation 15 (attention
items) is block B3.
"""

from __future__ import annotations

import pytest
from helpers import (
    API,
    NO_ACCESS,
    all_pages,
    assert_problem,
    create_material,
    create_supplier,
    error_codes,
    link,
)

SUPPLIER_FIELDS = {"id", "name", "catalog_url", "parser", "active", "last_update_date"}
MATERIAL_FIELDS = {"id", "name", "unit", "active", "linked_items_count"}
PAGE_FIELDS = {"items", "page", "page_size", "total_items", "total_pages"}
# REQ-F-057 criterion (П-3): the alphabetical order of these names.
ALPHABET_NAMES = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
ALPHABET_ORDER = ["2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак", "Alpha"]


@pytest.fixture
def world(admin_client, add_item):
    """Suppliers А, Б, В; materials М1 (шт), М2 (п.м.); unlinked items."""
    w = {}
    w["A"] = create_supplier(
        admin_client, "Альфа", catalog_url="http://localhost:8001/a"
    )
    w["B"] = create_supplier(
        admin_client,
        "Бета",
        catalog_url="http://localhost:8001/b",
        parser="cards_layout",
    )
    w["V"] = create_supplier(
        admin_client,
        "Вега",
        catalog_url="http://localhost:8001/c",
        parser="list_layout",
    )
    w["M1"] = create_material(admin_client, "ЛДСП Білий 18 мм", unit="шт")
    w["M2"] = create_material(admin_client, "Кромка біла 2 мм", unit="п.м.")
    w["A1"] = add_item(w["A"]["id"], "А-1", "Плита ЛДСП біла 18", "Шт.")
    w["A2"] = add_item(w["A"]["id"], "А-2", "Плита ЛДСП сіра 18", "шт")
    w["B1"] = add_item(w["B"]["id"], "Б-1", "ЛДСП білий 18 мм", "шт")
    w["B2"] = add_item(w["B"]["id"], "Б-2", "Кромка ПВХ біла", "м.п.")
    w["B3"] = add_item(w["B"]["id"], "Б-3", "Кромка ПВХ дуб", "п.м.")
    return w


def unlinked_ids(client) -> set[int]:
    return {
        i["supplier_item"]["id"] for i in all_pages(client, f"{API}/unlinked-items")
    }


def link_ids(client, material_id: int) -> set[int]:
    items = all_pages(client, f"{API}/materials/{material_id}/links")
    return {i["supplier_item"]["id"] for i in items}


def get_supplier(client, supplier_id: int) -> dict:
    return client.get(f"{API}/suppliers/{supplier_id}").json()


def get_material(client, material_id: int) -> dict:
    return client.get(f"{API}/materials/{material_id}").json()


# --- 4 GET /suppliers ---------------------------------------------------------------


# П-04, REQ-F-007, REQ-F-057, REQ-F-068: page of suppliers with all fields; a
# supplier not updated yet has last_update_date null.
def test_list_suppliers_admin(admin_client, world):
    body = admin_client.get(f"{API}/suppliers").json()
    assert set(body) == PAGE_FIELDS
    assert body["page"] == 1 and body["page_size"] == 50
    assert body["total_items"] == 3 and body["total_pages"] == 1
    assert [s["name"] for s in body["items"]] == ["Альфа", "Бета", "Вега"]
    for item in body["items"]:
        assert set(item) == SUPPLIER_FIELDS
        assert item["last_update_date"] is None
    assert body["items"][0]["catalog_url"] == "http://localhost:8001/a"
    assert body["items"][0]["parser"] == "table_layout"


# П-05, BDD-070, REQ-F-070: the manager gets suppliers, deactivated included, with
# only id, name and active.
def test_list_suppliers_manager_bdd070(admin_client, manager_client, world):
    admin_client.patch(f"{API}/suppliers/{world['V']['id']}", json={"active": False})
    body = manager_client.get(f"{API}/suppliers").json()
    by_name = {s["name"]: s for s in body["items"]}
    assert set(by_name) == {"Альфа", "Бета", "Вега"}
    assert by_name["Вега"]["active"] is False
    for item in body["items"]:
        assert set(item) == {"id", "name", "active"}


# REQ-F-007 (operation 4, parameter active): selection by the flag "active".
@pytest.mark.parametrize(
    ("active", "names"), [("true", ["Альфа", "Бета"]), ("false", ["Вега"])]
)
def test_list_suppliers_active_filter(admin_client, world, active, names):
    admin_client.patch(f"{API}/suppliers/{world['V']['id']}", json={"active": False})
    body = admin_client.get(f"{API}/suppliers?active={active}").json()
    assert [s["name"] for s in body["items"]] == names


# REQ-F-057, П-3: suppliers in the alphabetical order of the criterion.
def test_list_suppliers_alphabetical_order(admin_client):
    for i, name in enumerate(ALPHABET_NAMES):
        create_supplier(admin_client, name, catalog_url=f"http://localhost:8001/{i}")
    body = admin_client.get(f"{API}/suppliers").json()
    assert [s["name"] for s in body["items"]] == ALPHABET_ORDER


# REQ-F-057: 50 per page; a page beyond the end — 200 with empty items.
def test_list_suppliers_pages(admin_client):
    names = [f"Постачальник {i:03d}" for i in range(55)]
    for i, name in enumerate(names):
        create_supplier(admin_client, name, catalog_url=f"http://localhost:8001/{i}")
    first = admin_client.get(f"{API}/suppliers").json()
    second = admin_client.get(f"{API}/suppliers?page=2").json()
    beyond = admin_client.get(f"{API}/suppliers?page=3")
    assert [s["name"] for s in first["items"]] == names[:50]
    assert [s["name"] for s in second["items"]] == names[50:]
    assert (first["total_items"], first["total_pages"]) == (55, 2)
    assert second["page"] == 2
    assert beyond.status_code == 200
    assert beyond.json()["items"] == [] and beyond.json()["page"] == 3


# Н-24: page=abc — 422 page_invalid; also 0 and -1. active=maybe — invalid_type.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("page=abc", ("page", "page_invalid")),
        ("page=0", ("page", "page_invalid")),
        ("page=-1", ("page", "page_invalid")),
        ("active=maybe", ("active", "invalid_type")),
    ],
)
def test_list_suppliers_bad_parameters(admin_client, query, expected):
    body = assert_problem(
        admin_client.get(f"{API}/suppliers?{query}"), 422, "validation_failed"
    )
    assert expected in error_codes(body)


# --- 5 POST /suppliers ----------------------------------------------------------------


# П-06, REQ-F-007: the supplier is created with the entered values; 201, Location.
def test_create_supplier(admin_client):
    body = {
        "name": "Альфа",
        "catalog_url": "http://localhost:8001/a",
        "parser": "table_layout",
        "active": True,
    }
    resp = admin_client.post(f"{API}/suppliers", json=body)
    assert resp.status_code == 201
    created = resp.json()
    assert set(created) == SUPPLIER_FIELDS
    assert {k: created[k] for k in body} == body
    assert created["last_update_date"] is None
    assert resp.headers["location"] == f"{API}/suppliers/{created['id']}"
    assert get_supplier(admin_client, created["id"]) == created


# REQ-F-007: an https address is accepted as well; a supplier can be created inactive.
def test_create_supplier_https_inactive(admin_client):
    created = create_supplier(
        admin_client, "Дельта", catalog_url="https://localhost:8443/d", active=False
    )
    assert created["active"] is False


# Н-11, REQ-F-007: "альфа" when "Альфа" exists — 409 supplier_name_taken.
@pytest.mark.parametrize("name", ["альфа", "АЛЬФА", "Альфа"])
def test_create_supplier_name_taken(admin_client, world, name):
    body = {
        "name": name,
        "catalog_url": "http://localhost:8001/a3",
        "parser": "table_layout",
        "active": True,
    }
    resp = admin_client.post(f"{API}/suppliers", json=body)
    problem = assert_problem(resp, 409, "supplier_name_taken")
    assert error_codes(problem) == [("name", "supplier_name_taken")]
    assert admin_client.get(f"{API}/suppliers").json()["total_items"] == 3


# Н-18, REQ-F-007: empty name, "catalog.html", "ftp://localhost/a", unknown
# parser — 422 with the reason; nothing created.
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": ""}, ("name", "required")),
        ({"catalog_url": "catalog.html"}, ("catalog_url", "catalog_url_invalid")),
        ({"catalog_url": "ftp://localhost/a"}, ("catalog_url", "catalog_url_invalid")),
        ({"catalog_url": ""}, ("catalog_url", "required")),
        ({"parser": "xml_layout"}, ("parser", "parser_unknown")),
        ({"active": "так"}, ("active", "invalid_type")),
        ({"colour": "синій"}, ("colour", "unknown_field")),
        ({"id": 7}, ("id", "read_only_field")),
        ({"last_update_date": "2026-10-05"}, ("last_update_date", "read_only_field")),
    ],
)
def test_create_supplier_invalid(admin_client, change, expected):
    body = {
        "name": "Дельта",
        "catalog_url": "http://localhost:8001/a",
        "parser": "table_layout",
        "active": True,
    } | change
    problem = assert_problem(
        admin_client.post(f"{API}/suppliers", json=body), 422, "validation_failed"
    )
    assert expected in error_codes(problem)
    assert admin_client.get(f"{API}/suppliers").json()["total_items"] == 0


# REQ-F-007: required fields missing — 422 required for each.
def test_create_supplier_missing_fields(admin_client):
    problem = assert_problem(
        admin_client.post(f"{API}/suppliers", json={}), 422, "validation_failed"
    )
    fields = {f for f, c in error_codes(problem) if c == "required"}
    assert {"name", "catalog_url", "parser", "active"} <= fields


# --- 6 GET /suppliers/{id} --------------------------------------------------------------


# П-07: one supplier with all fields.
def test_get_supplier(admin_client, world):
    resp = admin_client.get(f"{API}/suppliers/{world['A']['id']}")
    assert resp.status_code == 200
    assert resp.json() == world["A"]


# Н-05: unknown supplier — 404 not_found.
def test_get_supplier_not_found(admin_client):
    assert_problem(admin_client.get(f"{API}/suppliers/999"), 404, "not_found")


# Н-19: /suppliers/abc — 422 invalid_type for supplier_id, not 404.
def test_get_supplier_invalid_id(admin_client):
    problem = assert_problem(
        admin_client.get(f"{API}/suppliers/abc"), 422, "validation_failed"
    )
    assert error_codes(problem) == [("supplier_id", "invalid_type")]


# --- 7 PATCH /suppliers/{id} --------------------------------------------------------------


# П-08, REQ-F-010: deactivation removes "active"; activation returns it.
def test_update_supplier_deactivate_and_activate(admin_client, world):
    sid = world["A"]["id"]
    resp = admin_client.patch(f"{API}/suppliers/{sid}", json={"active": False})
    assert resp.status_code == 200
    assert resp.json()["active"] is False
    assert get_supplier(admin_client, sid)["active"] is False
    resp = admin_client.patch(f"{API}/suppliers/{sid}", json={"active": True})
    assert resp.json()["active"] is True


# REQ-F-007: name, address and parser are changed; other fields stay.
def test_update_supplier_fields(admin_client, world):
    sid = world["A"]["id"]
    change = {
        "name": "Альфа-Плюс",
        "catalog_url": "https://localhost:8443/a2",
        "parser": "cards_layout",
    }
    resp = admin_client.patch(f"{API}/suppliers/{sid}", json=change)
    assert resp.status_code == 200
    assert resp.json() == world["A"] | change
    assert get_supplier(admin_client, sid) == world["A"] | change


# REQ-F-007: renaming a supplier to its own name in another case is no conflict.
def test_update_supplier_own_name_other_case(admin_client, world):
    resp = admin_client.patch(
        f"{API}/suppliers/{world['A']['id']}", json={"name": "АЛЬФА"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "АЛЬФА"


# REQ-F-007: renaming to another supplier's name (any case) — 409; nothing changes.
def test_update_supplier_name_taken(admin_client, world):
    sid = world["B"]["id"]
    resp = admin_client.patch(f"{API}/suppliers/{sid}", json={"name": "альфа"})
    problem = assert_problem(resp, 409, "supplier_name_taken")
    assert error_codes(problem) == [("name", "supplier_name_taken")]
    assert get_supplier(admin_client, sid) == world["B"]


# Н-26 and REQ-F-007: read-only and invalid fields — 422; nothing changes.
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"last_update_date": "2026-10-05"}, ("last_update_date", "read_only_field")),
        ({"id": 99}, ("id", "read_only_field")),
        ({"name": ""}, ("name", "required")),
        ({"catalog_url": "catalog.html"}, ("catalog_url", "catalog_url_invalid")),
        ({"parser": "xml_layout"}, ("parser", "parser_unknown")),
        ({"comment": "x"}, ("comment", "unknown_field")),
    ],
)
def test_update_supplier_invalid(admin_client, world, change, expected):
    sid = world["A"]["id"]
    problem = assert_problem(
        admin_client.patch(f"{API}/suppliers/{sid}", json=change),
        422,
        "validation_failed",
    )
    assert expected in error_codes(problem)
    assert get_supplier(admin_client, sid) == world["A"]


# Operation 7: unknown supplier — 404; id not an integer — 422.
def test_update_supplier_not_found_and_bad_id(admin_client):
    assert_problem(
        admin_client.patch(f"{API}/suppliers/999", json={"active": False}),
        404,
        "not_found",
    )
    problem = assert_problem(
        admin_client.patch(f"{API}/suppliers/x1", json={"active": False}),
        422,
        "validation_failed",
    )
    assert error_codes(problem) == [("supplier_id", "invalid_type")]


# --- 8 GET /parsers -------------------------------------------------------------------------


# П-09, REQ-F-007, REQ-NF-006: the list of available parsers, one per simulator
# supplier.
def test_list_parsers(admin_client):
    resp = admin_client.get(f"{API}/parsers")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {"table_layout", "cards_layout", "list_layout"} <= set(items)
    assert all(isinstance(i, str) for i in items)


# --- 9 GET /materials ----------------------------------------------------------------------


# П-10, REQ-F-008, REQ-F-068: materials with all fields; search "лдсп" ignores case.
def test_list_materials_admin_search(admin_client, world):
    body = admin_client.get(f"{API}/materials?q=лдсп").json()
    assert [m["name"] for m in body["items"]] == ["ЛДСП Білий 18 мм"]
    assert set(body["items"][0]) == MATERIAL_FIELDS
    assert body["items"][0]["linked_items_count"] == 0
    assert body["total_items"] == 1


# REQ-F-057, REQ-F-069: search finds text inside the name, in any case.
@pytest.mark.parametrize(
    ("q", "names"), [("БІЛ", ["Кромка біла 2 мм", "ЛДСП Білий 18 мм"]), ("xyz", [])]
)
def test_list_materials_search_substring(admin_client, world, q, names):
    body = admin_client.get(f"{API}/materials?q={q}").json()
    assert [m["name"] for m in body["items"]] == names


# П-36, П-37, BDD-070, REQ-F-070: the manager gets М1 and deactivated М2 with only
# id, name, active; with active=true — only active ones.
def test_list_materials_manager_bdd070(admin_client, manager_client, world):
    admin_client.patch(f"{API}/materials/{world['M2']['id']}", json={"active": False})
    body = manager_client.get(f"{API}/materials").json()
    names = {m["name"]: m for m in body["items"]}
    assert set(names) == {"ЛДСП Білий 18 мм", "Кромка біла 2 мм"}
    assert names["Кромка біла 2 мм"]["active"] is False
    for item in body["items"]:
        assert set(item) == {"id", "name", "active"}
    active = manager_client.get(f"{API}/materials?active=true").json()
    assert [m["name"] for m in active["items"]] == ["ЛДСП Білий 18 мм"]


# REQ-F-057 criterion: 120 materials — pages of 50, 50, 20 in alphabetical order.
def test_list_materials_120_pages(admin_client):
    names = [f"Матеріал {i:03d}" for i in range(120)]
    for name in reversed(names):
        create_material(admin_client, name)
    pages = [admin_client.get(f"{API}/materials?page={p}").json() for p in (1, 2, 3)]
    assert [[m["name"] for m in p["items"]] for p in pages] == [
        names[:50],
        names[50:100],
        names[100:],
    ]
    assert pages[0]["total_pages"] == 3 and pages[0]["total_items"] == 120
    assert admin_client.get(f"{API}/materials?page=4").json()["items"] == []


# REQ-F-057, П-3: materials in the alphabetical order of the criterion.
def test_list_materials_alphabetical_order(admin_client):
    for name in ALPHABET_NAMES:
        create_material(admin_client, name)
    body = admin_client.get(f"{API}/materials").json()
    assert [m["name"] for m in body["items"]] == ALPHABET_ORDER


# Operation 9: bad page — 422 page_invalid.
def test_list_materials_bad_page(admin_client):
    problem = assert_problem(
        admin_client.get(f"{API}/materials?page=x"), 422, "validation_failed"
    )
    assert ("page", "page_invalid") in error_codes(problem)


# --- 10 POST /materials ---------------------------------------------------------------------


# П-11, REQ-F-008: the material is created with the entered values.
def test_create_material(admin_client):
    body = {"name": "ЛДСП Білий 18 мм", "unit": "шт", "active": True}
    resp = admin_client.post(f"{API}/materials", json=body)
    assert resp.status_code == 201
    created = resp.json()
    assert set(created) == MATERIAL_FIELDS
    assert {k: created[k] for k in body} == body
    assert created["linked_items_count"] == 0
    assert resp.headers["location"] == f"{API}/materials/{created['id']}"


# Н-28, REQ-F-008: "лдсп білий 18 мм" when "ЛДСП Білий 18 мм" exists — 409.
def test_create_material_name_taken(admin_client, world):
    resp = admin_client.post(
        f"{API}/materials",
        json={"name": "лдсп білий 18 мм", "unit": "шт", "active": True},
    )
    problem = assert_problem(resp, 409, "material_name_taken")
    assert error_codes(problem) == [("name", "material_name_taken")]
    assert admin_client.get(f"{API}/materials").json()["total_items"] == 2


# Н-25, REQ-F-008: empty name, empty unit, unknown and read-only fields — 422.
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": ""}, ("name", "required")),
        ({"unit": ""}, ("unit", "required")),
        ({"colour": "білий"}, ("colour", "unknown_field")),
        ({"linked_items_count": 3}, ("linked_items_count", "read_only_field")),
        ({"active": 1}, ("active", "invalid_type")),
    ],
)
def test_create_material_invalid(admin_client, change, expected):
    body = {"name": "Кромка біла 2 мм", "unit": "п.м.", "active": True} | change
    problem = assert_problem(
        admin_client.post(f"{API}/materials", json=body), 422, "validation_failed"
    )
    assert expected in error_codes(problem)
    assert admin_client.get(f"{API}/materials").json()["total_items"] == 0


# Н-27: a body that is not valid JSON — 422 malformed_json.
def test_create_material_malformed_json(admin_client):
    resp = admin_client.post(
        f"{API}/materials",
        content='{"name": ',
        headers={"Content-Type": "application/json"},
    )
    problem = assert_problem(resp, 422, "validation_failed")
    assert error_codes(problem) == [(None, "malformed_json")]


# --- 11 GET /materials/{id} ------------------------------------------------------------------


# П-12: one material; unknown — 404; not an integer — 422.
def test_get_material(admin_client, world):
    resp = admin_client.get(f"{API}/materials/{world['M1']['id']}")
    assert resp.status_code == 200
    assert resp.json() == world["M1"]
    assert_problem(admin_client.get(f"{API}/materials/999"), 404, "not_found")
    problem = assert_problem(
        admin_client.get(f"{API}/materials/abc"), 422, "validation_failed"
    )
    assert error_codes(problem) == [("material_id", "invalid_type")]


# --- 12 PATCH /materials/{id} ----------------------------------------------------------------


# П-13, REQ-F-008, REQ-F-010: name and "active" changes are stored.
def test_update_material_name_and_active(admin_client, world):
    mid = world["M2"]["id"]
    resp = admin_client.patch(f"{API}/materials/{mid}", json={"active": False})
    assert resp.status_code == 200
    assert set(resp.json()) == MATERIAL_FIELDS
    assert resp.json()["active"] is False
    resp = admin_client.patch(
        f"{API}/materials/{mid}", json={"name": "Кромка біла 2,0 мм"}
    )
    assert resp.json()["name"] == "Кромка біла 2,0 мм"
    assert get_material(admin_client, mid) == world["M2"] | {
        "name": "Кромка біла 2,0 мм",
        "active": False,
    }


# REQ-F-009: a material without prices and links — the unit change is stored.
def test_update_material_unit_without_links(admin_client, world):
    mid = world["M1"]["id"]
    resp = admin_client.patch(f"{API}/materials/{mid}", json={"unit": "уп"})
    assert resp.status_code == 200
    assert get_material(admin_client, mid)["unit"] == "уп"


# Н-10, REQ-F-009: a material with a linked item — 409 unit_locked with the text
# of the criterion; the unit stays.
def test_update_material_unit_locked(admin_client, world):
    mid = world["M1"]["id"]
    assert link(admin_client, world["B1"], mid).status_code == 201
    resp = admin_client.patch(f"{API}/materials/{mid}", json={"unit": "уп"})
    problem = assert_problem(resp, 409, "unit_locked")
    assert error_codes(problem) == [("unit", "unit_locked")]
    assert "одиницю не можна змінити: є ціни або прив'язки" in problem[
        "detail"
    ].replace("’", "'")
    assert get_material(admin_client, mid)["unit"] == "шт"


# REQ-F-008: another material's name in any case — 409; read-only field — 422.
def test_update_material_conflicts(admin_client, world):
    mid = world["M2"]["id"]
    resp = admin_client.patch(
        f"{API}/materials/{mid}", json={"name": "ЛДСП БІЛИЙ 18 ММ"}
    )
    assert_problem(resp, 409, "material_name_taken")
    resp = admin_client.patch(f"{API}/materials/{mid}", json={"linked_items_count": 5})
    problem = assert_problem(resp, 422, "validation_failed")
    assert ("linked_items_count", "read_only_field") in error_codes(problem)
    assert get_material(admin_client, mid) == world["M2"]


# Operation 12: unknown material — 404.
def test_update_material_not_found(admin_client):
    assert_problem(
        admin_client.patch(f"{API}/materials/999", json={"active": False}),
        404,
        "not_found",
    )


# --- DELETE is not allowed (REQ-F-010, Н-08) -----------------------------------------------


# Н-08, REQ-F-010: DELETE on supplier and material addresses — 405; records stay.
@pytest.mark.parametrize("kind", ["suppliers", "materials"])
def test_delete_supplier_or_material_not_allowed(admin_client, world, kind):
    record = world["A"] if kind == "suppliers" else world["M1"]
    for path in (f"{API}/{kind}/{record['id']}", f"{API}/{kind}"):
        problem = assert_problem(admin_client.delete(path), 405, "method_not_allowed")
        assert "DELETE" in problem["detail"]
    resp = admin_client.get(f"{API}/{kind}/{record['id']}")
    assert resp.status_code == 200
    assert resp.json() == record


# REQ-NF-031: other methods those addresses do not have — 405 too.
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/suppliers/{id}"),
        ("PATCH", "/suppliers"),
        ("PUT", "/materials/{id}"),
        ("POST", "/parsers"),
    ],
)
def test_other_methods_not_allowed(admin_client, world, method, path):
    url = API + path.format(id=world["A"]["id"])
    assert_problem(
        admin_client.request(method, url, json={}), 405, "method_not_allowed"
    )


# --- 13 GET /materials/{id}/links ------------------------------------------------------------


# П-14, BDD-063, REQ-F-069: the list of items linked to М1 — supplier, SKU, name,
# unit; ordered by supplier name, then SKU (П-4); linked_items_count = 2.
def test_list_material_links(admin_client, world):
    mid = world["M1"]["id"]
    assert link(admin_client, world["B1"], mid).status_code == 201
    assert link(admin_client, world["A1"], mid).status_code == 201
    body = admin_client.get(f"{API}/materials/{mid}/links").json()
    assert set(body) == PAGE_FIELDS
    rows = [
        (
            i["supplier_item"]["supplier"]["name"],
            i["supplier_item"]["sku"],
            i["supplier_item"]["name"],
            i["supplier_item"]["unit"],
            i["material"]["id"],
        )
        for i in body["items"]
    ]
    assert rows == [
        ("Альфа", "А-1", "Плита ЛДСП біла 18", "Шт.", mid),
        ("Бета", "Б-1", "ЛДСП білий 18 мм", "шт", mid),
    ]
    assert get_material(admin_client, mid)["linked_items_count"] == 2


# REQ-F-057 criterion (П-3, П-4): SKUs "А-2", "А-10", "А 3" of one supplier —
# "А 3", "А-10", "А-2"; items of "Бета" and "Альфа" — "Альфа" first.
def test_unlinked_items_order_by_supplier_and_sku(admin_client, add_item):
    beta = create_supplier(admin_client, "Бета", catalog_url="http://localhost:8001/b")
    alfa = create_supplier(admin_client, "Альфа", catalog_url="http://localhost:8001/a")
    add_item(beta["id"], "Б-1")
    add_item(alfa["id"], "А-2")
    add_item(alfa["id"], "А-10")
    add_item(alfa["id"], "А 3")
    body = admin_client.get(f"{API}/unlinked-items").json()
    assert [i["supplier_item"]["sku"] for i in body["items"]] == [
        "А 3",
        "А-10",
        "А-2",
        "Б-1",
    ]


# Operation 13: unknown material — 404; page beyond — 200 empty; bad page — 422.
def test_material_links_errors(admin_client, world):
    assert_problem(admin_client.get(f"{API}/materials/999/links"), 404, "not_found")
    beyond = admin_client.get(f"{API}/materials/{world['M1']['id']}/links?page=2")
    assert beyond.status_code == 200 and beyond.json()["items"] == []
    problem = assert_problem(
        admin_client.get(f"{API}/materials/{world['M1']['id']}/links?page=0"),
        422,
        "validation_failed",
    )
    assert ("page", "page_invalid") in error_codes(problem)


# --- 14 GET /unlinked-items -------------------------------------------------------------------


# П-16, REQ-F-012, REQ-F-057: one list of all suppliers, by supplier then SKU; with
# supplier (id, name, active), SKU, name, unit, last seen date.
def test_list_unlinked_items(admin_client, world):
    body = admin_client.get(f"{API}/unlinked-items").json()
    assert set(body) == PAGE_FIELDS
    rows = [
        (i["supplier_item"]["supplier"]["name"], i["supplier_item"]["sku"])
        for i in body["items"]
    ]
    assert rows == [
        ("Альфа", "А-1"),
        ("Альфа", "А-2"),
        ("Бета", "Б-1"),
        ("Бета", "Б-2"),
        ("Бета", "Б-3"),
    ]
    first = body["items"][0]["supplier_item"]
    assert first == {
        "id": world["A1"],
        "supplier": {"id": world["A"]["id"], "name": "Альфа", "active": True},
        "sku": "А-1",
        "name": "Плита ЛДСП біла 18",
        "unit": "Шт.",
        "last_seen_date": "2026-07-14",
    }


# REQ-F-011: an item of a deactivated supplier stays in the list, supplier.active false.
def test_unlinked_items_of_deactivated_supplier(admin_client, world):
    admin_client.patch(f"{API}/suppliers/{world['A']['id']}", json={"active": False})
    items = admin_client.get(f"{API}/unlinked-items").json()["items"]
    alfa = [
        i["supplier_item"]
        for i in items
        if i["supplier_item"]["supplier"]["name"] == "Альфа"
    ]
    assert len(alfa) == 2
    assert all(i["supplier"]["active"] is False for i in alfa)


# REQ-F-012, REQ-F-057: search "білий" in SKU and name, ignoring case.
@pytest.mark.parametrize(
    ("q", "skus"),
    [
        ("білий", ["Б-1"]),
        ("БІЛ", ["А-1", "Б-1", "Б-2"]),
        ("б-2", ["Б-2"]),
        ("нема", []),
    ],
)
def test_unlinked_items_search(admin_client, world, q, skus):
    body = admin_client.get(f"{API}/unlinked-items?q={q}").json()
    assert [i["supplier_item"]["sku"] for i in body["items"]] == skus


# REQ-F-057 criterion: 120 unlinked items — first page holds the first 50 by
# supplier and SKU; the page beyond is empty.
def test_unlinked_items_120_pages(admin_client, add_item):
    beta = create_supplier(admin_client, "Бета", catalog_url="http://localhost:8001/b")
    alfa = create_supplier(admin_client, "Альфа", catalog_url="http://localhost:8001/a")
    for n in range(60):
        add_item(beta["id"], f"Б-{n:03d}")
        add_item(alfa["id"], f"А-{n:03d}")
    pages = [
        admin_client.get(f"{API}/unlinked-items?page={p}").json() for p in (1, 2, 3, 4)
    ]
    skus = [[i["supplier_item"]["sku"] for i in p["items"]] for p in pages]
    expected = [f"А-{n:03d}" for n in range(60)] + [f"Б-{n:03d}" for n in range(60)]
    assert skus == [expected[:50], expected[50:100], expected[100:], []]
    assert pages[0]["total_items"] == 120 and pages[0]["total_pages"] == 3


# --- 16 PUT /supplier-items/{id}/link -----------------------------------------------------------


# П-18, REQ-F-013, REQ-F-014: a new link — 201 with Location; "Шт." links to "шт";
# the item leaves the unlinked list.
def test_link_new(admin_client, world):
    resp = link(admin_client, world["A1"], world["M1"]["id"])
    assert resp.status_code == 201
    assert resp.headers["location"] == f"{API}/supplier-items/{world['A1']}/link"
    body = resp.json()
    assert body["supplier_item"]["id"] == world["A1"]
    assert body["supplier_item"]["sku"] == "А-1"
    assert body["material"] == {"id": world["M1"]["id"], "name": "ЛДСП Білий 18 мм"}
    assert world["A1"] not in unlinked_ids(admin_client)


# REQ-F-016/contract: repeating the same link — 200 without change.
def test_link_same_material_again(admin_client, world):
    link(admin_client, world["A1"], world["M1"]["id"])
    resp = link(admin_client, world["A1"], world["M1"]["id"])
    assert resp.status_code == 200
    assert link_ids(admin_client, world["M1"]["id"]) == {world["A1"]}


# П-19, BDD-063, REQ-F-015: rebinding to another material — 200; the item is only
# in the new material's list (one link per item, REQ-F-013).
def test_relink_to_other_material(admin_client, world):
    m3 = create_material(admin_client, "ЛДСП Сірий 18 мм", unit="шт")
    link(admin_client, world["A1"], world["M1"]["id"])
    resp = link(admin_client, world["A1"], m3["id"])
    assert resp.status_code == 200
    assert resp.json()["material"]["id"] == m3["id"]
    assert link_ids(admin_client, world["M1"]["id"]) == set()
    assert link_ids(admin_client, m3["id"]) == {world["A1"]}


# Н-12, BDD-027, REQ-F-014: "м.п." to "п.м." — 409 link_units_differ with both units;
# the item stays unlinked.
def test_link_units_differ(admin_client, world):
    resp = link(admin_client, world["B2"], world["M2"]["id"])
    problem = assert_problem(resp, 409, "link_units_differ")
    assert "м.п." in problem["detail"] and "п.м." in problem["detail"]
    assert world["B2"] in unlinked_ids(admin_client)


# REQ-F-014: units are compared lower-case, without dots and spaces.
@pytest.mark.parametrize(
    ("item_unit", "material_unit"), [("Шт.", "шт"), ("П. М.", "п.м."), ("кг", "КГ")]
)
def test_link_units_normalized(admin_client, add_item, item_unit, material_unit):
    supplier = create_supplier(
        admin_client, "Гама", catalog_url="http://localhost:8001/g"
    )
    material = create_material(admin_client, "Матеріал Х", unit=material_unit)
    item = add_item(supplier["id"], "Г-1", "Позиція", item_unit)
    assert link(admin_client, item, material["id"]).status_code == 201


# Н-13, BDD-032, REQ-F-048: the second item of the same supplier to М1 — 409 with
# the SKU of the linked one; an item of another supplier can be linked.
def test_link_second_item_same_supplier(admin_client, world):
    mid = world["M1"]["id"]
    assert link(admin_client, world["A1"], mid).status_code == 201
    problem = assert_problem(
        link(admin_client, world["A2"], mid), 409, "material_supplier_already_linked"
    )
    assert "А-1" in problem["detail"]
    assert world["A2"] in unlinked_ids(admin_client)
    assert link(admin_client, world["B1"], mid).status_code == 201


# BDD-063, REQ-F-069: rebinding Б-1 to a material where Б-4 of the same supplier
# is linked (units match) — 409 with "Б-4"; Б-1 stays in М1.
def test_relink_to_material_with_same_supplier_item(admin_client, add_item, world):
    m1 = world["M1"]["id"]
    m3 = create_material(admin_client, "ЛДСП Сірий 18 мм", unit="шт")["id"]
    b4 = add_item(world["B"]["id"], "Б-4", "ЛДСП сірий", "шт")
    link(admin_client, world["B1"], m1)
    assert link(admin_client, b4, m3).status_code == 201
    problem = assert_problem(
        link(admin_client, world["B1"], m3), 409, "material_supplier_already_linked"
    )
    assert "Б-4" in problem["detail"]
    assert link_ids(admin_client, m1) == {world["B1"]}


# Н-14, BDD-037, REQ-F-050: link to a deactivated material — 409 with its name and
# "activate first"; after activation the same link works.
def test_link_inactive_material(admin_client, world):
    mid = world["M1"]["id"]
    admin_client.patch(f"{API}/materials/{mid}", json={"active": False})
    problem = assert_problem(
        link(admin_client, world["B1"], mid), 409, "material_inactive"
    )
    assert "ЛДСП Білий 18 мм" in problem["detail"]
    assert "активуйте" in problem["detail"]
    assert world["B1"] in unlinked_ids(admin_client)
    admin_client.patch(f"{API}/materials/{mid}", json={"active": True})
    assert link(admin_client, world["B1"], mid).status_code == 201


# Operation 16: unknown item — 404; unknown material — 422 reference_not_found;
# body errors — 422; id not an integer — 422.
@pytest.mark.parametrize(
    ("item", "body", "status", "expected"),
    [
        ("999", {"material_id": "M1"}, 404, None),
        ("A1", {"material_id": 999}, 422, ("material_id", "reference_not_found")),
        ("A1", {}, 422, ("material_id", "required")),
        ("A1", {"material_id": "1"}, 422, ("material_id", "invalid_type")),
        ("A1", {"material_id": "M1", "note": "x"}, 422, ("note", "unknown_field")),
        ("abc", {"material_id": "M1"}, 422, ("supplier_item_id", "invalid_type")),
    ],
)
def test_link_invalid(admin_client, world, item, body, status, expected):
    item_id = world[item] if item in world else item
    body = {k: (world[v]["id"] if v in ("M1", "M2") else v) for k, v in body.items()}
    resp = admin_client.put(f"{API}/supplier-items/{item_id}/link", json=body)
    if status == 404:
        assert_problem(resp, 404, "not_found")
    else:
        problem = assert_problem(resp, 422, "validation_failed")
        assert expected in error_codes(problem)
    assert world["A1"] in unlinked_ids(admin_client)


# --- 17 DELETE /supplier-items/{id}/link --------------------------------------------------------


# П-20, BDD-063, REQ-F-015: unlink — 204; the item is back in the unlinked list.
def test_unlink(admin_client, world):
    mid = world["M1"]["id"]
    link(admin_client, world["A1"], mid)
    resp = admin_client.delete(f"{API}/supplier-items/{world['A1']}/link")
    assert resp.status_code == 204
    assert world["A1"] in unlinked_ids(admin_client)
    assert link_ids(admin_client, mid) == set()
    assert get_material(admin_client, mid)["linked_items_count"] == 0


# Н-06: an item without a link — 404; unknown item — 404; bad id — 422.
def test_unlink_errors(admin_client, world):
    assert_problem(
        admin_client.delete(f"{API}/supplier-items/{world['A1']}/link"),
        404,
        "not_found",
    )
    assert_problem(
        admin_client.delete(f"{API}/supplier-items/999/link"), 404, "not_found"
    )
    problem = assert_problem(
        admin_client.delete(f"{API}/supplier-items/x/link"), 422, "validation_failed"
    )
    assert error_codes(problem) == [("supplier_item_id", "invalid_type")]


# --- 401, 403, 415, 422 for every operation in scope -----------------------------------------

# (method, path template, body) of operations 4–14, 16, 17, 23, 24.
OPERATIONS = {
    4: ("GET", "/suppliers", None),
    5: (
        "POST",
        "/suppliers",
        {
            "name": "Дельта",
            "catalog_url": "http://localhost:8001/e",
            "parser": "table_layout",
            "active": True,
        },
    ),
    6: ("GET", "/suppliers/{A}", None),
    7: ("PATCH", "/suppliers/{A}", {"active": False}),
    8: ("GET", "/parsers", None),
    9: ("GET", "/materials", None),
    10: (
        "POST",
        "/materials",
        {"name": "Кромка біла 1 мм", "unit": "п.м.", "active": True},
    ),
    11: ("GET", "/materials/{M1}", None),
    12: ("PATCH", "/materials/{M1}", {"name": "ЛДСП Білий 18 мм (Egger)"}),
    13: ("GET", "/materials/{M1}/links", None),
    14: ("GET", "/unlinked-items", None),
    16: ("PUT", "/supplier-items/{B1}/link", {"material_id": "{M1}"}),
    17: ("DELETE", "/supplier-items/{A1}/link", None),
    23: ("GET", "/settings", None),
    24: ("PATCH", "/settings", {"notification_threshold": 2}),
}
ADMIN_ONLY = [5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 23, 24]
WITH_BODY = [5, 7, 10, 12, 16, 24]


def resolve(world: dict, number: int) -> tuple[str, str, dict | None]:
    method, path, body = OPERATIONS[number]
    ids = {
        "A": world["A"]["id"],
        "M1": world["M1"]["id"],
        "A1": world["A1"],
        "B1": world["B1"],
    }
    path = API + path.format(**ids)
    if body is not None:
        body = {
            k: (ids[v[1:-1]] if isinstance(v, str) and v.startswith("{") else v)
            for k, v in body.items()
        }
    return method, path, body


def state(admin_client, world) -> dict:
    """Everything operations 5–17, 24 could change."""
    return {
        "suppliers": all_pages(admin_client, f"{API}/suppliers"),
        "materials": all_pages(admin_client, f"{API}/materials"),
        "links": link_ids(admin_client, world["M1"]["id"]),
        "unlinked": unlinked_ids(admin_client),
        "settings": admin_client.get(f"{API}/settings").json(),
    }


# REQ-NF-031, BDD-068: every operation without a session — 401 unauthenticated.
@pytest.mark.parametrize("number", sorted(OPERATIONS))
def test_operation_without_session_is_401(admin_client, client, world, number):
    method, path, body = resolve(world, number)
    assert_problem(client.request(method, path, json=body), 401, "unauthenticated")


# Н-03, Н-04, Н-29…Н-36, Н-38…Н-40, BDD-070, REQ-F-005: the manager on every
# administrator operation — 403 "немає доступу", and the state is unchanged.
@pytest.mark.parametrize("number", ADMIN_ONLY)
def test_manager_forbidden_state_unchanged(admin_client, manager_client, world, number):
    link(admin_client, world["A1"], world["M1"]["id"])
    before = state(admin_client, world)
    method, path, body = resolve(world, number)
    problem = assert_problem(
        manager_client.request(method, path, json=body), 403, "forbidden"
    )
    assert problem["detail"] == NO_ACCESS
    assert state(admin_client, world) == before


# REQ-F-005, section 0 of resources.md: the manager gets 403 even for a missing id.
@pytest.mark.parametrize(
    "path", ["/suppliers/999", "/materials/999", "/materials/999/links"]
)
def test_manager_forbidden_before_not_found(manager_client, path):
    assert_problem(manager_client.get(API + path), 403, "forbidden")


# BDD-070: the manager asks to rename М1 — 403 "немає доступу", the name is the same.
def test_manager_cannot_rename_material_bdd070(admin_client, manager_client, world):
    mid = world["M1"]["id"]
    resp = manager_client.patch(
        f"{API}/materials/{mid}", json={"name": "ЛДСП Білий 18 мм (Egger)"}
    )
    assert assert_problem(resp, 403, "forbidden")["detail"] == NO_ACCESS
    assert get_material(admin_client, mid)["name"] == "ЛДСП Білий 18 мм"


# Н-16, REQ-NF-031: operations with a body — Content-Type not JSON — 415; nothing changes.
@pytest.mark.parametrize("number", WITH_BODY)
def test_operation_body_not_json_is_415(admin_client, world, number):
    before = state(admin_client, world)
    method, path, _ = resolve(world, number)
    resp = admin_client.request(
        method, path, content="name=x", headers={"Content-Type": "text/plain"}
    )
    assert_problem(resp, 415, "unsupported_media_type")
    assert state(admin_client, world) == before


# Н-27 for every operation with a body: invalid JSON — 422 malformed_json.
@pytest.mark.parametrize("number", WITH_BODY)
def test_operation_malformed_json_is_422(admin_client, world, number):
    before = state(admin_client, world)
    method, path, _ = resolve(world, number)
    resp = admin_client.request(
        method, path, content="{oops", headers={"Content-Type": "application/json"}
    )
    problem = assert_problem(resp, 422, "validation_failed")
    assert error_codes(problem) == [(None, "malformed_json")]
    assert state(admin_client, world) == before


# REQ-NF-031: successful answers are JSON.
@pytest.mark.parametrize("number", [4, 6, 8, 9, 11, 13, 14, 23])
def test_operation_answers_json(admin_client, world, number):
    method, path, _ = resolve(world, number)
    resp = admin_client.request(method, path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")

"""T-13: screens "постачальники" and "матеріали" and their actions (web).

REQ-F-007, REQ-F-008, REQ-F-010, REQ-F-068, REQ-F-057 (П-3, П-4), REQ-NF-015,
REQ-F-005; UC-06, UC-07 (main flows, 2в, 2г, 3а).

The screens are server HTML pages (REQ-NF-015); the forms post
application/x-www-form-urlencoded data. The state is checked through the API.
"""

from __future__ import annotations

import pytest
from helpers import (
    API,
    NO_ACCESS,
    all_pages,
    column,
    create_material,
    create_supplier,
    data_table,
    forms,
    link,
    page_text,
)

SUPPLIER_COLUMNS = [
    "назва",
    "адреса каталогу",
    "розбирач",
    "активний",
    "дата останнього оновлення",
]
MATERIAL_COLUMNS = [
    "найменування",
    "одиниця",
    "активний",
    "кількість прив'язаних позицій",
]
ALPHABET_NAMES = ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]
ALPHABET_ORDER = ["2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак", "Alpha"]
PARSERS = {"table_layout", "cards_layout", "list_layout"}
REDIRECT = (302, 303)


def supplier_form(**change) -> dict:
    data = {
        "name": "Альфа",
        "catalog_url": "http://localhost:8001/a",
        "parser": "table_layout",
        "active": "on",
    }
    data.update(change)
    return {k: v for k, v in data.items() if v is not None}


def material_form(**change) -> dict:
    data = {"name": "ЛДСП Білий 18 мм", "unit": "шт", "active": "on"}
    data.update(change)
    return {k: v for k, v in data.items() if v is not None}


def suppliers(client) -> list[dict]:
    return all_pages(client, f"{API}/suppliers")


def materials(client) -> list[dict]:
    return all_pages(client, f"{API}/materials")


def headers_of(html: str) -> list[str]:
    headers, _ = data_table(html)
    return [h.lower().replace("«", "").replace("»", "") for h in headers]


def assert_html_screen(resp) -> str:
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    return resp.text


# --- screen "постачальники" ------------------------------------------------------------


# REQ-F-068, REQ-NF-015: exactly the columns of REQ-F-068; the data is in the HTML
# from the server; a supplier not updated yet shows "ще не оновлювався".
def test_suppliers_screen_columns(admin_client):
    create_supplier(admin_client, "Альфа", catalog_url="http://localhost:8001/a")
    html = assert_html_screen(admin_client.get("/suppliers"))
    assert headers_of(html) == SUPPLIER_COLUMNS
    _, rows = data_table(html)
    assert rows[0][:5] == [
        "Альфа",
        "http://localhost:8001/a",
        "table_layout",
        rows[0][3],
        "ще не оновлювався",
    ]


# REQ-F-007 criterion: the created supplier appears with the entered values.
def test_create_supplier_on_screen(admin_client):
    resp = admin_client.post("/suppliers", data=supplier_form(), follow_redirects=False)
    assert resp.status_code in REDIRECT
    assert [s["name"] for s in suppliers(admin_client)] == ["Альфа"]
    created = suppliers(admin_client)[0]
    assert (created["catalog_url"], created["parser"], created["active"]) == (
        "http://localhost:8001/a",
        "table_layout",
        True,
    )
    assert column(admin_client.get("/suppliers").text) == ["Альфа"]


# REQ-F-007 criterion: empty name, "альфа" when "Альфа" exists, "catalog.html",
# "ftp://localhost/a" are refused with the reason; nothing is created.
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"name": ""}, "обов'язков"),
        ({"name": "альфа"}, "уже є"),
        ({"catalog_url": "catalog.html", "name": "Бета"}, "http або https"),
        ({"catalog_url": "ftp://localhost/a", "name": "Бета"}, "http або https"),
        ({"parser": "xml_layout", "name": "Бета"}, "немає в списку наявних"),
    ],
)
def test_create_supplier_rejected_on_screen(admin_client, change, reason):
    create_supplier(admin_client, "Альфа", catalog_url="http://localhost:8001/a")
    resp = admin_client.post(
        "/suppliers", data=supplier_form(**change), follow_redirects=False
    )
    assert resp.status_code not in REDIRECT
    assert reason in page_text(resp.text).lower()
    assert [s["name"] for s in suppliers(admin_client)] == ["Альфа"]


# REQ-F-007 criterion: "http://localhost:8001/a" is accepted.
def test_create_supplier_localhost_url_accepted(admin_client):
    resp = admin_client.post(
        "/suppliers",
        data=supplier_form(catalog_url="http://localhost:8001/a"),
        follow_redirects=False,
    )
    assert resp.status_code in REDIRECT


# REQ-F-007: the parser is chosen only from the list of available parsers (select,
# no free text), on the create and the edit form.
def test_parser_is_a_choice_from_available(admin_client):
    sid = create_supplier(admin_client, "Альфа")["id"]
    available = set(admin_client.get(f"{API}/parsers").json()["items"])
    assert PARSERS <= available
    for path in ("/suppliers/new", f"/suppliers/{sid}"):
        html = assert_html_screen(admin_client.get(path))
        (form,) = [
            f for f in forms(html) if f["method"] == "post" and "parser" in f["selects"]
        ]
        assert {o["value"] for o in form["selects"]["parser"]} == available
        assert "parser" not in {i.get("name") for i in form["inputs"]}


# REQ-F-007: the edit form changes the supplier; the same rules apply.
def test_edit_supplier_on_screen(admin_client):
    sid = create_supplier(admin_client, "Альфа")["id"]
    create_supplier(admin_client, "Бета")
    resp = admin_client.post(
        f"/suppliers/{sid}",
        data=supplier_form(name="Альфа Плюс", parser="cards_layout"),
        follow_redirects=False,
    )
    assert resp.status_code in REDIRECT
    edited = admin_client.get(f"{API}/suppliers/{sid}").json()
    assert (edited["name"], edited["parser"]) == ("Альфа Плюс", "cards_layout")
    resp = admin_client.post(
        f"/suppliers/{sid}", data=supplier_form(name="БЕТА"), follow_redirects=False
    )
    assert resp.status_code not in REDIRECT
    assert "уже є" in page_text(resp.text)
    assert admin_client.get(f"{API}/suppliers/{sid}").json()["name"] == "Альфа Плюс"


# REQ-F-010: deactivation removes the flag "active"; activation returns it.
def test_deactivate_and_activate_supplier_on_screen(admin_client):
    sid = create_supplier(admin_client, "Альфа")["id"]
    resp = admin_client.post(
        f"/suppliers/{sid}", data=supplier_form(active=None), follow_redirects=False
    )
    assert resp.status_code in REDIRECT
    assert admin_client.get(f"{API}/suppliers/{sid}").json()["active"] is False
    inactive_cell = data_table(admin_client.get("/suppliers").text)[1][0][3]
    admin_client.post(f"/suppliers/{sid}", data=supplier_form(), follow_redirects=False)
    assert admin_client.get(f"{API}/suppliers/{sid}").json()["active"] is True
    active_cell = data_table(admin_client.get("/suppliers").text)[1][0][3]
    assert inactive_cell != active_cell


# REQ-F-057, П-3, П-4: suppliers by name in alphabetical order.
def test_suppliers_screen_order(admin_client):
    for i, name in enumerate(ALPHABET_NAMES):
        create_supplier(admin_client, name, catalog_url=f"http://localhost:8001/{i}")
    assert column(admin_client.get("/suppliers").text) == ALPHABET_ORDER


# REQ-F-057, П-4: 50 per page with paging.
def test_suppliers_screen_pages(admin_client):
    names = [f"Постачальник {i:03d}" for i in range(53)]
    for i, name in enumerate(names):
        create_supplier(admin_client, name, catalog_url=f"http://localhost:8001/{i}")
    assert column(admin_client.get("/suppliers").text) == names[:50]
    assert column(admin_client.get("/suppliers?page=2").text) == names[50:]
    assert "page=2" in admin_client.get("/suppliers").text


# --- screen "матеріали" --------------------------------------------------------------------


# REQ-F-068: exactly the columns; two linked items — the count shows 2.
def test_materials_screen_columns(admin_client, add_item):
    supplier_a = create_supplier(
        admin_client, "Альфа", catalog_url="http://localhost:8001/a"
    )
    supplier_b = create_supplier(
        admin_client, "Бета", catalog_url="http://localhost:8001/b"
    )
    material = create_material(admin_client, "ЛДСП Білий 18 мм", unit="шт")
    link(admin_client, add_item(supplier_a["id"], "А-1"), material["id"])
    link(admin_client, add_item(supplier_b["id"], "Б-1"), material["id"])
    html = assert_html_screen(admin_client.get("/materials"))
    assert headers_of(html) == MATERIAL_COLUMNS
    _, rows = data_table(html)
    assert rows[0][0] == "ЛДСП Білий 18 мм"
    assert rows[0][1] == "шт"
    assert rows[0][3] == "2"


# REQ-F-008 criterion: the created material appears with the entered values;
# changed name and "active" are stored.
def test_create_and_edit_material_on_screen(admin_client):
    resp = admin_client.post("/materials", data=material_form(), follow_redirects=False)
    assert resp.status_code in REDIRECT
    (created,) = materials(admin_client)
    assert (created["name"], created["unit"], created["active"]) == (
        "ЛДСП Білий 18 мм",
        "шт",
        True,
    )
    resp = admin_client.post(
        f"/materials/{created['id']}",
        data=material_form(name="ЛДСП Білий 16 мм", active=None),
        follow_redirects=False,
    )
    assert resp.status_code in REDIRECT
    edited = admin_client.get(f"{API}/materials/{created['id']}").json()
    assert (edited["name"], edited["active"]) == ("ЛДСП Білий 16 мм", False)


# REQ-F-008 criterion: empty name, "лдсп білий 18 мм" when "ЛДСП Білий 18 мм"
# exists, empty unit — refused with the reason; nothing is created.
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"name": ""}, "обов'язков"),
        ({"name": "лдсп білий 18 мм"}, "уже є"),
        ({"name": "Кромка", "unit": ""}, "обов'язков"),
    ],
)
def test_create_material_rejected_on_screen(admin_client, change, reason):
    create_material(admin_client, "ЛДСП Білий 18 мм")
    resp = admin_client.post(
        "/materials", data=material_form(**change), follow_redirects=False
    )
    assert resp.status_code not in REDIRECT
    assert reason in page_text(resp.text).lower()
    assert [m["name"] for m in materials(admin_client)] == ["ЛДСП Білий 18 мм"]


# REQ-F-009 on the screen: the unit of a material with a link cannot change.
def test_material_unit_locked_on_screen(admin_client, add_item):
    supplier = create_supplier(admin_client, "Альфа")
    material = create_material(admin_client, "ЛДСП Білий 18 мм", unit="шт")
    link(admin_client, add_item(supplier["id"], "А-1"), material["id"])
    resp = admin_client.post(
        f"/materials/{material['id']}",
        data=material_form(unit="уп"),
        follow_redirects=False,
    )
    assert resp.status_code not in REDIRECT
    assert "одиницю не можна змінити: є ціни або прив'язки" in page_text(resp.text)
    assert admin_client.get(f"{API}/materials/{material['id']}").json()["unit"] == "шт"


# REQ-F-057 criterion: 120 materials — first page holds the first 50 by name.
def test_materials_screen_pages_and_order(admin_client):
    names = [f"Матеріал {i:03d}" for i in range(120)]
    for name in reversed(names):
        create_material(admin_client, name)
    assert column(admin_client.get("/materials").text) == names[:50]
    assert column(admin_client.get("/materials?page=2").text) == names[50:100]
    assert column(admin_client.get("/materials?page=3").text) == names[100:]


# REQ-F-057, П-3: the alphabetical order of the criterion on the "матеріали" screen.
def test_materials_screen_alphabetical(admin_client):
    for name in ALPHABET_NAMES:
        create_material(admin_client, name)
    assert column(admin_client.get("/materials").text) == ALPHABET_ORDER


# --- REQ-F-010: no deletion ---------------------------------------------------------------


# REQ-F-010: the screens offer no deletion, even for a new record without prices.
@pytest.mark.parametrize("kind", ["suppliers", "materials"])
def test_no_delete_in_interface(admin_client, kind):
    record = (
        create_supplier(admin_client, "Альфа")
        if kind == "suppliers"
        else create_material(admin_client, "М1")
    )
    for path in (f"/{kind}", f"/{kind}/{record['id']}"):
        text = page_text(admin_client.get(path).text).lower()
        assert "видалити" not in text
        assert "вилучити" not in text


# REQ-F-010: a direct request to delete is refused, and the record stays.
@pytest.mark.parametrize("kind", ["suppliers", "materials"])
@pytest.mark.parametrize("method", ["DELETE", "POST"])
def test_direct_delete_request_refused(admin_client, kind, method):
    record = (
        create_supplier(admin_client, "Альфа")
        if kind == "suppliers"
        else create_material(admin_client, "М1")
    )
    path = (
        f"/{kind}/{record['id']}"
        if method == "DELETE"
        else f"/{kind}/{record['id']}/delete"
    )
    resp = admin_client.request(method, path, follow_redirects=False)
    assert resp.status_code in (404, 405)
    assert admin_client.get(f"{API}/{kind}/{record['id']}").json() == record


# --- REQ-F-005: the manager -------------------------------------------------------------------


# REQ-F-005, REQ-NF-003: the manager on the admin screens sees "немає доступу",
# not their content and not "not found".
@pytest.mark.parametrize(
    "path",
    [
        "/suppliers",
        "/suppliers/new",
        "/suppliers/{s}",
        "/materials",
        "/materials/new",
        "/materials/{m}",
    ],
)
def test_manager_screens_no_access(admin_client, manager_client, path):
    s = create_supplier(admin_client, "Альфа Секрет")["id"]
    m = create_material(admin_client, "Матеріал Секрет")["id"]
    resp = manager_client.get(path.format(s=s, m=m))
    assert resp.status_code == 403
    text = page_text(resp.text)
    assert NO_ACCESS in text
    assert "Секрет" not in text


# REQ-F-003, REQ-F-005: the manager's direct form requests change nothing.
@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/suppliers", supplier_form(name="Дельта")),
        ("/suppliers/{s}", supplier_form(name="Інша", active=None)),
        ("/materials", material_form(name="Кромка")),
        ("/materials/{m}", material_form(name="Інший", active=None)),
    ],
)
def test_manager_actions_no_access(admin_client, manager_client, path, data):
    s = create_supplier(admin_client, "Альфа")
    m = create_material(admin_client, "ЛДСП Білий 18 мм")
    before = (suppliers(admin_client), materials(admin_client))
    resp = manager_client.post(
        path.format(s=s["id"], m=m["id"]), data=data, follow_redirects=False
    )
    assert resp.status_code == 403
    assert NO_ACCESS in page_text(resp.text)
    assert (suppliers(admin_client), materials(admin_client)) == before

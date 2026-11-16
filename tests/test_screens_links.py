"""T-15: unlinked items, linking and the list of linked items (web).

REQ-F-012, REQ-F-013, REQ-F-014, REQ-F-015, REQ-F-048, REQ-F-050, REQ-F-057
(list of unlinked items, choice of the material), REQ-F-069; BDD-027, BDD-032,
BDD-037, BDD-063; UC-08, UC-09. No update runs exist yet, so the supplier items
are created directly in storage (T-15).
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
    ordered,
    page_text,
)

UNLINKED_COLUMNS = ["постачальник", "артикул", "найменування", "одиниця", "дата"]
LINK_COLUMNS = ["постачальник", "артикул", "найменування", "одиниця"]
REDIRECT = (302, 303)


@pytest.fixture
def world(admin_client, add_item):
    """Suppliers "Бета" and "Альфа" (created in this order), materials, items."""
    from datetime import date

    w = {}
    w["B"] = create_supplier(
        admin_client, "Бета", catalog_url="http://localhost:8001/b"
    )
    w["A"] = create_supplier(
        admin_client, "Альфа", catalog_url="http://localhost:8001/a"
    )
    w["M1"] = create_material(admin_client, "ЛДСП Білий 18 мм", unit="шт")
    w["M2"] = create_material(admin_client, "Кромка біла 2 мм", unit="п.м.")
    w["B1"] = add_item(w["B"]["id"], "Б-1", "ЛДСП білий 18 мм", "шт", date(2026, 7, 10))
    w["B2"] = add_item(
        w["B"]["id"], "Б-2", "Кромка ПВХ біла", "м.п.", date(2026, 7, 11)
    )
    w["A1"] = add_item(
        w["A"]["id"], "А-1", "Плита ЛДСП біла 18", "Шт.", date(2026, 7, 12)
    )
    w["A2"] = add_item(
        w["A"]["id"], "А-2", "Плита ЛДСП сіра 18", "шт", date(2026, 7, 13)
    )
    return w


def link_on_screen(client, item_id: int, material_id: int):
    return client.post(
        f"/supplier-items/{item_id}/link",
        data={"material_id": str(material_id)},
        follow_redirects=False,
    )


def unlink_on_screen(client, item_id: int):
    return client.post(f"/supplier-items/{item_id}/unlink", follow_redirects=False)


def unlinked_skus_on_screen(client, query: str = "") -> list[str]:
    return column(client.get(f"/unlinked-items{query}").text, 1)


def linked_skus(client, material_id: int) -> list[str]:
    items = all_pages(client, f"{API}/materials/{material_id}/links")
    return [i["supplier_item"]["sku"] for i in items]


def lower_headers(html: str) -> list[str]:
    headers, _ = data_table(html)
    return [h.lower() for h in headers]


# --- the list of unlinked items ---------------------------------------------------------------


# REQ-F-012, REQ-F-057, П-4: one list for all suppliers, by supplier name then SKU,
# columns supplier, SKU, name, unit, date last seen (РРРР-ММ-ДД); no supplier filter.
def test_unlinked_items_screen(admin_client, world):
    html = admin_client.get("/unlinked-items").text
    headers = lower_headers(html)
    assert len(headers) == len(UNLINKED_COLUMNS)
    for header, start in zip(headers, UNLINKED_COLUMNS, strict=True):
        assert header.startswith(start)
    _, rows = data_table(html)
    assert [r[:5] for r in rows] == [
        ["Альфа", "А-1", "Плита ЛДСП біла 18", "Шт.", "2026-07-12"],
        ["Альфа", "А-2", "Плита ЛДСП сіра 18", "шт", "2026-07-13"],
        ["Бета", "Б-1", "ЛДСП білий 18 мм", "шт", "2026-07-10"],
        ["Бета", "Б-2", "Кромка ПВХ біла", "м.п.", "2026-07-11"],
    ]
    assert not any("supplier_id" in str(f["selects"]) for f in forms(html))


# REQ-F-013: a linked item is not in the list.
def test_linked_item_not_in_unlinked_list(admin_client, world):
    assert (
        link_on_screen(admin_client, world["A1"], world["M1"]["id"]).status_code
        in REDIRECT
    )
    assert unlinked_skus_on_screen(admin_client) == ["А-2", "Б-1", "Б-2"]


# REQ-F-057 criterion: search "білий" shows only items with "білий" in SKU or
# name; search ignores case.
@pytest.mark.parametrize(
    ("q", "skus"),
    [("білий", ["Б-1"]), ("ЛДСП", ["А-1", "А-2", "Б-1"]), ("а-2", ["А-2"])],
)
def test_unlinked_items_search_on_screen(admin_client, world, q, skus):
    assert unlinked_skus_on_screen(admin_client, f"?q={q}") == skus


# REQ-F-057 criterion: 120 unlinked items — first page holds the first 50.
def test_unlinked_items_screen_pages(admin_client, add_item):
    supplier = create_supplier(admin_client, "Альфа")
    for n in reversed(range(120)):
        add_item(supplier["id"], f"А-{n:03d}")
    expected = [f"А-{n:03d}" for n in range(120)]
    assert unlinked_skus_on_screen(admin_client) == expected[:50]
    assert unlinked_skus_on_screen(admin_client, "?page=2") == expected[50:100]
    assert unlinked_skus_on_screen(admin_client, "?page=3") == expected[100:]


# REQ-F-057 criterion (П-3): SKUs "А-2", "А-10", "А 3" — "А 3", "А-10", "А-2".
def test_unlinked_items_sku_order(admin_client, add_item):
    supplier = create_supplier(admin_client, "Альфа")
    for sku in ("А-2", "А-10", "А 3"):
        add_item(supplier["id"], sku)
    assert unlinked_skus_on_screen(admin_client) == ["А 3", "А-10", "А-2"]


# REQ-F-057 (П-3): other characters (by code: "!" < "'" < "-"), then digits, then Cyrillic by the Ukrainian
# alphabet (Ґ, Є, І, Ї in place), then Latin; case is ignored.
def test_unlinked_items_sku_alphabet(admin_client, add_item):
    supplier = create_supplier(admin_client, "Альфа")
    skus = [
        "z1",
        "Я1",
        "ї1",
        "І1",
        "и1",
        "є1",
        "Е1",
        "ґ1",
        "Г1",
        "9",
        "10",
        "-1",
        "!1",
        "'1",
    ]
    for sku in skus:
        add_item(supplier["id"], sku)
    expected = [
        "!1",
        "'1",
        "-1",
        "10",
        "9",
        "Г1",
        "ґ1",
        "Е1",
        "є1",
        "и1",
        "І1",
        "ї1",
        "Я1",
        "z1",
    ]
    assert unlinked_skus_on_screen(admin_client) == expected


# --- linking -----------------------------------------------------------------------------------


# REQ-F-013, REQ-F-014: "Шт." links to "шт"; the item leaves the unlinked list.
def test_link_on_screen(admin_client, world):
    resp = link_on_screen(admin_client, world["A1"], world["M1"]["id"])
    assert resp.status_code in REDIRECT
    assert linked_skus(admin_client, world["M1"]["id"]) == ["А-1"]
    assert "А-1" not in unlinked_skus_on_screen(admin_client)


# BDD-027, REQ-F-014: "м.п." to "п.м." is refused with both units; the item stays
# in the unlinked list.
def test_link_units_differ_on_screen(admin_client, world):
    resp = link_on_screen(admin_client, world["B2"], world["M2"]["id"])
    assert resp.status_code not in REDIRECT
    text = page_text(resp.text)
    assert "м.п." in text and "п.м." in text
    assert "Б-2" in unlinked_skus_on_screen(admin_client)


# BDD-032, REQ-F-048: the second item of supplier А to М1 is refused with "А-1";
# А-2 stays unlinked; Б-1 of supplier Б can be linked.
def test_second_item_same_supplier_on_screen(admin_client, world):
    link_on_screen(admin_client, world["A1"], world["M1"]["id"])
    resp = link_on_screen(admin_client, world["A2"], world["M1"]["id"])
    assert resp.status_code not in REDIRECT
    assert "А-1" in page_text(resp.text)
    assert "А-2" in unlinked_skus_on_screen(admin_client)
    assert (
        link_on_screen(admin_client, world["B1"], world["M1"]["id"]).status_code
        in REDIRECT
    )


# BDD-037, REQ-F-050: link to a deactivated material is refused with its name and
# "activate first"; after activation the same link works.
def test_link_inactive_material_on_screen(admin_client, world):
    mid = world["M1"]["id"]
    admin_client.patch(f"{API}/materials/{mid}", json={"active": False})
    resp = link_on_screen(admin_client, world["B1"], mid)
    assert resp.status_code not in REDIRECT
    text = page_text(resp.text)
    assert "ЛДСП Білий 18 мм" in text and "активуйте" in text
    assert "Б-1" in unlinked_skus_on_screen(admin_client)
    admin_client.patch(f"{API}/materials/{mid}", json={"active": True})
    assert link_on_screen(admin_client, world["B1"], mid).status_code in REDIRECT


# REQ-F-057, П-4, REQ-F-069: the choice of the material is ordered by name
# alphabetically and has a search by name ("лдсп" ignores case).
def test_material_choice_order_and_search(admin_client, world):
    for name in ("Їжак", "Alpha", "Ґанок", "2 Плита"):
        create_material(admin_client, name)
    html = admin_client.get(f"/supplier-items/{world['A1']}/link").text
    assert html
    text = page_text(html)
    order = [
        "2 Плита",
        "Ґанок",
        "Їжак",
        "Кромка біла 2 мм",
        "ЛДСП Білий 18 мм",
        "Alpha",
    ]
    assert ordered(text, order)
    found = page_text(
        admin_client.get(f"/supplier-items/{world['A1']}/link?q=лдсп").text
    )
    assert "ЛДСП Білий 18 мм" in found
    assert "Кромка біла 2 мм" not in found and "Їжак" not in found


# --- the list of linked items of a material (REQ-F-069) ---------------------------------------


# BDD-063, REQ-F-069: М1 with А-1 and Б-1 — both with four columns; ordered by
# supplier, then SKU; actions "зняти" and "перев'язати".
def test_material_links_screen(admin_client, world):
    mid = world["M1"]["id"]
    link(admin_client, world["B1"], mid)
    link(admin_client, world["A1"], mid)
    html = admin_client.get(f"/materials/{mid}/links").text
    assert lower_headers(html) == LINK_COLUMNS
    _, rows = data_table(html)
    assert [r[:4] for r in rows] == [
        ["Альфа", "А-1", "Плита ЛДСП біла 18", "Шт."],
        ["Бета", "Б-1", "ЛДСП білий 18 мм", "шт"],
    ]
    text = page_text(html).lower().replace("’", "'")
    assert "зняти" in text and "перев'язати" in text


# BDD-063, REQ-F-015: "зняти" for А-1 removes it from М1 and returns it to the
# unlinked list.
def test_unlink_on_screen(admin_client, world):
    mid = world["M1"]["id"]
    link(admin_client, world["A1"], mid)
    link(admin_client, world["B1"], mid)
    assert unlink_on_screen(admin_client, world["A1"]).status_code in REDIRECT
    assert linked_skus(admin_client, mid) == ["Б-1"]
    assert "А-1" in unlinked_skus_on_screen(admin_client)
    assert column(admin_client.get(f"/materials/{mid}/links").text, 1) == ["Б-1"]


# REQ-F-069: "перев'язати" Б-1 to М3 removes it from М1 and adds it to М3.
def test_relink_on_screen(admin_client, world):
    m1 = world["M1"]["id"]
    m3 = create_material(admin_client, "ЛДСП Сірий 18 мм", unit="шт")["id"]
    link(admin_client, world["B1"], m1)
    assert link_on_screen(admin_client, world["B1"], m3).status_code in REDIRECT
    assert linked_skus(admin_client, m1) == []
    assert linked_skus(admin_client, m3) == ["Б-1"]


# BDD-063, REQ-F-048: rebinding Б-1 to a material where Б-2 of the same supplier
# is linked is refused with "Б-2".
def test_relink_refused_same_supplier_on_screen(admin_client, add_item, world):
    m1 = world["M1"]["id"]
    m3 = create_material(admin_client, "ЛДСП Сірий 18 мм", unit="шт")["id"]
    b4 = add_item(world["B"]["id"], "Б-4", "ЛДСП сірий", "шт")
    link(admin_client, world["B1"], m1)
    link(admin_client, b4, m3)
    resp = link_on_screen(admin_client, world["B1"], m3)
    assert resp.status_code not in REDIRECT
    assert "Б-4" in page_text(resp.text)
    assert linked_skus(admin_client, m1) == ["Б-1"]


# REQ-F-057: the list of linked items is paged by 50.
def test_material_links_screen_pages(admin_client, add_item):
    material = create_material(admin_client, "ЛДСП Білий 18 мм")
    names = [f"Постачальник {n:02d}" for n in range(52)]
    for n, name in enumerate(names):
        supplier = create_supplier(
            admin_client, name, catalog_url=f"http://localhost:8001/{n}"
        )
        link(admin_client, add_item(supplier["id"], f"П-{n}"), material["id"])
    assert (
        column(admin_client.get(f"/materials/{material['id']}/links").text)
        == names[:50]
    )
    second = column(admin_client.get(f"/materials/{material['id']}/links?page=2").text)
    assert second == names[50:]


# --- REQ-F-005: the manager --------------------------------------------------------------------


# REQ-F-005, REQ-F-069: the manager sees "немає доступу" on these screens.
@pytest.mark.parametrize(
    "path", ["/unlinked-items", "/materials/{m}/links", "/supplier-items/{i}/link"]
)
def test_manager_no_access_link_screens(manager_client, world, path):
    resp = manager_client.get(path.format(m=world["M1"]["id"], i=world["A1"]))
    assert resp.status_code == 403
    text = page_text(resp.text)
    assert NO_ACCESS in text
    assert "А-1" not in text


# REQ-F-003, REQ-F-005: the manager's direct link and unlink requests change nothing.
def test_manager_cannot_link_or_unlink(admin_client, manager_client, world):
    link(admin_client, world["A1"], world["M1"]["id"])
    resp = link_on_screen(manager_client, world["B1"], world["M1"]["id"])
    assert resp.status_code == 403 and NO_ACCESS in page_text(resp.text)
    resp = unlink_on_screen(manager_client, world["A1"])
    assert resp.status_code == 403 and NO_ACCESS in page_text(resp.text)
    assert linked_skus(admin_client, world["M1"]["id"]) == ["А-1"]

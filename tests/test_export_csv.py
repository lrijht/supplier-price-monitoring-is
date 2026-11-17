"""T-60: the export of the comparison list to a CSV file (addendum A-06).

REQ-F-072; REQ-NF-031 (the ``text/csv`` exception, errors in the error model);
REQ-F-035, REQ-F-057, REQ-F-059 (rows, order and search in the file); REQ-F-039
(built at the moment of the export); REQ-NF-032 (only the HTTP request record);
BDD-072; UC-02 alternative flow 1в; contract operation 29
``exportMaterialComparisons`` and scenarios П-38, П-39, Н-46, Н-47 of
tests/contract/scenarios.json.

The API operation is ``GET /api/v1/exports/material-comparisons?q=…``
(spec/openapi.yaml). The address of the screen link is not fixed by the SRS:
the tests take it from the link «Завантажити CSV» on the screen of the
comparison list (``GET /material-comparisons?q=…``) and only require that it is
an address of the web interface, not of ``/api/v1``.

Prices are written by real runs on the simulator (``Market`` in helpers_b3);
"today" and the Kyiv date of the file name come from the controlled clock.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest
from helpers import API, all_pages, assert_problem, create_material, has_login_form
from helpers_b2 import item, kyiv, move_to
from helpers_b3 import Market, all_screen_rows, compact, row_text, screen

# REQ-NF-021: sessions stay open while the tests move the clock by days.
pytestmark = pytest.mark.usefixtures("keep_sessions")

EXPORT = f"{API}/exports/material-comparisons"
BOM = b"\xef\xbb\xbf"
HEADER = ["Матеріал", "Найдешевший постачальник", "Ціна, грн"]
DASH = "—"
LINK_TEXT = "Завантажити CSV"
BASE = "http://testserver"
TODAY = date(2026, 11, 17)

WHITE = "ЛДСП Білий 18 мм"
GREY = "ЛДСП Сірий 18 мм"
BLACK = "ЛДСП Чорний 18 мм"
EDGE = "Кромка біла 2 мм"


# --- helpers --------------------------------------------------------------------------------------


def csv_bytes(*rows: list[str]) -> bytes:
    """The expected file: BOM, the header row, the rows; CRLF after each row.
    Fields are given as they stand in the file (already quoted if needed)."""
    lines = [HEADER, *rows]
    return BOM + "".join(";".join(r) + "\r\n" for r in lines).encode("utf-8")


HEADER_ONLY = csv_bytes()

# REQ-F-072 criterion 1, BDD-072: the file of the manager without search.
BDD072_FILE = csv_bytes(
    [EDGE, DASH, DASH],
    [WHITE, "Альфа", "1000,00"],
    [GREY, "Бета", "1250,50"],
)
BDD072_LDSP_FILE = csv_bytes(
    [WHITE, "Альфа", "1000,00"],
    [GREY, "Бета", "1250,50"],
)


def export(client, q: str | None = None, **params: str):
    """``GET /api/v1/exports/material-comparisons`` with the search ``q``."""
    if q is not None:
        params["q"] = q
    return client.get(EXPORT, params=params or None)


def assert_csv(resp, day: str) -> bytes:
    """200, ``text/csv; charset=utf-8`` and the attachment with the file name of
    the Kyiv date (REQ-F-072, REQ-NF-031, openapi operation 29). Returns the
    body."""
    assert resp.status_code == 200, (resp.status_code, resp.text[:300])
    media, _, params = resp.headers["content-type"].partition(";")
    assert media.strip().lower() == "text/csv"
    assert params.replace(" ", "").lower() == "charset=utf-8"
    disposition = resp.headers.get("content-disposition", "")
    assert re.fullmatch(
        rf'attachment;\s*filename="porivniannia-{day}\.csv"', disposition
    ), disposition
    return resp.content


def csv_rows(body: bytes) -> list[list[str]]:
    """Rows of the file read by an RFC 4180 reader with ";" (header included)."""
    assert body.startswith(BOM), body[:10]
    text = body[len(BOM) :].decode("utf-8")
    assert text.endswith("\r\n")
    assert "\n" not in text.replace("\r\n", ""), "a line ends without CR"
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    assert all(len(r) == 3 for r in rows), rows
    return rows


def money(value: str | None) -> str:
    """ "1000.00" of the API as the file writes it."""
    return value.replace(".", ",") if value is not None else DASH


def rows_of_operation_18(client, q: str | None = None) -> list[list[str]]:
    """The comparison list of operation 18, every page, as rows of the file."""
    path = f"{API}/material-comparisons" + (f"?q={q}" if q is not None else "")
    return [
        [
            r["material"]["name"],
            r["cheapest_supplier"]["name"] if r["cheapest_supplier"] else DASH,
            money(r["price"]),
        ]
        for r in all_pages(client, path)
    ]


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.found.append((self._href, text))
            self._href = None


def download_link(html: str, page: str = "/material-comparisons") -> str:
    """Absolute URL of the only link «Завантажити CSV» of the page."""
    parser = _Anchors()
    parser.feed(html)
    parser.close()
    found = [href for href, text in parser.found if LINK_TEXT in text]
    assert len(found) == 1, f"links «{LINK_TEXT}»: {found}"
    return urljoin(BASE + page, found[0])


def click_download(client, screen_path: str) -> tuple[str, object]:
    """Open the screen, follow its link «Завантажити CSV»; (url, response)."""
    url = download_link(screen(client, screen_path), screen_path)
    return url, client.get(url)


def link_query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def action_records(read_log, config) -> list[dict]:
    return read_log(config.action_log_path)


# --- data -----------------------------------------------------------------------------------------


@pytest.fixture
def bdd072(world):
    """BDD-072 and REQ-F-072 criterion 1, today 2026-11-17: the cheapest price of
    "ЛДСП Білий 18 мм" — Альфа 1000,00 (Бета 1100,00), of "ЛДСП Сірий 18 мм" —
    Бета 1250,50; "Кромка біла 2 мм" has no suitable price; "ЛДСП Чорний 18 мм"
    (Альфа 500,00 — the cheapest of all) is deactivated."""
    m = Market(
        world,
        {
            "Альфа": {"А-1": WHITE, "А-2": BLACK},
            "Бета": {"Б-1": GREY, "Б-2": WHITE},
        },
    )
    m.day(
        TODAY,
        {
            "Альфа": {"А-1": "1000.00", "А-2": "500.00"},
            "Бета": {"Б-1": "1250.50", "Б-2": "1100.00"},
        },
    )
    world.material(EDGE)
    resp = world.admin.patch(f"{API}/materials/{m.mid(BLACK)}", json={"active": False})
    assert resp.status_code == 200, resp.text
    return m


# --- BDD-072 and the file of criterion 1 ------------------------------------------------------------


# BDD-072 in full, UC-02 1в, REQ-F-072: today 2026-11-17. The manager on the
# comparison list without search clicks «Завантажити CSV» — the file
# "porivniannia-2026-11-17.csv", UTF-8 with BOM, the header row
# "Матеріал;Найдешевший постачальник;Ціна, грн", then "Кромка біла 2 мм;—;—",
# "ЛДСП Білий 18 мм;А;1000,00", "ЛДСП Сірий 18 мм;Б;1250,50" in this order, no row
# of "ЛДСП Чорний 18 мм". With search "лдсп" — the header and only the two ЛДСП
# rows. The administrator through the API — 200 text/csv, the same content as the
# manager's file without search.
def test_export_bdd072(bdd072, manager_client, admin_client):
    _, resp = click_download(manager_client, "/material-comparisons")
    manager_file = assert_csv(resp, "2026-11-17")
    assert manager_file.startswith(BOM)
    assert manager_file == BDD072_FILE
    assert BLACK.encode("utf-8") not in manager_file

    _, resp = click_download(manager_client, "/material-comparisons?q=лдсп")
    assert assert_csv(resp, "2026-11-17") == BDD072_LDSP_FILE

    admin_file = assert_csv(export(admin_client), "2026-11-17")
    assert admin_file == manager_file


# REQ-F-072 criterion 1, П-38, Р-131: the manager's file through the API without
# search — name "porivniannia-2026-11-17.csv", bytes EF BB BF first, rows
# "Матеріал;Найдешевший постачальник;Ціна, грн", "Кромка біла 2 мм;—;—",
# "ЛДСП Білий 18 мм;Альфа;1000,00", "ЛДСП Сірий 18 мм;Бета;1250,50" in this order,
# each ending with CRLF; the price "1250,50" without "грн".
def test_file_of_criterion_1(bdd072, manager_client):
    body = assert_csv(export(manager_client), "2026-11-17")
    assert body[:3] == b"\xef\xbb\xbf"
    assert body == BDD072_FILE
    assert body.count(b"\r\n") == 4
    assert "грн".encode() not in body.split(b"\r\n", 1)[1]
    assert csv_rows(body)[0] == HEADER


# --- search, empty file ----------------------------------------------------------------------------------


# REQ-F-072 criterion 2, REQ-F-059, П-39: search "лдсп" (and "ЛДСП") — the header
# and only "ЛДСП Білий 18 мм" and "ЛДСП Сірий 18 мм"; the administrator gets the
# same file.
@pytest.mark.parametrize("q", ["лдсп", "ЛДСП"])
def test_search_ldsp(bdd072, manager_client, admin_client, q):
    assert assert_csv(export(manager_client, q), "2026-11-17") == BDD072_LDSP_FILE
    assert assert_csv(export(admin_client, q), "2026-11-17") == BDD072_LDSP_FILE


# REQ-F-072 criterion 2: a search without matches gives a file with the header row
# only.
def test_search_without_matches_header_only(bdd072, manager_client):
    body = assert_csv(export(manager_client, "фанера"), "2026-11-17")
    assert body == HEADER_ONLY
    assert csv_rows(body) == [HEADER]


# REQ-F-072 (Р-131 "якщо матеріалів для файлу немає"): no materials at all — the
# file holds the header row only (the default clock: 2026-07-15 by Kyiv).
def test_no_materials_header_only(manager_client):
    assert assert_csv(export(manager_client), "2026-07-15") == HEADER_ONLY


# --- all pages, order --------------------------------------------------------------------------------------


# REQ-F-072 criterion 3, REQ-F-057: 120 materials — the header and 120 rows in the
# order of pages 1–3 of the comparison list screen, not split by 50; the link on
# page 2 of the screen gives the same whole file; a "page" parameter of the API
# is not a parameter of the operation and is ignored.
def test_120_materials_all_pages(admin_client, manager_client):
    names = [f"Матеріал {n:03d}" for n in range(120, 0, -1)]
    for name in names:
        create_material(admin_client, name)
    body = assert_csv(export(manager_client), "2026-07-15")
    rows = csv_rows(body)
    assert len(rows) == 121
    assert rows[0] == HEADER
    screen_names = [
        r[0] for r in all_screen_rows(manager_client, "/material-comparisons")
    ]
    assert len(screen_names) == 120
    assert [r[0] for r in rows[1:]] == screen_names == sorted(names)
    assert rows[1:] == [[n, DASH, DASH] for n in sorted(names)]
    _, resp = click_download(manager_client, "/material-comparisons?page=2")
    assert assert_csv(resp, "2026-07-15") == body
    assert assert_csv(export(manager_client, page="2"), "2026-07-15") == body


# REQ-F-072, REQ-F-057 criterion (П-3, Р-113): the file keeps the alphabetical
# order of the screen — "2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра",
# "Їжак", "Alpha".
def test_alphabetical_order(admin_client, manager_client):
    for name in ["Їжак", "Alpha", "бета", "Ґанок", "Іскра", "Гама", "2 Плита", "Альфа"]:
        create_material(admin_client, name)
    rows = csv_rows(assert_csv(export(manager_client), "2026-07-15"))
    order = ["2 Плита", "Альфа", "бета", "Гама", "Ґанок", "Іскра", "Їжак", "Alpha"]
    assert [r[0] for r in rows[1:]] == order


# --- deactivated --------------------------------------------------------------------------------------------


# REQ-F-072 criterion 4, REQ-F-049: the deactivated material "ЛДСП Чорний 18 мм" is
# not in the file, with and without search, though its price 500,00 is the lowest.
@pytest.mark.parametrize("q", [None, "чорний"])
def test_deactivated_material_absent(bdd072, manager_client, q):
    body = assert_csv(export(manager_client, q), "2026-11-17")
    assert BLACK not in [r[0] for r in csv_rows(body)]
    assert b"500,00" not in body
    if q is not None:
        assert body == HEADER_ONLY


# REQ-F-072 criterion 4, REQ-F-011, REQ-F-037: the price 900,00 of the deactivated
# supplier Альфа does not become the cheapest — the file shows "М1;Бета;1000,00",
# as the screen does.
def test_deactivated_supplier_price_not_cheapest(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М1"}})
    m.day(TODAY, {"Альфа": {"А-1": "900.00"}, "Бета": {"Б-1": "1000.00"}})
    world.set_active("Альфа", False)
    body = assert_csv(export(manager_client), "2026-11-17")
    assert body == csv_bytes(["М1", "Бета", "1000,00"])
    (screen_row,) = all_screen_rows(manager_client, "/material-comparisons")
    assert "Бета" in row_text(screen_row) and "Альфа" not in row_text(screen_row)


# --- format details -----------------------------------------------------------------------------------------


# REQ-F-072 criterion 5, RFC 4180: the name "Плита; біла" is written as
# «"Плита; біла"»; a name with quotes 'Плита "Люкс"' — «"Плита ""Люкс"""»; a
# supplier name with ";" is quoted too. An RFC 4180 reader with ";" reads 3
# columns in every row and the names back unchanged.
def test_rfc4180_quotes(world, manager_client):
    world.supplier("Бета; Плюс", "betaplus", [item("П-1", "100.00")])
    world.at(2026, 11, 16)
    world.run()
    world.material("Плита; біла")
    world.material('Плита "Люкс"')
    world.link("П-1", "Плита; біла")
    world.page("Бета; Плюс", [item("П-1", "1000.00")])
    world.at(2026, 11, 17)
    world.run()
    body = assert_csv(export(manager_client), "2026-11-17")
    assert body == csv_bytes(
        ['"Плита ""Люкс"""', DASH, DASH],
        ['"Плита; біла"', '"Бета; Плюс"', "1000,00"],
    )
    assert csv_rows(body)[1:] == [
        ['Плита "Люкс"', DASH, DASH],
        ["Плита; біла", "Бета; Плюс", "1000,00"],
    ]


# REQ-F-072, Д.11 «Ціна, грн»: the price with a decimal comma and two digits, without
# "грн" and without a thousands separator — 12345,60 and 5,00.
def test_price_format(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М2"}})
    m.day(TODAY, {"Альфа": {"А-1": "12345.60"}, "Бета": {"Б-1": "5.00"}})
    body = assert_csv(export(manager_client), "2026-11-17")
    assert body == csv_bytes(["М1", "Альфа", "12345,60"], ["М2", "Бета", "5,00"])


# REQ-F-072 criterion 6, risk 3 of A-06: the file name follows the Kyiv date —
# at 00:30 on 2026-11-18 by Kyiv (22:30 UTC on 2026-11-17) it is
# "porivniannia-2026-11-18.csv"; at 23:59 on 2026-11-17 — "…-2026-11-17.csv".
@pytest.mark.parametrize(
    ("moment", "day"),
    [
        (kyiv(2026, 11, 18, 0, 30), "2026-11-18"),
        (kyiv(2026, 11, 17, 23, 59), "2026-11-17"),
    ],
)
def test_file_name_kyiv_date(clock, manager_client, moment, day):
    move_to(clock, moment)
    assert assert_csv(export(manager_client), day) == HEADER_ONLY


# REQ-F-039, REQ-F-072 ("за даними на момент вивантаження"): the file is built when
# it is requested — after a new run with other prices the next file shows them.
def test_built_at_the_moment_of_export(world, manager_client):
    m = Market(world, {"Альфа": {"А-1": "М1"}, "Бета": {"Б-1": "М1"}})
    m.day(date(2026, 11, 16), {"Альфа": {"А-1": "1000.00"}, "Бета": {"Б-1": "1100.00"}})
    first = assert_csv(export(manager_client), "2026-11-16")
    assert first == csv_bytes(["М1", "Альфа", "1000,00"])
    m.day(TODAY, {"Альфа": {"А-1": "1200.00"}, "Бета": {"Б-1": "1100.00"}})
    second = assert_csv(export(manager_client), "2026-11-17")
    assert second == csv_bytes(["М1", "Бета", "1100,00"])


# --- the same data as the screen and operation 18 --------------------------------------------------------------


# REQ-F-072 ("ті самі рядки й колонки, що й екран"), REQ-F-035, REQ-F-059, risk 1 of
# A-06: on the same data the rows of the file are the rows of operation 18 (every
# page, the price with a comma, "—" without a price) and of the screen (the name
# first, the cheapest supplier and the price in the row) — without search and
# with search "лдсп".
@pytest.mark.parametrize("q", [None, "лдсп"])
def test_same_rows_as_screen_and_operation_18(bdd072, manager_client, q):
    rows = csv_rows(assert_csv(export(manager_client, q), "2026-11-17"))[1:]
    assert rows == rows_of_operation_18(manager_client, q)
    screen_path = "/material-comparisons" + (f"?q={q}" if q else "")
    on_screen = all_screen_rows(manager_client, screen_path)
    assert [r[0] for r in rows] == [r[0] for r in on_screen]
    for (name, supplier, price), shown in zip(rows, on_screen, strict=True):
        text = row_text(shown)
        assert shown[0] == name
        if supplier == DASH:
            assert DASH in text
        else:
            assert supplier in text and price in compact(text)


# --- both roles, the screen link ---------------------------------------------------------------------------------


# REQ-F-072 criterion 7, Р-132: the administrator gets the file with the same
# content as the manager — without search and with search "лдсп".
@pytest.mark.parametrize("q", [None, "лдсп"])
def test_both_roles_same_content(bdd072, manager_client, admin_client, q):
    manager_file = assert_csv(export(manager_client, q), "2026-11-17")
    assert assert_csv(export(admin_client, q), "2026-11-17") == manager_file


# REQ-F-072, UC-02 1в, Р-129: the comparison list screen of each role has the link
# «Завантажити CSV»; it leads to an address of the web interface (not /api/v1),
# passes the current search q ("лдсп") or none, and gives the same file as the
# API operation with the same search, with the same headers.
@pytest.mark.parametrize("role", ["manager", "admin"])
@pytest.mark.parametrize("q", [None, "лдсп"])
def test_screen_link_passes_search(bdd072, manager_client, admin_client, role, q):
    client = manager_client if role == "manager" else admin_client
    screen_path = "/material-comparisons" + (f"?q={q}" if q else "")
    url, resp = click_download(client, screen_path)
    assert not urlsplit(url).path.startswith(API)
    assert link_query(url).get("q", [""]) == [q or ""]
    body = assert_csv(resp, "2026-11-17")
    assert body == (BDD072_LDSP_FILE if q else BDD072_FILE)
    assert body == assert_csv(export(client, q), "2026-11-17")


# REQ-F-072 criterion 7, REQ-F-001, Р-132: without a session the link of the
# screen leads to the login form, and no file is given.
def test_screen_link_without_session_login_form(manager_client, client):
    url = download_link(screen(manager_client, "/material-comparisons?q=лдсп"))
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    assert urlsplit(resp.headers["location"]).path.endswith("/login")
    page = client.get(url)
    assert page.headers["content-type"].startswith("text/html")
    assert has_login_form(page.text)
    assert BOM not in page.content


# --- errors ------------------------------------------------------------------------------------------------------


# REQ-F-072 criterion 7, REQ-NF-031, Н-46: the API without a session — 401
# unauthenticated in the error model (application/problem+json), no file and no
# Content-Disposition; with search too.
@pytest.mark.parametrize("q", [None, "лдсп"])
def test_api_without_session_401(accounts, client, q):
    resp = export(client, q)
    assert_problem(resp, 401, "unauthenticated")
    assert "content-disposition" not in resp.headers
    assert "location" not in resp.headers


# REQ-NF-031, REQ-NF-018, Н-47: an artificial storage failure (the daily prices
# table dropped after start) — the export answers 500 internal_error in the
# error model, without "errors", without internal details and without a file.
def test_api_storage_failure_500(admin_client, manager_client, config):
    create_material(admin_client, "М1")
    with sqlite3.connect(config.database_path) as db:
        db.execute("DROP TABLE daily_prices")
    resp = export(manager_client)
    body = assert_problem(resp, 500, "internal_error")
    assert "errors" not in body
    assert "content-disposition" not in resp.headers
    for detail in ("daily_prices", "Traceback", "sqlite", "OperationalError"):
        assert detail not in resp.text


# --- changes nothing; the action log ----------------------------------------------------------------------------


def snapshot(admin) -> dict:
    """What the administrator can read through the API."""
    paths = [
        "/material-comparisons",
        "/materials",
        "/suppliers",
        "/events",
        "/run-log-entries",
        "/unlinked-items",
        "/attention-items",
        "/supplier-update-statuses",
    ]
    data: dict = {p: all_pages(admin, f"{API}{p}") for p in paths}
    data["/settings"] = admin.get(f"{API}/settings").json()
    for material in data["/materials"]:
        mid = material["id"]
        for path in (
            f"/material-comparisons/{mid}",
            f"/materials/{mid}/price-history?period=all",
            f"/materials/{mid}/links",
        ):
            data[path] = admin.get(f"{API}{path}").json()
    return data


# REQ-F-072 criterion 7, Р-132: the export changes nothing — after exports of both
# roles through the API and the screen link, with and without search, everything
# the administrator reads through the API is the same.
def test_export_changes_nothing(bdd072, manager_client, admin_client):
    before = snapshot(admin_client)
    for client in (manager_client, admin_client):
        for q in (None, "лдсп"):
            assert_csv(export(client, q), "2026-11-17")
        click_download(client, "/material-comparisons?q=лдсп")
    assert snapshot(admin_client) == before


# REQ-F-072 criterion 7, REQ-NF-032, Р-132: for an export the action log gets only
# the record of the HTTP request — method GET, the path without the query string,
# status 200, the login and role — and no other record (no event of its own);
# through the API and through the screen link.
@pytest.mark.parametrize("way", ["api", "link"])
def test_action_log_only_http_request(bdd072, manager_client, config, read_log, way):
    if way == "api":
        url = BASE + EXPORT + "?q=лдсп"
        path = EXPORT
    else:
        url = download_link(screen(manager_client, "/material-comparisons?q=лдсп"))
        path = urlsplit(url).path
    before = len(action_records(read_log, config))
    assert_csv(manager_client.get(url), "2026-11-17")
    new = action_records(read_log, config)[before:]
    assert [r["event"] for r in new] == ["http_request"], new
    (record,) = new
    assert (record["method"], record["path"], record["status"]) == ("GET", path, 200)
    assert "?" not in record["path"]
    assert (record["login"], record["role"]) == ("manager", "manager")

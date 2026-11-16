"""Helpers shared by the B1.2 tests: API calls, problem checks, HTML reading.

Plain functions, no import of ``spm``: the system is reached only through HTTP
and the fixtures in ``conftest.py``.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

PROBLEM_TYPE = "application/problem+json"
PROBLEM_FIELDS = {"type", "title", "status", "detail", "code"}
# Problem.title of the contract (docs/api/resources.md, section 4).
TITLES = {
    401: "Неавторизовано",
    403: "Заборонено",
    404: "Не знайдено",
    405: "Метод не дозволено",
    409: "Конфлікт",
    415: "Непідтримуваний тип даних",
    422: "Необроблюваний вміст",
    500: "Внутрішня помилка сервера",
}
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
NO_ACCESS = "немає доступу"
# Contract detail of invalid_credentials; the login form shows the same text.
WRONG_CREDENTIALS = "Неправильний логін або пароль"

ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin-test-password-1"
MANAGER_LOGIN = "manager"
MANAGER_PASSWORD = "manager-test-password-1"

API = "/api/v1"


# --- API ----------------------------------------------------------------------


def assert_problem(resp, status: int, code: str) -> dict:
    """The response is an error of the contract's error model."""
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].split(";")[0].strip() == PROBLEM_TYPE
    body = resp.json()
    assert PROBLEM_FIELDS <= set(body)
    assert set(body) <= PROBLEM_FIELDS | {"errors"}
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["code"] == code
    assert body["title"] == TITLES[status]
    assert isinstance(body["detail"], str) and CYRILLIC.search(body["detail"])
    if status == 422:
        assert isinstance(body.get("errors"), list) and body["errors"]
        for error in body["errors"]:
            assert {"field", "code", "detail"} <= set(error)
            assert CYRILLIC.search(error["detail"])
    return body


def error_codes(body: dict) -> list[tuple[str | None, str]]:
    return [(e["field"], e["code"]) for e in body.get("errors", [])]


def api_login(client, login: str, password: str):
    return client.post(f"{API}/sessions", json={"login": login, "password": password})


def create_supplier(
    client,
    name: str,
    *,
    catalog_url: str | None = None,
    parser: str = "table_layout",
    active: bool = True,
) -> dict:
    body = {
        "name": name,
        "catalog_url": catalog_url or "http://localhost:8001/catalog/x",
        "parser": parser,
        "active": active,
    }
    resp = client.post(f"{API}/suppliers", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_material(
    client, name: str, *, unit: str = "шт", active: bool = True
) -> dict:
    resp = client.post(
        f"{API}/materials", json={"name": name, "unit": unit, "active": active}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def link(client, item_id: int, material_id: int):
    return client.put(
        f"{API}/supplier-items/{item_id}/link", json={"material_id": material_id}
    )


def all_pages(client, path: str) -> list[dict]:
    """Items of every page of a paged list."""
    items: list[dict] = []
    page = 1
    sep = "&" if "?" in path else "?"
    while True:
        body = client.get(f"{path}{sep}page={page}").json()
        items.extend(body["items"])
        if page >= body["total_pages"]:
            return items
        page += 1


# --- HTML ---------------------------------------------------------------------


def normalize(text: str) -> str:
    """Collapse whitespace (incl. no-break spaces) and unify apostrophes."""
    text = text.replace("’", "'").replace("ʼ", "'")
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.tables: list[dict] = []
        self.forms: list[dict] = []
        self._stack: list[str] = []
        self._table: dict | None = None
        self._section: str | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._form: dict | None = None
        self._select: dict | None = None
        self._option: dict | None = None
        self._skip = 0
        self._row_th = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "table":
            self._table = {"headers": [], "rows": []}
            self.tables.append(self._table)
        elif tag in ("thead", "tbody") and self._table is not None:
            self._section = tag
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._row_th = True
        elif tag in ("th", "td") and self._row is not None:
            self._cell = []
            self._row_th = self._row_th and tag == "th"
        elif tag == "form":
            self._form = {
                "action": a.get("action", ""),
                "method": a.get("method", "get").lower(),
                "inputs": [],
                "selects": {},
                "buttons": [],
            }
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            self._form["inputs"].append(a)
        elif tag == "button" and self._form is not None:
            self._form["buttons"].append(a)
        elif tag == "select" and self._form is not None:
            self._select = {"name": a.get("name", ""), "options": []}
            self._form["selects"][self._select["name"]] = self._select["options"]
        elif tag == "option" and self._select is not None:
            self._option = {"value": a.get("value"), "text": []}
            self._select["options"].append(self._option)
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "td", "th"):
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("th", "td") and self._cell is not None and self._row is not None:
            self._row.append(normalize("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            in_head = self._section == "thead"
            if in_head or (self._row_th and self._row and not self._table["headers"]):
                self._table["headers"] = self._row
            else:
                self._table["rows"].append(self._row)
            self._row = None
        elif tag in ("thead", "tbody"):
            self._section = None
        elif tag == "table":
            self._table = None
        elif tag == "form":
            self._form = None
        elif tag == "select":
            self._select = None
        elif tag == "option" and self._option is not None:
            text = normalize("".join(self._option["text"]))
            self._option["text"] = text
            if self._option["value"] is None:
                self._option["value"] = text
            self._option = None
        if tag in ("p", "div", "li", "tr", "h1", "h2", "td", "th", "button"):
            self.text.append(" ")

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._option is not None:
            self._option["text"].append(data)


def parse_page(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def page_text(html: str) -> str:
    """Visible text of the page, normalized."""
    return normalize("".join(parse_page(html).text))


def data_table(html: str) -> tuple[list[str], list[list[str]]]:
    """Headers and rows of the page's data table.

    The data table is the ``<table>`` with a ``<thead>``. Headers are the
    non-empty ``<th>`` texts (an actions column has an empty header); each
    row is the list of its ``<td>`` texts, data cells first.
    """
    tables = [t for t in parse_page(html).tables if t["headers"]]
    assert len(tables) == 1, f"expected one data table, found {len(tables)}"
    table = tables[0]
    headers = [h for h in table["headers"] if h]
    return headers, table["rows"]


def column(html: str, index: int = 0) -> list[str]:
    _, rows = data_table(html)
    return [row[index] for row in rows]


def forms(html: str) -> list[dict]:
    return parse_page(html).forms


def has_login_form(html: str) -> bool:
    for form in forms(html):
        names = {i.get("name") for i in form["inputs"]}
        types = {i.get("name"): i.get("type", "text") for i in form["inputs"]}
        if (
            form["method"] == "post"
            and {"login", "password"} <= names
            and types["password"] == "password"
        ):
            return True
    return False


def has_logout_button(html: str) -> bool:
    for form in forms(html):
        if form["method"] == "post" and form["action"].endswith("/logout"):
            labels = [normalize(b.get("value", "")) for b in form["buttons"]]
            labels += [normalize(i.get("value", "")) for i in form["inputs"]]
            text = page_text(html)
            if "Вийти" in labels or "Вийти" in text:
                return True
    return False


def ordered(text: str, names: list[str]) -> bool:
    """Every name occurs in the text, in the given order."""
    positions = [text.find(n) for n in names]
    return -1 not in positions and positions == sorted(positions)

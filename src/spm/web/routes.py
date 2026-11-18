"""Screens of the web interface: server HTML pages without JavaScript (REQ-NF-015).

Thin: each screen calls the same functions of ``auth`` and ``services`` as the
API (REQ-NF-031). Addresses mirror the API paths without ``/api/v1``. Forms
post ``application/x-www-form-urlencoded``; a successful action redirects
(303), a refused one shows the form again with the reason.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from spm.auth import SESSION_COOKIE, Account, AuthService
from spm.auth.service import (
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_SCOPE,
    WRONG_CREDENTIALS,
)
from spm.clock import to_kyiv
from spm.services import (
    EVENT_KINDS,
    MATERIAL,
    PERIODS,
    RUN,
    SETTINGS,
    SUPPLIER,
    SUPPLIER_ITEM,
    VOLUME_ACCEPTANCE,
    Actor,
    Conflict,
    Directories,
    NotFound,
    RunLogEntry,
    Runs,
    SettingsService,
    ValidationFailed,
    Views,
)
from spm.services.errors import REQUIRED, FieldError, ServiceError

TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


# --- formats of the screens (REQ-NF-030; sums with a comma, percents with a sign) ------------


def money(value) -> str:
    """1000.5 -> "1000,50"; no value -> "—"."""
    return f"{value:.2f}".replace(".", ",") if value is not None else "—"


def signed_money(value) -> str:
    return ("+" if value > 0 else "") + money(value)


def percent(value) -> str:
    """10 -> "+10,0 %", -1 -> "-1,0 %", 0 -> "0,0 %"; no value -> "—"."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}".replace(".", ",") + " %"


TEMPLATES.filters.update(money=money, signed_money=signed_money, percent=percent)

router = APIRouter()

LOGIN_PATH = "/login"
HOME_PATH = "/"
COMPARISON_EXPORT_PATH = "/exports/material-comparisons"  # REQ-F-072


# --- helpers ----------------------------------------------------------------------------------


def render(name: str, status: int = 200, **context) -> HTMLResponse:
    return HTMLResponse(TEMPLATES.get_template(name).render(**context), status)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def directories(request: Request) -> Directories:
    return request.app.state.directories


def settings_service(request: Request) -> SettingsService:
    return request.app.state.settings


def runs_service(request: Request) -> Runs:
    return request.app.state.runs


def views_service(request: Request) -> Views:
    return request.app.state.views


def session_account(request: Request) -> Account | None:
    return auth_service(request).resolve(request.cookies.get(SESSION_COOKIE))


def actor(account: Account) -> Actor:
    return Actor(account.login, account.role)


def int_or_none(value: str) -> int | None:
    return int(value) if value.isascii() and value.isdigit() else None


def known_id(value: int | None) -> int:
    """An id for a service lookup: an address part that is not a number becomes
    0, which no record has, so the screen answers «not found»."""
    return value if value is not None else 0


def page_number(request: Request) -> int:
    """The page of a list; anything but an integer from 1 is the first page."""
    number = int_or_none(request.query_params.get("page", ""))
    return number if number and number >= 1 else 1


def messages(exc: ServiceError) -> list[str]:
    if isinstance(exc, ValidationFailed):
        return [f"{label(e.field)}: {e.detail}" for e in exc.errors]
    if isinstance(exc, Conflict):
        return [exc.detail]
    return []


FIELD_LABELS = {
    "name": "Назва",
    "catalog_url": "Адреса каталогу",
    "parser": "Розбирач",
    "active": "Активний",
    "unit": "Одиниця виміру",
    "material_id": "Матеріал",
    "update_time": "Час щоденного оновлення",
    "notification_threshold": "Поріг сповіщень",
    "run_id": "Запуск",
    "supplier_id": "Постачальник",
}


def label(field: str | None) -> str:
    return FIELD_LABELS.get(field or "", "Запит")


def refused_status(exc: ServiceError) -> int:
    return 409 if isinstance(exc, Conflict) else 422


def not_found_page(account: Account | None) -> HTMLResponse:
    return render("not_found.html", 404, account=account)


def user_screen(request: Request) -> Account | Response:
    """The account of the session, or the login form without a session."""
    account = session_account(request)
    if account is None:
        return redirect(LOGIN_PATH)
    return account


def admin_screen(
    request: Request,
    *,
    action: str,
    object_type: str | None,
    object_id: int | None = None,
) -> Account | Response:
    """The administrator's account, or the answer: the login form without a
    session, «немає доступу» for the manager (REQ-F-001, REQ-F-005)."""
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    if not account.is_admin:
        auth_service(request).deny(
            account, action=action, object_type=object_type, object_id=object_id
        )
        return render("no_access.html", 403, account=account)
    return account


async def form_data(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: v for k, v in form.items() if isinstance(v, str)}


# --- handlers the application installs for unknown addresses -----------------------------------


async def not_found(request: Request) -> Response:
    """Without a session every screen address leads to the login form."""
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    return not_found_page(account)


async def method_not_allowed(request: Request) -> Response:
    return render("not_found.html", 405, account=None)


# --- login, logout (REQ-F-001, REQ-F-002) --------------------------------------------------------


@router.get(LOGIN_PATH)
async def login_form(request: Request) -> Response:
    return render("login.html", account=None, errors=[], login="")


@router.post(LOGIN_PATH)
async def login(request: Request) -> Response:
    form = await form_data(request)
    entered = form.get("login", "")
    opened = auth_service(request).login(entered, form.get("password", ""))
    if opened is None:
        return render(
            "login.html", 401, account=None, errors=[WRONG_CREDENTIALS], login=entered
        )
    _, cookie = opened
    response = redirect(HOME_PATH)
    response.set_cookie(
        SESSION_COOKIE, cookie, max_age=SESSION_COOKIE_MAX_AGE, **SESSION_COOKIE_SCOPE
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    auth_service(request).logout(request.cookies.get(SESSION_COOKIE))
    response = redirect(LOGIN_PATH)
    response.delete_cookie(SESSION_COOKIE, **SESSION_COOKIE_SCOPE)
    return response


@router.get(HOME_PATH)
async def home(request: Request) -> Response:
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    return render("home.html", account=account)


# --- suppliers (REQ-F-007, REQ-F-010, REQ-F-068) ----------------------------------------------------


def supplier_values(form: dict[str, str]) -> dict:
    return {
        "name": form.get("name", ""),
        "catalog_url": form.get("catalog_url", ""),
        "parser": form.get("parser", ""),
        "active": "active" in form,  # an unchecked box sends no field
    }


def supplier_form(request, account, *, heading, action, values, errors, status=200):
    return render(
        "supplier_form.html",
        status,
        account=account,
        heading=heading,
        action=action,
        values=values,
        errors=errors,
        parsers=directories(request).parsers(),
    )


@router.get("/suppliers")
async def suppliers_screen(request: Request) -> Response:
    account = admin_screen(request, action="supplier_list", object_type=SUPPLIER)
    if not isinstance(account, Account):
        return account
    page = directories(request).list_suppliers(page_number(request))
    return render("suppliers.html", account=account, page=page)


@router.get("/suppliers/new")
async def new_supplier_screen(request: Request) -> Response:
    account = admin_screen(request, action="supplier_create", object_type=SUPPLIER)
    if not isinstance(account, Account):
        return account
    values = {"name": "", "catalog_url": "", "parser": "", "active": True}
    return supplier_form(
        request,
        account,
        heading="Новий постачальник",
        action="/suppliers",
        values=values,
        errors=[],
    )


@router.post("/suppliers")
async def create_supplier(request: Request) -> Response:
    account = admin_screen(request, action="supplier_create", object_type=SUPPLIER)
    if not isinstance(account, Account):
        return account
    values = supplier_values(await form_data(request))
    try:
        directories(request).create_supplier(actor(account), **values)
    except ServiceError as exc:
        return supplier_form(
            request,
            account,
            heading="Новий постачальник",
            action="/suppliers",
            values=values,
            errors=messages(exc),
            status=refused_status(exc),
        )
    return redirect("/suppliers")


@router.get("/suppliers/{supplier_id}")
async def supplier_screen(request: Request, supplier_id: str) -> Response:
    sid = int_or_none(supplier_id)
    account = admin_screen(
        request, action="supplier_read", object_type=SUPPLIER, object_id=sid
    )
    if not isinstance(account, Account):
        return account
    try:
        supplier = directories(request).get_supplier(known_id(sid))
    except NotFound:
        return not_found_page(account)
    values = {
        "name": supplier.name,
        "catalog_url": supplier.catalog_url,
        "parser": supplier.parser,
        "active": supplier.active,
    }
    return supplier_form(
        request,
        account,
        heading=f"Постачальник «{supplier.name}»",
        action=f"/suppliers/{supplier.id}",
        values=values,
        errors=[],
    )


@router.post("/suppliers/{supplier_id}")
async def update_supplier(request: Request, supplier_id: str) -> Response:
    sid = int_or_none(supplier_id)
    account = admin_screen(
        request, action="supplier_update", object_type=SUPPLIER, object_id=sid
    )
    if not isinstance(account, Account):
        return account
    values = supplier_values(await form_data(request))
    service = directories(request)
    try:
        current = service.get_supplier(known_id(sid))
        service.update_supplier(actor(account), current.id, values)
    except NotFound:
        return not_found_page(account)
    except ServiceError as exc:
        return supplier_form(
            request,
            account,
            heading=f"Постачальник «{current.name}»",
            action=f"/suppliers/{current.id}",
            values=values,
            errors=messages(exc),
            status=refused_status(exc),
        )
    return redirect("/suppliers")


# --- materials (REQ-F-008, REQ-F-009, REQ-F-010, REQ-F-068) -------------------------------------------


def material_values(form: dict[str, str]) -> dict:
    return {
        "name": form.get("name", ""),
        "unit": form.get("unit", ""),
        "active": "active" in form,
    }


def material_form(account, *, heading, action, values, errors, status=200):
    return render(
        "material_form.html",
        status,
        account=account,
        heading=heading,
        action=action,
        values=values,
        errors=errors,
    )


@router.get("/materials")
async def materials_screen(request: Request) -> Response:
    account = admin_screen(request, action="material_list", object_type=MATERIAL)
    if not isinstance(account, Account):
        return account
    page = directories(request).list_materials(page_number(request))
    return render("materials.html", account=account, page=page)


@router.get("/materials/new")
async def new_material_screen(request: Request) -> Response:
    account = admin_screen(request, action="material_create", object_type=MATERIAL)
    if not isinstance(account, Account):
        return account
    return material_form(
        account,
        heading="Новий матеріал",
        action="/materials",
        values={"name": "", "unit": "", "active": True},
        errors=[],
    )


@router.post("/materials")
async def create_material(request: Request) -> Response:
    account = admin_screen(request, action="material_create", object_type=MATERIAL)
    if not isinstance(account, Account):
        return account
    values = material_values(await form_data(request))
    try:
        directories(request).create_material(actor(account), **values)
    except ServiceError as exc:
        return material_form(
            account,
            heading="Новий матеріал",
            action="/materials",
            values=values,
            errors=messages(exc),
            status=refused_status(exc),
        )
    return redirect("/materials")


@router.get("/materials/{material_id}")
async def material_screen(request: Request, material_id: str) -> Response:
    mid = int_or_none(material_id)
    account = admin_screen(
        request, action="material_read", object_type=MATERIAL, object_id=mid
    )
    if not isinstance(account, Account):
        return account
    try:
        material = directories(request).get_material(known_id(mid))
    except NotFound:
        return not_found_page(account)
    return material_form(
        account,
        heading=f"Матеріал «{material.name}»",
        action=f"/materials/{material.id}",
        values={
            "name": material.name,
            "unit": material.unit,
            "active": material.active,
        },
        errors=[],
    )


@router.post("/materials/{material_id}")
async def update_material(request: Request, material_id: str) -> Response:
    mid = int_or_none(material_id)
    account = admin_screen(
        request, action="material_update", object_type=MATERIAL, object_id=mid
    )
    if not isinstance(account, Account):
        return account
    values = material_values(await form_data(request))
    service = directories(request)
    try:
        current = service.get_material(known_id(mid))
        service.update_material(actor(account), current.id, values)
    except NotFound:
        return not_found_page(account)
    except ServiceError as exc:
        return material_form(
            account,
            heading=f"Матеріал «{current.name}»",
            action=f"/materials/{current.id}",
            values=values,
            errors=messages(exc),
            status=refused_status(exc),
        )
    return redirect("/materials")


@router.get("/materials/{material_id}/links")
async def material_links_screen(request: Request, material_id: str) -> Response:
    mid = int_or_none(material_id)
    account = admin_screen(
        request, action="material_links_read", object_type=MATERIAL, object_id=mid
    )
    if not isinstance(account, Account):
        return account
    try:
        material, page = directories(request).list_material_links(
            known_id(mid), page_number(request)
        )
    except NotFound:
        return not_found_page(account)
    return render("material_links.html", account=account, material=material, page=page)


# --- unlinked items and links (REQ-F-012…REQ-F-015, REQ-F-048, REQ-F-050, REQ-F-069) ----------------


@router.get("/unlinked-items")
async def unlinked_items_screen(request: Request) -> Response:
    account = admin_screen(
        request, action="unlinked_items_read", object_type=SUPPLIER_ITEM
    )
    if not isinstance(account, Account):
        return account
    q = request.query_params.get("q", "")
    page = directories(request).list_unlinked_items(page_number(request), q)
    query = "&" + urlencode({"q": q}) if q else ""
    return render("unlinked_items.html", account=account, page=page, q=q, query=query)


def link_choice(request, account, item, q, errors, status=200) -> HTMLResponse:
    service = directories(request)
    current = (
        service.get_material(item.material_id) if item.material_id is not None else None
    )
    return render(
        "link_choice.html",
        status,
        account=account,
        item=item,
        current=current,
        q=q,
        materials=service.choose_materials(q),
        errors=errors,
    )


@router.get("/supplier-items/{supplier_item_id}/link")
async def link_choice_screen(request: Request, supplier_item_id: str) -> Response:
    item_id = int_or_none(supplier_item_id)
    account = admin_screen(
        request, action="link_create", object_type=SUPPLIER_ITEM, object_id=item_id
    )
    if not isinstance(account, Account):
        return account
    try:
        item = directories(request).get_supplier_item(known_id(item_id))
    except NotFound:
        return not_found_page(account)
    return link_choice(request, account, item, request.query_params.get("q", ""), [])


@router.post("/supplier-items/{supplier_item_id}/link")
async def link_item(request: Request, supplier_item_id: str) -> Response:
    item_id = int_or_none(supplier_item_id)
    account = admin_screen(
        request, action="link_create", object_type=SUPPLIER_ITEM, object_id=item_id
    )
    if not isinstance(account, Account):
        return account
    service = directories(request)
    try:
        item = service.get_supplier_item(known_id(item_id))
    except NotFound:
        return not_found_page(account)
    material_id = int_or_none((await form_data(request)).get("material_id", ""))
    if material_id is None:  # no material chosen
        exc = ValidationFailed([FieldError("material_id", "required", REQUIRED)])
        service.reject_link(actor(account), item.id, exc.code)
        return link_choice(request, account, item, "", messages(exc), 422)
    try:
        result = service.link_item(actor(account), item.id, material_id)
    except ServiceError as exc:
        return link_choice(
            request, account, item, "", messages(exc), refused_status(exc)
        )
    return redirect(f"/materials/{result.material.id}/links")


@router.post("/supplier-items/{supplier_item_id}/unlink")
async def unlink_item(request: Request, supplier_item_id: str) -> Response:
    item_id = int_or_none(supplier_item_id)
    account = admin_screen(
        request, action="link_remove", object_type=SUPPLIER_ITEM, object_id=item_id
    )
    if not isinstance(account, Account):
        return account
    try:
        material_id = directories(request).unlink_item(
            actor(account), known_id(item_id)
        )
    except NotFound:
        return not_found_page(account)
    return redirect(f"/materials/{material_id}/links")


# --- settings (REQ-F-019) ---------------------------------------------------------------------------


@router.get("/settings")
async def settings_screen(request: Request) -> Response:
    account = admin_screen(request, action="settings_read", object_type=SETTINGS)
    if not isinstance(account, Account):
        return account
    settings = settings_service(request).get()
    values = {
        "update_time": settings.update_time,
        "notification_threshold": settings.threshold_text,
    }
    return render("settings.html", account=account, values=values, errors=[])


@router.post("/settings")
async def update_settings(request: Request) -> Response:
    account = admin_screen(request, action="settings_update", object_type=SETTINGS)
    if not isinstance(account, Account):
        return account
    form = await form_data(request)
    values = {
        "update_time": form.get("update_time", "").strip(),
        "notification_threshold": form.get("notification_threshold", ""),
    }
    try:
        settings_service(request).update(
            actor(account),
            update_time=values["update_time"],
            threshold=values["notification_threshold"],
        )
    except ServiceError as exc:
        return render(
            "settings.html",
            refused_status(exc),
            account=account,
            values=values,
            errors=messages(exc),
        )
    return redirect("/settings")


# --- the run log, manual run, new volume (REQ-F-020, REQ-F-021, REQ-F-031, REQ-F-033) ---------

DASH = "—"
TRIGGER_TEXT = {
    "scheduled": "за розкладом",
    "manual": "вручну",
    "catch_up": "доганяння",
}
RUN_STATUS_TEXT = {
    "success": "успіх",
    "partial": "частково",
    "error": "помилка",
    "interrupted": "перервано",
    "in_progress": "триває",
}
SUPPLIER_STATUS_TEXT = {
    "success": "успіх",
    "partial": "частково",
    "error": "помилка",
    "not_finished": "не завершено",
}
WARNING_TEXT = {
    "unit_mismatch": "одиниця не збігається",
    "duplicate_sku": "повторний артикул",
    "unparsed_row": "рядок не розібрано",
    "non_positive_price": "нульова або від'ємна ціна",
}
ENTRY_TEXT = {
    "skipped": "пропущено: оновлення вже триває",
    "no_active_suppliers": "немає активних постачальників",
    "volume_acceptance": "прийнято новий обсяг",
}


def warning_text(warning: dict) -> str:
    if warning["sku"] is None:
        return "рядок без артикула"
    return f"{WARNING_TEXT[warning['kind']]}: {warning['sku']}"


def time_text(moment, started) -> str:
    """ГГ:ХХ:СС (REQ-NF-030); with the date when it is not the start date."""
    if moment is None:
        return DASH
    local = to_kyiv(moment)
    if local.date() != to_kyiv(started).date():
        return local.strftime("%Y-%m-%d %H:%M:%S")
    return local.strftime("%H:%M:%S")


def run_rows(run, common: dict) -> list[dict]:
    """The rows of a run: one per supplier, with its status and messages."""
    rows = []
    for s in run.supplier_run_statuses:
        count = s.parsed_items_count
        texts = [s.error_reason] if s.error_reason else []
        texts += [warning_text(w) for w in s.warnings]
        accept = (
            {"run_id": run.id, "supplier_id": s.supplier.id}
            if s.volume_acceptance_available
            else None
        )
        rows.append(
            common
            | {
                "finish": time_text(run.finished_at, run.started_at),
                "trigger": TRIGGER_TEXT[run.trigger],
                "by": run.started_by or DASH,
                "status": RUN_STATUS_TEXT[run.status],
                "supplier": s.supplier.name,
                "supplier_status": SUPPLIER_STATUS_TEXT.get(s.status, DASH),
                "count": str(count) if count is not None else DASH,
                "message": "; ".join(texts),
                "accept": accept,
            }
        )
    return rows


def log_rows(entries: list[RunLogEntry]) -> list[dict]:
    """One table row per supplier of a run, one row for any other entry."""
    rows = []
    for entry in entries:
        local = to_kyiv(entry.occurred_at)
        common = {
            "date": local.date().isoformat(),
            "start": local.strftime("%H:%M:%S"),
            "finish": DASH,
            "trigger": DASH,
            "by": DASH,
            "status": DASH,
            "supplier": DASH,
            "supplier_status": DASH,
            "count": DASH,
            "message": "",
            "accept": None,
        }
        if entry.run is not None:
            rows += run_rows(entry.run, common)
        elif entry.volume_acceptance is not None:
            accepted = entry.volume_acceptance
            rows.append(
                common
                | {
                    "by": accepted.accepted_by,
                    "status": ENTRY_TEXT["volume_acceptance"],
                    "supplier": accepted.supplier.name,
                    "count": str(accepted.volume_baseline),
                    "message": f"нова база обсягу: {accepted.volume_baseline}",
                }
            )
        else:
            trigger = TRIGGER_TEXT[entry.trigger or "scheduled"]
            rows.append(common | {"trigger": trigger, "status": ENTRY_TEXT[entry.kind]})
    return rows


def run_log_page(request, account, errors: list[str], status: int = 200):
    page = runs_service(request).list_log(page_number(request))
    return render(
        "run_log.html",
        status,
        account=account,
        page=page,
        rows=log_rows(page.items),
        errors=errors,
    )


@router.get("/run-log-entries")
async def run_log_screen(request: Request) -> Response:
    account = admin_screen(request, action="run_log_read", object_type=RUN)
    if not isinstance(account, Account):
        return account
    return run_log_page(request, account, [])


@router.post("/runs")
async def manual_run(request: Request) -> Response:
    account = admin_screen(request, action="manual_run", object_type=RUN)
    if not isinstance(account, Account):
        return account
    try:
        runs_service(request).start_manual(actor(account))
    except ServiceError as exc:  # «оновлення вже триває»
        return run_log_page(request, account, messages(exc), refused_status(exc))
    return redirect("/run-log-entries")


@router.post("/volume-acceptances")
async def accept_volume(request: Request) -> Response:
    account = admin_screen(
        request, action="volume_accept", object_type=VOLUME_ACCEPTANCE
    )
    if not isinstance(account, Account):
        return account
    form = await form_data(request)
    service = runs_service(request)
    who = actor(account)
    values = {f: int_or_none(form.get(f, "")) for f in ("run_id", "supplier_id")}
    try:
        missing = [
            FieldError(f, "required", REQUIRED) for f, v in values.items() if v is None
        ]
        if missing:
            service.reject_acceptance(who, ValidationFailed.code)
            raise ValidationFailed(missing)
        service.accept_volume(who, values["run_id"], values["supplier_id"])
    except ServiceError as exc:
        return run_log_page(request, account, messages(exc), refused_status(exc))
    return redirect("/run-log-entries")


# --- the update status of suppliers (REQ-F-034), both roles -----------------------------------


@router.get("/supplier-update-statuses")
async def supplier_update_statuses_screen(request: Request) -> Response:
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    page = runs_service(request).update_statuses(page_number(request))
    return render("supplier_update_statuses.html", account=account, page=page)


# --- comparison, history, the feed (REQ-F-035…REQ-F-042, REQ-F-058), both roles ---------------

CHEAPEST = "найдешевша"
STALE = "застаріла"
UNIT_MISMATCH = "одиниця не збігається"
AT_PERIOD_START = "чинна на початок періоду"
PERIOD_TEXT = {
    "last_7_days": "7 днів",
    "last_30_days": "30 днів",
    "all": "весь період",
}
DEFAULT_PERIOD = "all"
KIND_TEXT = {
    "price_change": "зміна ціни",
    "appeared": "з'явився",
    "disappeared": "зник",
}


def comparison_marks(row) -> list[str]:
    marks = []
    if row.cheapest:
        marks.append(CHEAPEST)
    if row.stale:
        marks.append(STALE)
    if row.daily_price is not None and row.daily_price.unit_mismatch:
        marks.append(UNIT_MISMATCH)
    return marks


def history_marks(row) -> list[str]:
    marks = []
    if row.unit_mismatch:
        marks.append(UNIT_MISMATCH)
    if row.effective_at_period_start:
        marks.append(AT_PERIOD_START)
    return marks


def given_filters(values: dict) -> dict:
    """The filters of a list that have a value."""
    return {k: v for k, v in values.items() if v not in (None, "")}


def query_suffix(values: dict) -> str:
    """The filters of a list for the page links: "&name=value…"."""
    kept = given_filters(values)
    return "&" + urlencode(kept) if kept else ""


def with_filters(path: str, values: dict) -> str:
    """A link that keeps the filters of a list: "path?name=value…"."""
    kept = given_filters(values)
    return path + "?" + urlencode(kept) if kept else path


@router.get("/material-comparisons")
async def comparison_list_screen(request: Request) -> Response:
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    q = request.query_params.get("q", "")
    page = views_service(request).comparison_list(page_number(request), q)
    return render(
        "material_comparisons.html",
        account=account,
        page=page,
        q=q,
        query=query_suffix({"q": q}),
        export_url=with_filters(COMPARISON_EXPORT_PATH, {"q": q}),
    )


@router.get(COMPARISON_EXPORT_PATH)
async def comparison_list_csv(request: Request) -> Response:
    """REQ-F-072, UC-02 1в: the link «Завантажити CSV» of the comparison list."""
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    q = request.query_params.get("q", "")
    csv_file = views_service(request).export_comparison_list(q)
    return Response(
        csv_file.content,
        media_type=csv_file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{csv_file.name}"'},
    )


@router.get("/material-comparisons/{material_id}")
async def material_comparison_screen(request: Request, material_id: str) -> Response:
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    mid = int_or_none(material_id)
    try:
        found = views_service(request).material_comparison(known_id(mid))
    except NotFound:
        return not_found_page(account)
    return render(
        "material_comparison.html",
        account=account,
        comparison=found,
        marks=comparison_marks,
    )


@router.get("/price-history")
async def price_history_screen(request: Request) -> Response:
    """Without a material the screen offers the choice; an unknown period is
    the whole period."""
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    service = views_service(request)
    query = request.query_params
    period = query.get("period", "")
    if period not in PERIODS:
        period = DEFAULT_PERIOD
    show_inactive = bool(query.get("show_inactive"))
    history = None
    mid = int_or_none(query.get("material_id", ""))
    if mid is not None:
        try:
            history = service.price_history(mid, period)
        except NotFound:
            return not_found_page(account)
        # The chosen deactivated material stays visible in the choice.
        show_inactive = show_inactive or not history.material.active
    return render(
        "price_history.html",
        account=account,
        history=history,
        materials=service.history_materials(show_inactive),
        period=period,
        periods=list(PERIOD_TEXT.items()),
        show_inactive=show_inactive,
        marks=history_marks,
    )


@router.get("/events")
async def events_screen(request: Request) -> Response:
    """Filters with a value that is not an id or a kind are not applied."""
    account = user_screen(request)
    if not isinstance(account, Account):
        return account
    service = views_service(request)
    query = request.query_params
    kind = query.get("kind", "")
    filters = {
        "material_id": int_or_none(query.get("material_id", "")),
        "supplier_id": int_or_none(query.get("supplier_id", "")),
        "kind": kind if kind in EVENT_KINDS else None,
    }
    page = service.events(page_number(request), **filters)
    materials, suppliers = service.feed_choices()
    return render(
        "events.html",
        account=account,
        page=page,
        filters=filters,
        materials=materials,
        suppliers=suppliers,
        kinds=list(KIND_TEXT.items()),
        kind_text=KIND_TEXT,
        query=query_suffix(filters),
    )


# --- items that need attention (REQ-F-017, REQ-F-066, REQ-F-068), administrator -------------


@router.get("/attention-items")
async def attention_items_screen(request: Request) -> Response:
    account = admin_screen(
        request, action="attention_items_read", object_type=SUPPLIER_ITEM
    )
    if not isinstance(account, Account):
        return account
    page = views_service(request).attention_items(page_number(request))
    return render("attention_items.html", account=account, page=page)

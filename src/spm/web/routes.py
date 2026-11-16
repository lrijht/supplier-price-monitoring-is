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
from spm.auth.service import SESSION_LIFETIME
from spm.services import (
    Actor,
    Conflict,
    Directories,
    NotFound,
    SettingsService,
    ValidationFailed,
)
from spm.services.errors import REQUIRED, FieldError, ServiceError

TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
WRONG_CREDENTIALS = "Неправильний логін або пароль."

router = APIRouter()


# --- helpers ----------------------------------------------------------------------------------


def render(name: str, status: int = 200, **context) -> HTMLResponse:
    return HTMLResponse(TEMPLATES.get_template(name).render(**context), status)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def auth(request: Request) -> AuthService:
    return request.app.state.auth


def directories(request: Request) -> Directories:
    return request.app.state.directories


def settings_service(request: Request) -> SettingsService:
    return request.app.state.settings


def session_account(request: Request) -> Account | None:
    return auth(request).resolve(request.cookies.get(SESSION_COOKIE))


def actor(account: Account) -> Actor:
    return Actor(account.login, account.role)


def int_or_none(value: str) -> int | None:
    return int(value) if value.isascii() and value.isdigit() else None


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
}


def label(field: str | None) -> str:
    return FIELD_LABELS.get(field or "", "Запит")


def refused_status(exc: ServiceError) -> int:
    return 409 if isinstance(exc, Conflict) else 422


def not_found_page(account: Account | None) -> HTMLResponse:
    return render("not_found.html", 404, account=account)


def admin_screen(
    request: Request,
    *,
    action: str,
    object_type: str | None,
    object_id: int | None = None,
) -> Account | Response:
    """The administrator's account, or the answer: the login form without a
    session, «немає доступу» for the manager (REQ-F-001, REQ-F-005)."""
    account = session_account(request)
    if account is None:
        return redirect("/login")
    if not account.is_admin:
        auth(request).deny(
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
    account = session_account(request)
    if account is None:
        return redirect("/login")
    return not_found_page(account)


async def method_not_allowed(request: Request) -> Response:
    return render("not_found.html", 405, account=None)


# --- login, logout (REQ-F-001, REQ-F-002) --------------------------------------------------------


@router.get("/login")
async def login_form(request: Request) -> Response:
    return render("login.html", account=None, errors=[], login="")


@router.post("/login")
async def login(request: Request) -> Response:
    form = await form_data(request)
    entered = form.get("login", "")
    opened = auth(request).login(entered, form.get("password", ""))
    if opened is None:
        return render(
            "login.html", 401, account=None, errors=[WRONG_CREDENTIALS], login=entered
        )
    _, cookie = opened
    response = redirect("/")
    # SameSite=Lax, no Secure: no HTTPS in the trusted local network (ЗП-4).
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    auth(request).logout(request.cookies.get(SESSION_COOKIE))
    response = redirect("/login")
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return response


@router.get("/")
async def home(request: Request) -> Response:
    account = session_account(request)
    if account is None:
        return redirect("/login")
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
    account = admin_screen(request, action="supplier_list", object_type="supplier")
    if not isinstance(account, Account):
        return account
    page = directories(request).list_suppliers(page_number(request))
    return render("suppliers.html", account=account, page=page)


@router.get("/suppliers/new")
async def new_supplier_screen(request: Request) -> Response:
    account = admin_screen(request, action="supplier_create", object_type="supplier")
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
    account = admin_screen(request, action="supplier_create", object_type="supplier")
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
        request, action="supplier_read", object_type="supplier", object_id=sid
    )
    if not isinstance(account, Account):
        return account
    try:
        supplier = directories(request).get_supplier(sid if sid is not None else 0)
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
        request, action="supplier_update", object_type="supplier", object_id=sid
    )
    if not isinstance(account, Account):
        return account
    values = supplier_values(await form_data(request))
    service = directories(request)
    try:
        current = service.get_supplier(sid if sid is not None else 0)
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


@router.get("/materials")
async def materials_screen(request: Request) -> Response:
    account = admin_screen(request, action="material_list", object_type="material")
    if not isinstance(account, Account):
        return account
    page = directories(request).list_materials(page_number(request))
    return render("materials.html", account=account, page=page)


@router.get("/materials/new")
async def new_material_screen(request: Request) -> Response:
    account = admin_screen(request, action="material_create", object_type="material")
    if not isinstance(account, Account):
        return account
    return render(
        "material_form.html",
        account=account,
        heading="Новий матеріал",
        action="/materials",
        values={"name": "", "unit": "", "active": True},
        errors=[],
    )


@router.post("/materials")
async def create_material(request: Request) -> Response:
    account = admin_screen(request, action="material_create", object_type="material")
    if not isinstance(account, Account):
        return account
    values = material_values(await form_data(request))
    try:
        directories(request).create_material(actor(account), **values)
    except ServiceError as exc:
        return render(
            "material_form.html",
            refused_status(exc),
            account=account,
            heading="Новий матеріал",
            action="/materials",
            values=values,
            errors=messages(exc),
        )
    return redirect("/materials")


@router.get("/materials/{material_id}")
async def material_screen(request: Request, material_id: str) -> Response:
    mid = int_or_none(material_id)
    account = admin_screen(
        request, action="material_read", object_type="material", object_id=mid
    )
    if not isinstance(account, Account):
        return account
    try:
        material = directories(request).get_material(mid if mid is not None else 0)
    except NotFound:
        return not_found_page(account)
    return render(
        "material_form.html",
        account=account,
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
        request, action="material_update", object_type="material", object_id=mid
    )
    if not isinstance(account, Account):
        return account
    values = material_values(await form_data(request))
    service = directories(request)
    try:
        current = service.get_material(mid if mid is not None else 0)
        service.update_material(actor(account), current.id, values)
    except NotFound:
        return not_found_page(account)
    except ServiceError as exc:
        return render(
            "material_form.html",
            refused_status(exc),
            account=account,
            heading=f"Матеріал «{current.name}»",
            action=f"/materials/{current.id}",
            values=values,
            errors=messages(exc),
        )
    return redirect("/materials")


@router.get("/materials/{material_id}/links")
async def material_links_screen(request: Request, material_id: str) -> Response:
    mid = int_or_none(material_id)
    account = admin_screen(
        request, action="material_links_read", object_type="material", object_id=mid
    )
    if not isinstance(account, Account):
        return account
    try:
        material, page = directories(request).list_material_links(
            mid if mid is not None else 0, page_number(request)
        )
    except NotFound:
        return not_found_page(account)
    return render("material_links.html", account=account, material=material, page=page)


# --- unlinked items and links (REQ-F-012…REQ-F-015, REQ-F-048, REQ-F-050, REQ-F-069) ----------------


@router.get("/unlinked-items")
async def unlinked_items_screen(request: Request) -> Response:
    account = admin_screen(
        request, action="unlinked_items_read", object_type="supplier_item"
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
        request, action="link_create", object_type="supplier_item", object_id=item_id
    )
    if not isinstance(account, Account):
        return account
    try:
        item = directories(request).get_supplier_item(
            item_id if item_id is not None else 0
        )
    except NotFound:
        return not_found_page(account)
    return link_choice(request, account, item, request.query_params.get("q", ""), [])


@router.post("/supplier-items/{supplier_item_id}/link")
async def link_item(request: Request, supplier_item_id: str) -> Response:
    item_id = int_or_none(supplier_item_id)
    account = admin_screen(
        request, action="link_create", object_type="supplier_item", object_id=item_id
    )
    if not isinstance(account, Account):
        return account
    service = directories(request)
    try:
        item = service.get_supplier_item(item_id if item_id is not None else 0)
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
        request, action="link_remove", object_type="supplier_item", object_id=item_id
    )
    if not isinstance(account, Account):
        return account
    try:
        material_id = directories(request).unlink_item(
            actor(account), item_id if item_id is not None else 0
        )
    except NotFound:
        return not_found_page(account)
    return redirect(f"/materials/{material_id}/links")


# --- settings (REQ-F-019) ---------------------------------------------------------------------------


@router.get("/settings")
async def settings_screen(request: Request) -> Response:
    account = admin_screen(request, action="settings_read", object_type="settings")
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
    account = admin_screen(request, action="settings_update", object_type="settings")
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

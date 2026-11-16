"""Operations 1–14, 16, 17, 23, 24 of ``spec/openapi.yaml``.

Thin: each operation checks the request in the contract's order and calls the
same functions of ``auth`` and ``services`` as the web interface (REQ-NF-031).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from spm.api.errors import API_PREFIX, ProblemError
from spm.api.requests import (
    BOOL,
    INT,
    NUMBER,
    STR,
    auth_service,
    authenticate,
    check_fields,
    json_object,
    list_query,
    path_id,
    require_admin,
    require_json,
)
from spm.auth import SESSION_COOKIE, Account
from spm.auth.service import SESSION_LIFETIME
from spm.services import (
    Actor,
    Directories,
    Material,
    Page,
    Settings,
    SettingsService,
    Supplier,
    SupplierItem,
)
from spm.services.errors import ServiceError

router = APIRouter(prefix=API_PREFIX)

SUPPLIER_INPUT = {"name": STR, "catalog_url": STR, "parser": STR, "active": BOOL}
SUPPLIER_READ_ONLY = ("id", "last_update_date")
MATERIAL_INPUT = {"name": STR, "unit": STR, "active": BOOL}
MATERIAL_READ_ONLY = ("id", "linked_items_count")
SETTINGS_INPUT = {"update_time": STR, "notification_threshold": NUMBER}


def directories(request: Request) -> Directories:
    return request.app.state.directories


def settings_service(request: Request) -> SettingsService:
    return request.app.state.settings


def actor(account: Account) -> Actor:
    return Actor(account.login, account.role)


def json(content: Any, status: int = 200, location: str | None = None) -> JSONResponse:
    headers = {"Location": location} if location else None
    return JSONResponse(content, status_code=status, headers=headers)


# --- representations ---------------------------------------------------------------------


def account_json(account: Account) -> dict:
    return {"account": {"login": account.login, "role": account.role}}


def supplier_json(supplier: Supplier, *, full: bool = True) -> dict:
    if not full:  # SupplierForManager (REQ-F-070)
        return {"id": supplier.id, "name": supplier.name, "active": supplier.active}
    return {
        "id": supplier.id,
        "name": supplier.name,
        "catalog_url": supplier.catalog_url,
        "parser": supplier.parser,
        "active": supplier.active,
        "last_update_date": (
            supplier.last_update_date.isoformat() if supplier.last_update_date else None
        ),
    }


def material_json(material: Material, *, full: bool = True) -> dict:
    if not full:  # MaterialForManager (REQ-F-070)
        return {"id": material.id, "name": material.name, "active": material.active}
    return {
        "id": material.id,
        "name": material.name,
        "unit": material.unit,
        "active": material.active,
        "linked_items_count": material.linked_items_count,
    }


def link_json(item: SupplierItem, material: Material) -> dict:
    return {
        "supplier_item": {
            "id": item.id,
            "supplier": {"id": item.supplier.id, "name": item.supplier.name},
            "sku": item.sku,
            "name": item.name,
            "unit": item.unit,
        },
        "material": {"id": material.id, "name": material.name},
    }


def unlinked_json(item: SupplierItem) -> dict:
    return {
        "supplier_item": {
            "id": item.id,
            "supplier": {
                "id": item.supplier.id,
                "name": item.supplier.name,
                "active": item.supplier.active,
            },
            "sku": item.sku,
            "name": item.name,
            "unit": item.unit,
            "last_seen_date": item.last_seen_date.isoformat(),
        }
    }


def page_json(page: Page, items: list) -> dict:
    return {
        "items": items,
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
    }


def settings_json(settings: Settings) -> dict:
    return {
        "update_time": settings.update_time,
        "notification_threshold": settings.threshold,
    }


def service_call(call, *args, **kwargs):
    """Run a service function; its refusal becomes the problem answer."""
    try:
        return call(*args, **kwargs)
    except ServiceError as exc:
        raise ProblemError.from_service(exc) from None


# --- 1–3 sessions -----------------------------------------------------------------------------


@router.post("/sessions")
async def create_session(request: Request) -> Response:
    require_json(request)
    body = await json_object(request)
    fields = check_fields(
        body,
        {"login": STR, "password": STR},
        required=("login", "password"),
        non_empty=("login", "password"),
    )
    opened = auth_service(request).login(fields["login"], fields["password"])
    if opened is None:
        raise ProblemError(401, "invalid_credentials", "Неправильний логін або пароль.")
    account, cookie = opened
    response = json(account_json(account), 201, f"{API_PREFIX}/sessions/current")
    set_session_cookie(response, cookie)
    return response


def set_session_cookie(response: Response, cookie: str) -> None:
    # SameSite=Lax, no Secure: no HTTPS in the trusted local network (ЗП-4).
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.get("/sessions/current")
async def get_current_session(request: Request) -> Response:
    return json(account_json(authenticate(request)))


@router.delete("/sessions/current")
async def delete_current_session(request: Request) -> Response:
    authenticate(request)
    auth_service(request).logout(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return response


# --- 4–8 suppliers and parsers ---------------------------------------------------------------


@router.get("/suppliers")
async def list_suppliers(request: Request) -> Response:
    account = authenticate(request)
    page, active = list_query(request, active=True)
    result = directories(request).list_suppliers(page, active)
    items = [supplier_json(s, full=account.is_admin) for s in result.items]
    return json(page_json(result, items))


@router.post("/suppliers")
async def create_supplier(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="supplier_create", object_type="supplier")
    service = directories(request)
    who = actor(account)
    fields = await _body(
        request,
        SUPPLIER_INPUT,
        SUPPLIER_READ_ONLY,
        on_reject=lambda code: service.record_rejected(
            who, "supplier_create", "supplier", None, code
        ),
    )
    supplier = service_call(
        service.create_supplier,
        who,
        name=fields.get("name"),
        catalog_url=fields.get("catalog_url"),
        parser=fields.get("parser"),
        active=fields.get("active"),
    )
    return json(supplier_json(supplier), 201, f"{API_PREFIX}/suppliers/{supplier.id}")


@router.get("/suppliers/{supplier_id}")
async def get_supplier(request: Request, supplier_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="supplier_read",
        object_type="supplier",
        object_id=supplier_id,
    )
    sid = path_id(supplier_id, "supplier_id")
    return json(supplier_json(service_call(directories(request).get_supplier, sid)))


@router.patch("/suppliers/{supplier_id}")
async def update_supplier(request: Request, supplier_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="supplier_update",
        object_type="supplier",
        object_id=supplier_id,
    )
    sid = path_id(supplier_id, "supplier_id")
    service = directories(request)
    service_call(service.get_supplier, sid)
    who = actor(account)
    fields = await _body(
        request,
        SUPPLIER_INPUT,
        SUPPLIER_READ_ONLY,
        on_reject=lambda code: service.record_rejected(
            who, "supplier_update", "supplier", sid, code
        ),
    )
    supplier = service_call(service.update_supplier, who, sid, fields)
    return json(supplier_json(supplier))


@router.get("/parsers")
async def list_parsers(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="parser_list", object_type="parser")
    return json({"items": directories(request).parsers()})


# --- 9–13 materials ---------------------------------------------------------------------------


@router.get("/materials")
async def list_materials(request: Request) -> Response:
    account = authenticate(request)
    page, active = list_query(request, active=True)
    q = request.query_params.get("q")
    result = directories(request).list_materials(page, active, q)
    items = [material_json(m, full=account.is_admin) for m in result.items]
    return json(page_json(result, items))


@router.post("/materials")
async def create_material(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="material_create", object_type="material")
    service = directories(request)
    who = actor(account)
    fields = await _body(
        request,
        MATERIAL_INPUT,
        MATERIAL_READ_ONLY,
        on_reject=lambda code: service.record_rejected(
            who, "material_create", "material", None, code
        ),
    )
    material = service_call(
        service.create_material,
        who,
        name=fields.get("name"),
        unit=fields.get("unit"),
        active=fields.get("active"),
    )
    return json(material_json(material), 201, f"{API_PREFIX}/materials/{material.id}")


@router.get("/materials/{material_id}")
async def get_material(request: Request, material_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="material_read",
        object_type="material",
        object_id=material_id,
    )
    mid = path_id(material_id, "material_id")
    return json(material_json(service_call(directories(request).get_material, mid)))


@router.patch("/materials/{material_id}")
async def update_material(request: Request, material_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="material_update",
        object_type="material",
        object_id=material_id,
    )
    mid = path_id(material_id, "material_id")
    service = directories(request)
    service_call(service.get_material, mid)
    who = actor(account)
    fields = await _body(
        request,
        MATERIAL_INPUT,
        MATERIAL_READ_ONLY,
        on_reject=lambda code: service.record_rejected(
            who, "material_update", "material", mid, code
        ),
    )
    material = service_call(service.update_material, who, mid, fields)
    return json(material_json(material))


@router.get("/materials/{material_id}/links")
async def list_material_links(request: Request, material_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="material_links_read",
        object_type="material",
        object_id=material_id,
    )
    mid = path_id(material_id, "material_id")
    page, _ = list_query(request)
    material, result = service_call(directories(request).list_material_links, mid, page)
    items = [link_json(item, material) for item in result.items]
    return json(page_json(result, items))


# --- 14, 16, 17 supplier items and links ---------------------------------------------------------


@router.get("/unlinked-items")
async def list_unlinked_items(request: Request) -> Response:
    account = authenticate(request)
    require_admin(
        request, account, action="unlinked_items_read", object_type="supplier_item"
    )
    page, _ = list_query(request)
    q = request.query_params.get("q")
    result = directories(request).list_unlinked_items(page, q)
    return json(page_json(result, [unlinked_json(i) for i in result.items]))


@router.put("/supplier-items/{supplier_item_id}/link")
async def put_supplier_item_link(request: Request, supplier_item_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="link_create",
        object_type="supplier_item",
        object_id=supplier_item_id,
    )
    item_id = path_id(supplier_item_id, "supplier_item_id")
    service = directories(request)
    service_call(service.get_supplier_item, item_id)
    who = actor(account)
    fields = await _body(
        request,
        {"material_id": INT},
        (),
        required=("material_id",),
        on_reject=lambda code: service.reject_link(who, item_id, code),
    )
    result = service_call(service.link_item, who, item_id, fields["material_id"])
    body = link_json(result.item, result.material)
    if result.created:
        location = f"{API_PREFIX}/supplier-items/{item_id}/link"
        return json(body, 201, location)
    return json(body)


@router.delete("/supplier-items/{supplier_item_id}/link")
async def delete_supplier_item_link(
    request: Request, supplier_item_id: str
) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="link_remove",
        object_type="supplier_item",
        object_id=supplier_item_id,
    )
    item_id = path_id(supplier_item_id, "supplier_item_id")
    service_call(directories(request).unlink_item, actor(account), item_id)
    return Response(status_code=204)


# --- 23, 24 settings ----------------------------------------------------------------------------


@router.get("/settings")
async def get_settings(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="settings_read", object_type="settings")
    return json(settings_json(settings_service(request).get()))


@router.patch("/settings")
async def update_settings(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="settings_update", object_type="settings")
    service = settings_service(request)
    who = actor(account)
    fields = await _body(
        request, SETTINGS_INPUT, (), on_reject=lambda code: service.reject(who, code)
    )
    threshold = fields.get("notification_threshold")
    settings = service_call(
        service.update,
        who,
        update_time=fields.get("update_time"),
        # str() of a JSON number keeps its decimal text: 0.3 → "0.3".
        threshold=Decimal(str(threshold)) if threshold is not None else None,
    )
    return json(settings_json(settings))


# --- body of state-changing operations -------------------------------------------------------------


async def _body(
    request: Request,
    fields: dict[str, str],
    read_only: tuple[str, ...],
    *,
    on_reject,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The checked body; a refused body is recorded as a rejected action.

    415 is not an action on the object, so it is not recorded.
    """
    require_json(request)
    try:
        body = await json_object(request)
        return check_fields(body, fields, read_only=read_only, required=required)
    except ProblemError as exc:
        on_reject(exc.code)
        raise

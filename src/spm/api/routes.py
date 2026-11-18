"""Operations 1–29 of ``spec/openapi.yaml``.

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
    KIND_INVALID,
    NUMBER,
    PERIOD_INVALID,
    STR,
    auth_service,
    authenticate,
    check_fields,
    json_object,
    list_query,
    path_id,
    query_errors,
    require_admin,
    require_json,
)
from spm.auth import SESSION_COOKIE, Account
from spm.auth.service import (
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_SCOPE,
    WRONG_CREDENTIALS,
)
from spm.clock import to_kyiv
from spm.services import (
    EVENT_KINDS,
    MATERIAL,
    PARSER,
    PERIODS,
    RUN,
    SETTINGS,
    SUPPLIER,
    SUPPLIER_ITEM,
    VOLUME_ACCEPTANCE,
    Actor,
    AttentionItem,
    ComparisonListRow,
    ComparisonRow,
    Directories,
    Event,
    Material,
    Page,
    PriceHistory,
    Run,
    RunLogEntry,
    Runs,
    Settings,
    SettingsService,
    Supplier,
    SupplierItem,
    SupplierUpdateStatus,
    Views,
    VolumeAcceptance,
)
from spm.services.errors import REQUIRED, FieldError, ServiceError

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


def runs_service(request: Request) -> Runs:
    return request.app.state.runs


def views_service(request: Request) -> Views:
    return request.app.state.views


def actor(account: Account) -> Actor:
    return Actor(account.login, account.role)


def json(content: Any, status: int = 200, location: str | None = None) -> JSONResponse:
    headers = {"Location": location} if location else None
    return JSONResponse(content, status_code=status, headers=headers)


# --- representations ---------------------------------------------------------------------


def date_json(value) -> str | None:
    return value.isoformat() if value is not None else None


def moment_json(value) -> str | None:
    """ISO 8601 with the Kyiv offset, to the second (REQ-NF-031)."""
    return to_kyiv(value).isoformat(timespec="seconds") if value is not None else None


def money_json(value) -> str | None:
    """A sum with two decimals, as the contract's Price and Amount."""
    return f"{value:.2f}" if value is not None else None


def percent_json(value) -> float | None:
    return float(value) if value is not None else None


def ref_json(ref) -> dict:
    return {"id": ref.id, "name": ref.name}


def active_ref_json(ref) -> dict:
    """A reference with its activity; for the manager it is the whole supplier
    or material (SupplierForManager, MaterialForManager, REQ-F-070)."""
    return {"id": ref.id, "name": ref.name, "active": ref.active}


def supplier_item_json(item_id: int, supplier: dict, sku, name, unit) -> dict:
    return {"id": item_id, "supplier": supplier, "sku": sku, "name": name, "unit": unit}


def account_json(account: Account) -> dict:
    return {"account": {"login": account.login, "role": account.role}}


def supplier_json(supplier: Supplier, *, full: bool = True) -> dict:
    if not full:
        return active_ref_json(supplier)
    return {
        "id": supplier.id,
        "name": supplier.name,
        "catalog_url": supplier.catalog_url,
        "parser": supplier.parser,
        "active": supplier.active,
        "last_update_date": date_json(supplier.last_update_date),
    }


def material_json(material: Material, *, full: bool = True) -> dict:
    if not full:
        return active_ref_json(material)
    return {
        "id": material.id,
        "name": material.name,
        "unit": material.unit,
        "active": material.active,
        "linked_items_count": material.linked_items_count,
    }


def link_json(item: SupplierItem, material: Material) -> dict:
    return {
        "supplier_item": supplier_item_json(
            item.id, ref_json(item.supplier), item.sku, item.name, item.unit
        ),
        "material": ref_json(material),
    }


def unlinked_json(item: SupplierItem) -> dict:
    return {
        "supplier_item": supplier_item_json(
            item.id, active_ref_json(item.supplier), item.sku, item.name, item.unit
        )
        | {"last_seen_date": date_json(item.last_seen_date)}
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


def run_json(run: Run) -> dict:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "started_at": moment_json(run.started_at),
        "finished_at": moment_json(run.finished_at),
        "started_by": run.started_by,
        "status": run.status,
        "supplier_run_statuses": [
            {
                "supplier": ref_json(s.supplier),
                "status": s.status,
                "parsed_items_count": s.parsed_items_count,
                "reason_code": s.reason_code,
                "error_reason": s.error_reason,
                "warnings": [{"kind": w["kind"], "sku": w["sku"]} for w in s.warnings],
                "volume_acceptance_available": s.volume_acceptance_available,
            }
            for s in run.supplier_run_statuses
        ],
    }


def acceptance_json(acceptance: VolumeAcceptance) -> dict:
    return {
        "id": acceptance.id,
        "run_id": acceptance.run_id,
        "supplier": ref_json(acceptance.supplier),
        "accepted_by": acceptance.accepted_by,
        "accepted_at": moment_json(acceptance.accepted_at),
        "volume_baseline": acceptance.volume_baseline,
    }


def log_entry_json(entry: RunLogEntry) -> dict:
    return {
        "kind": entry.kind,
        "occurred_at": moment_json(entry.occurred_at),
        "trigger": entry.trigger,
        "run": run_json(entry.run) if entry.run is not None else None,
        "volume_acceptance": (
            acceptance_json(entry.volume_acceptance)
            if entry.volume_acceptance is not None
            else None
        ),
    }


def update_status_json(row: SupplierUpdateStatus) -> dict:
    return {
        "supplier": ref_json(row.supplier),
        "last_update_date": date_json(row.last_update_date),
    }


def attention_json(item: AttentionItem) -> dict:
    return {
        "supplier_item": supplier_item_json(
            item.item_id,
            ref_json(item.supplier) | {"active": item.supplier_active},
            item.sku,
            item.name,
            item.unit,
        ),
        "material": {
            "id": item.material.id,
            "name": item.material.name,
            "unit": item.material_unit,
        },
        "last_unit_mismatch_date": item.last_unit_mismatch_date.isoformat(),
    }


def comparison_list_json(row: ComparisonListRow) -> dict:
    return {
        "material": ref_json(row.material),
        "cheapest_supplier": (
            ref_json(row.cheapest_supplier) if row.cheapest_supplier else None
        ),
        "price": money_json(row.price),
    }


def comparison_row_json(row: ComparisonRow) -> dict:
    price = row.daily_price
    return {
        "supplier": ref_json(row.supplier),
        "daily_price": (
            {
                "price": money_json(price.price),
                "date": price.date.isoformat(),
                "unit_mismatch": price.unit_mismatch,
            }
            if price is not None
            else None
        ),
        "stale": row.stale,
        "cheapest": row.cheapest,
        "difference_from_cheapest": (
            {
                "percent": percent_json(row.difference.percent),
                "amount": money_json(row.difference.amount),
            }
            if row.difference is not None
            else None
        ),
    }


def history_json(history: PriceHistory) -> dict:
    return {
        "material": active_ref_json(history.material),
        "period": history.period,
        "items": [
            {
                "date": r.date.isoformat(),
                "supplier": ref_json(r.supplier),
                "price": money_json(r.price),
                "unit_mismatch": r.unit_mismatch,
                "effective_at_period_start": r.effective_at_period_start,
            }
            for r in history.items
        ],
    }


def event_json(event: Event) -> dict:
    return {
        "id": event.id,
        "kind": event.kind,
        "date": event.date.isoformat(),
        "created_at": moment_json(event.created_at),
        "material": ref_json(event.material),
        "supplier": ref_json(event.supplier),
        "old_price": money_json(event.old_price),
        "new_price": money_json(event.new_price),
        "change_percent": percent_json(event.change_percent),
        "price": money_json(event.price),
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
        raise ProblemError(401, "invalid_credentials", WRONG_CREDENTIALS)
    account, cookie = opened
    response = json(account_json(account), 201, f"{API_PREFIX}/sessions/current")
    set_session_cookie(response, cookie)
    return response


def set_session_cookie(response: Response, cookie: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, cookie, max_age=SESSION_COOKIE_MAX_AGE, **SESSION_COOKIE_SCOPE
    )


@router.get("/sessions/current")
async def get_current_session(request: Request) -> Response:
    return json(account_json(authenticate(request)))


@router.delete("/sessions/current")
async def delete_current_session(request: Request) -> Response:
    authenticate(request)
    auth_service(request).logout(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, **SESSION_COOKIE_SCOPE)
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
    require_admin(request, account, action="supplier_create", object_type=SUPPLIER)
    service = directories(request)
    who = actor(account)
    fields = await _body(
        request,
        SUPPLIER_INPUT,
        SUPPLIER_READ_ONLY,
        on_reject=lambda code: service.record_rejected(
            who, "supplier_create", SUPPLIER, None, code
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
        object_type=SUPPLIER,
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
        object_type=SUPPLIER,
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
            who, "supplier_update", SUPPLIER, sid, code
        ),
    )
    supplier = service_call(service.update_supplier, who, sid, fields)
    return json(supplier_json(supplier))


@router.get("/parsers")
async def list_parsers(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="parser_list", object_type=PARSER)
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
    require_admin(request, account, action="material_create", object_type=MATERIAL)
    service = directories(request)
    who = actor(account)
    fields = await _body(
        request,
        MATERIAL_INPUT,
        MATERIAL_READ_ONLY,
        on_reject=lambda code: service.record_rejected(
            who, "material_create", MATERIAL, None, code
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
        object_type=MATERIAL,
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
        object_type=MATERIAL,
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
            who, "material_update", MATERIAL, mid, code
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
        object_type=MATERIAL,
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
        request, account, action="unlinked_items_read", object_type=SUPPLIER_ITEM
    )
    page, _ = list_query(request)
    q = request.query_params.get("q")
    result = directories(request).list_unlinked_items(page, q)
    return json(page_json(result, [unlinked_json(i) for i in result.items]))


@router.get("/attention-items")
async def list_attention_items(request: Request) -> Response:
    account = authenticate(request)
    require_admin(
        request, account, action="attention_items_read", object_type=SUPPLIER_ITEM
    )
    page, _ = list_query(request)
    result = views_service(request).attention_items(page)
    return json(page_json(result, [attention_json(i) for i in result.items]))


@router.put("/supplier-items/{supplier_item_id}/link")
async def put_supplier_item_link(request: Request, supplier_item_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request,
        account,
        action="link_create",
        object_type=SUPPLIER_ITEM,
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
        object_type=SUPPLIER_ITEM,
        object_id=supplier_item_id,
    )
    item_id = path_id(supplier_item_id, "supplier_item_id")
    service_call(directories(request).unlink_item, actor(account), item_id)
    return Response(status_code=204)


# --- 18–21, 29 comparison and its export, history, the feed --------------------------------------


@router.get("/material-comparisons")
async def list_material_comparisons(request: Request) -> Response:
    authenticate(request)
    page, _ = list_query(request)
    q = request.query_params.get("q")
    result = views_service(request).comparison_list(page, q)
    return json(page_json(result, [comparison_list_json(r) for r in result.items]))


@router.get("/exports/material-comparisons")
async def export_material_comparisons(request: Request) -> Response:
    """Operation 29: the comparison list as a CSV file (REQ-F-072)."""
    authenticate(request)
    q = request.query_params.get("q")
    csv_file = views_service(request).export_comparison_list(q)
    return Response(
        csv_file.content,
        media_type=csv_file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{csv_file.name}"'},
    )


@router.get("/material-comparisons/{material_id}")
async def get_material_comparison(request: Request, material_id: str) -> Response:
    authenticate(request)
    mid = path_id(material_id, "material_id")
    found = service_call(views_service(request).material_comparison, mid)
    return json(
        {
            "material": active_ref_json(found.material),
            "items": [comparison_row_json(r) for r in found.items],
        }
    )


@router.get("/materials/{material_id}/price-history")
async def get_material_price_history(request: Request, material_id: str) -> Response:
    authenticate(request)
    errors: list[FieldError] = []
    try:
        mid = path_id(material_id, "material_id")
    except ProblemError as exc:
        errors += exc.errors
    period = request.query_params.get("period")
    if period is None:
        errors.append(FieldError("period", "required", REQUIRED))
    elif period not in PERIODS:
        errors.append(FieldError("period", "period_invalid", PERIOD_INVALID))
    if errors:
        raise ProblemError.validation(errors)
    history = service_call(views_service(request).price_history, mid, period)
    return json(history_json(history))


@router.get("/events")
async def list_events(request: Request) -> Response:
    authenticate(request)
    query = request.query_params
    page, _, errors = query_errors(query)
    filters: dict[str, Any] = {}
    for name in ("material_id", "supplier_id"):
        value = query.get(name)
        if value is None:
            continue
        try:
            filters[name] = path_id(value, name)
        except ProblemError as exc:
            errors += exc.errors
    kind = query.get("kind")
    if kind is not None:
        if kind in EVENT_KINDS:
            filters["kind"] = kind
        else:
            errors.append(FieldError("kind", "kind_invalid", KIND_INVALID))
    if errors:
        raise ProblemError.validation(errors)
    result = views_service(request).events(page, **filters)
    return json(page_json(result, [event_json(e) for e in result.items]))


# --- 23, 24 settings ----------------------------------------------------------------------------


@router.get("/settings")
async def get_settings(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="settings_read", object_type=SETTINGS)
    return json(settings_json(settings_service(request).get()))


@router.patch("/settings")
async def update_settings(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="settings_update", object_type=SETTINGS)
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


# --- 22, 25–28 updates ------------------------------------------------------------------------------


@router.get("/supplier-update-statuses")
async def list_supplier_update_statuses(request: Request) -> Response:
    authenticate(request)
    page, _ = list_query(request)
    result = runs_service(request).update_statuses(page)
    return json(page_json(result, [update_status_json(r) for r in result.items]))


@router.post("/runs")
async def create_run(request: Request) -> Response:
    """No body and no Content-Type (contract, operation 25)."""
    account = authenticate(request)
    require_admin(request, account, action="manual_run", object_type=RUN)
    result = service_call(runs_service(request).start_manual, actor(account))
    if isinstance(result, Run):
        return json(run_json(result), 202, f"{API_PREFIX}/runs/{result.id}")
    return json(log_entry_json(result))


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> Response:
    account = authenticate(request)
    require_admin(
        request, account, action="run_read", object_type=RUN, object_id=run_id
    )
    rid = path_id(run_id, "run_id")
    return json(run_json(service_call(runs_service(request).get_run, rid)))


@router.get("/run-log-entries")
async def list_run_log_entries(request: Request) -> Response:
    account = authenticate(request)
    require_admin(request, account, action="run_log_read", object_type=RUN)
    page, _ = list_query(request)
    result = runs_service(request).list_log(page)
    return json(page_json(result, [log_entry_json(e) for e in result.items]))


@router.post("/volume-acceptances")
async def create_volume_acceptance(request: Request) -> Response:
    """201 without Location: an acceptance has no address of its own."""
    account = authenticate(request)
    require_admin(
        request, account, action="volume_accept", object_type=VOLUME_ACCEPTANCE
    )
    service = runs_service(request)
    who = actor(account)
    fields = await _body(
        request,
        {"run_id": INT, "supplier_id": INT},
        (),
        required=("run_id", "supplier_id"),
        on_reject=lambda code: service.reject_acceptance(who, code),
    )
    acceptance = service_call(
        service.accept_volume, who, fields["run_id"], fields["supplier_id"]
    )
    return json(acceptance_json(acceptance), 201)


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

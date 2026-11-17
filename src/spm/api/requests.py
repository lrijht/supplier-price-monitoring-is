"""Reading API requests in the contract's order of checks.

401 (session) → 403 (role) → 422 (path and query parameters) → 404 (resource)
→ 415 (Content-Type) → 422 (body) → 409 (state). The operations call these
helpers in that order; FastAPI's own parameter parsing is not used, because it
would answer 422 before the session check.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

from fastapi import Request

from spm.api.errors import (
    FORBIDDEN_DETAIL,
    UNAUTHENTICATED_DETAIL,
    UNSUPPORTED_MEDIA_DETAIL,
    ProblemError,
)
from spm.auth import SESSION_COOKIE, Account, AuthService
from spm.services.errors import (
    INVALID_TYPE,
    READ_ONLY_FIELD,
    REQUIRED,
    UNKNOWN_FIELD,
    FieldError,
)

PAGE_INVALID = "Номер сторінки має бути цілим числом від 1."
PERIOD_INVALID = "Період має бути одним із: last_7_days, last_30_days, all."
KIND_INVALID = "Вид події має бути одним із: price_change, appeared, disappeared."
_INTEGER = re.compile(r"[+-]?\d+")
_MAX_ID = 2**63 - 1

STR, BOOL, INT, NUMBER = "string", "boolean", "integer", "number"


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def authenticate(request: Request) -> Account:
    """401 without a live session."""
    account = auth_service(request).resolve(request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise ProblemError(401, "unauthenticated", UNAUTHENTICATED_DETAIL)
    return account


def require_admin(
    request: Request,
    account: Account,
    *,
    action: str,
    object_type: str | None,
    object_id: str | int | None = None,
) -> None:
    """403 «немає доступу» for the manager on an administrator operation."""
    if account.is_admin:
        return
    if isinstance(object_id, str):
        object_id = maybe_id(object_id)
    auth_service(request).deny(
        account, action=action, object_type=object_type, object_id=object_id
    )
    raise ProblemError(403, "forbidden", FORBIDDEN_DETAIL)


def maybe_id(value: str) -> int | None:
    if not _INTEGER.fullmatch(value):
        return None
    number = int(value)
    return number if abs(number) <= _MAX_ID else None


def path_id(value: str, field: str) -> int:
    """An identifier from the path; not an integer — 422 invalid_type."""
    if not _INTEGER.fullmatch(value):
        raise ProblemError.validation([FieldError(field, "invalid_type", INVALID_TYPE)])
    number = int(value)
    # Too large for storage: no such record (checked as 404 later).
    return number if abs(number) <= _MAX_ID else 0


def query_errors(
    query: Mapping[str, str], *, active: bool = False
) -> tuple[int, bool | None, list[FieldError]]:
    """``page`` (and ``active``) of a list; unknown parameters are ignored."""
    errors: list[FieldError] = []
    page = 1
    raw_page = query.get("page")
    if raw_page is not None:
        if raw_page.isascii() and raw_page.isdigit() and int(raw_page) >= 1:
            page = int(raw_page)
        else:
            errors.append(FieldError("page", "page_invalid", PAGE_INVALID))
    flag: bool | None = None
    if active and "active" in query:
        value = query["active"]
        if value in ("true", "false"):
            flag = value == "true"
        else:
            errors.append(FieldError("active", "invalid_type", INVALID_TYPE))
    return page, flag, errors


def list_query(request: Request, *, active: bool = False) -> tuple[int, bool | None]:
    page, flag, errors = query_errors(request.query_params, active=active)
    if errors:
        raise ProblemError.validation(errors)
    return page, flag


def _reject_constant(name: str) -> Any:
    raise ValueError(f"not JSON: {name}")


def require_json(request: Request) -> None:
    """415 for a body that is not declared as JSON."""
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/json":
        raise ProblemError(415, "unsupported_media_type", UNSUPPORTED_MEDIA_DETAIL)


async def json_object(request: Request) -> dict[str, Any]:
    """The body as a JSON object; 422 if it is not valid JSON or not an object."""
    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError):
        raise ProblemError.malformed_json() from None
    if not isinstance(body, dict):
        raise ProblemError.validation([FieldError(None, "invalid_type", INVALID_TYPE)])
    return body


def _type_ok(value: Any, kind: str) -> bool:
    if kind == STR:
        return isinstance(value, str)
    if kind == BOOL:
        return isinstance(value, bool)
    if kind == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == NUMBER:
        return (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    raise ValueError(kind)


def check_fields(
    body: dict[str, Any],
    fields: Mapping[str, str],
    *,
    read_only: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    non_empty: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Check the body against a schema of the contract; return the known fields.

    Unknown field — unknown_field, read-only field — read_only_field, wrong JSON
    type — invalid_type, missing ``required`` — required, empty ``non_empty``
    string — required.
    """
    errors: list[FieldError] = []
    for name, value in body.items():
        if name in fields:
            if not _type_ok(value, fields[name]):
                errors.append(FieldError(name, "invalid_type", INVALID_TYPE))
            elif name in non_empty and not value:
                errors.append(FieldError(name, "required", REQUIRED))
        elif name in read_only:
            errors.append(FieldError(name, "read_only_field", READ_ONLY_FIELD))
        else:
            errors.append(FieldError(name, "unknown_field", UNKNOWN_FIELD))
    for name in required:
        if name not in body:
            errors.append(FieldError(name, "required", REQUIRED))
    if errors:
        raise ProblemError.validation(errors)
    return {name: body[name] for name in fields if name in body}

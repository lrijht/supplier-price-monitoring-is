"""API error model: application/problem+json (REQ-NF-031, schema Problem).

Titles and details are Ukrainian (REQ-NF-001); a 500 answer carries no
internal details, they go only to the technical log (REQ-NF-018).
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from spm.services.errors import (
    MALFORMED_JSON,
    Conflict,
    FieldError,
    NotFound,
    ValidationFailed,
)

API_PREFIX = "/api/v1"
PROBLEM_MEDIA_TYPE = "application/problem+json"

# Problem.title of the contract: the Ukrainian name of the HTTP status.
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
VALIDATION_DETAIL = "Запит містить некоректні значення."
UNAUTHENTICATED_DETAIL = "Потрібно увійти в систему."
FORBIDDEN_DETAIL = "немає доступу"
NOT_FOUND_DETAIL = "Ресурс не знайдено."
UNSUPPORTED_MEDIA_DETAIL = (
    "Запит має бути у форматі JSON (Content-Type: application/json)."
)


class ProblemResponse(JSONResponse):
    media_type = PROBLEM_MEDIA_TYPE


def problem(
    status: int,
    title: str,
    detail: str,
    code: str,
    errors: Iterable[FieldError] | None = None,
) -> ProblemResponse:
    content: dict = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
    }
    if errors:
        content["errors"] = [
            {"field": e.field, "code": e.code, "detail": e.detail} for e in errors
        ]
    return ProblemResponse(status_code=status, content=content)


class ProblemError(Exception):
    """An error answer of an API operation."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        errors: list[FieldError] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail
        self.errors = errors or []

    def response(self) -> ProblemResponse:
        return problem(
            self.status, TITLES[self.status], self.detail, self.code, self.errors
        )

    @classmethod
    def validation(cls, errors: list[FieldError]) -> ProblemError:
        return cls(422, "validation_failed", VALIDATION_DETAIL, errors)

    @classmethod
    def malformed_json(cls) -> ProblemError:
        return cls.validation([FieldError(None, "malformed_json", MALFORMED_JSON)])

    @classmethod
    def from_service(cls, exc: Exception) -> ProblemError:
        if isinstance(exc, ValidationFailed):
            return cls.validation(exc.errors)
        if isinstance(exc, Conflict):
            return cls(409, exc.code, exc.detail, exc.errors)
        if isinstance(exc, NotFound):
            return cls(404, "not_found", NOT_FOUND_DETAIL)
        raise TypeError(f"not a service error: {exc!r}")


def is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def not_found_problem() -> ProblemResponse:
    return problem(404, TITLES[404], NOT_FOUND_DETAIL, "not_found")


def method_not_allowed_problem(method: str) -> ProblemResponse:
    return problem(
        405,
        TITLES[405],
        f"Метод {method} не підтримується для цієї адреси.",
        "method_not_allowed",
    )


def internal_error_problem() -> ProblemResponse:
    return problem(
        500,
        TITLES[500],
        "Сталася внутрішня помилка. Спробуйте пізніше.",
        "internal_error",
    )


def internal_error_response(path: str) -> Response:
    """The 500 answer for an unexpected exception at ``path``."""
    if is_api_path(path):
        return internal_error_problem()
    return PlainTextResponse("Сталася внутрішня помилка. Спробуйте пізніше.", 500)


async def _problem_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, ProblemError)
    return exc.response()


def install_error_handlers(
    app: FastAPI, *, web_not_found, web_method_not_allowed
) -> None:
    """404 and 405 under /api/v1 answer in the error model; outside it the web
    interface answers (``web_not_found``, ``web_method_not_allowed``)."""

    async def not_found(request: Request, exc: Exception) -> Response:
        # An unknown address is not a contract operation, so no session check
        # applies to it: the router's own 404 becomes the problem answer.
        if is_api_path(request.url.path):
            return not_found_problem()
        return await web_not_found(request)

    async def method_not_allowed(request: Request, exc: Exception) -> Response:
        if is_api_path(request.url.path):
            return method_not_allowed_problem(request.method)
        return await web_method_not_allowed(request)

    async def http_exception(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, StarletteHTTPException)
        if exc.status_code == 404:
            return await not_found(request, exc)
        if exc.status_code == 405:
            return await method_not_allowed(request, exc)
        return PlainTextResponse(str(exc.detail), exc.status_code)

    app.add_exception_handler(StarletteHTTPException, http_exception)
    app.add_exception_handler(ProblemError, _problem_handler)

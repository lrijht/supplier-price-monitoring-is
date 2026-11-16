"""API error model: application/problem+json (REQ-NF-031, schema Problem).

Titles and details are Ukrainian (REQ-NF-001); a 500 answer carries no
internal details, they go only to the technical log (REQ-NF-018).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

API_PREFIX = "/api/v1"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemResponse(JSONResponse):
    media_type = PROBLEM_MEDIA_TYPE


def problem(status: int, title: str, detail: str, code: str) -> ProblemResponse:
    return ProblemResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
        },
    )


def is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def not_found_problem() -> ProblemResponse:
    return problem(404, "Не знайдено", "Ресурс не знайдено.", "not_found")


def internal_error_problem() -> ProblemResponse:
    return problem(
        500,
        "Внутрішня помилка сервера",
        "Сталася внутрішня помилка. Спробуйте пізніше.",
        "internal_error",
    )


def internal_error_response(path: str) -> Response:
    """The 500 answer for an unexpected exception at ``path``."""
    if is_api_path(path):
        return internal_error_problem()
    return PlainTextResponse("Сталася внутрішня помилка. Спробуйте пізніше.", 500)


async def _not_found_handler(request: Request, exc: Exception) -> Response:
    if is_api_path(request.url.path):
        return not_found_problem()
    return PlainTextResponse("Сторінку не знайдено.", 404)


def install_error_handlers(app: FastAPI) -> None:
    # An unknown address is not a contract operation, so no session check
    # applies to it: the router's own 404 becomes the problem answer.
    app.add_exception_handler(404, _not_found_handler)

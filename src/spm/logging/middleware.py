"""Request log middleware (REQ-NF-018, REQ-NF-032).

For every HTTP request it creates a request identifier, writes the HTTP request
record to the action log after the response, and writes an unexpected
exception to the technical log with the same identifier. The identifier is
never put into the response (Р-126).
"""

from __future__ import annotations

import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from spm.logging.redaction import SecretCollector
from spm.logging.writer import (
    JsonLinesLog,
    current_request_account,
    reset_request_account,
    reset_request_id,
    set_request_id,
    start_request_account,
)

HTTP_REQUEST_EVENT = "http_request"
EXCEPTION_EVENT = "unhandled_exception"

# ASGI types (the same shapes Starlette uses), kept local to avoid importing
# an undeclared transitive package.
Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestLogMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        action_log: JsonLinesLog,
        technical_log: JsonLinesLog,
        error_response: Callable[[str], ASGIApp],
    ) -> None:
        self.app = app
        self.action_log = action_log
        self.technical_log = technical_log
        # Builds the 500 answer for a path; supplied when the app is assembled,
        # so this component does not depend on the API error model.
        self.error_response = error_response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = set_request_id(uuid.uuid4().hex)
        account_token = start_request_account()
        started = time.perf_counter()
        secrets = SecretCollector(scope.get("headers", []))
        state = {"status": None}

        async def receive_tracked() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                secrets.feed_body(message.get("body", b""))
            return message

        async def send_tracked(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive_tracked, send_tracked)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a 500
            self._log_exception(scope, exc, secrets)
            if state["status"] is None:
                response = self.error_response(scope["path"])
                await response(scope, receive, send_tracked)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            login, role = current_request_account()
            self.action_log.write(
                level="info",
                event=HTTP_REQUEST_EVENT,
                login=login,
                role=role,
                method=scope["method"],
                path=scope["path"],  # ASGI path carries no query string
                status=state["status"] if state["status"] is not None else 500,
                duration_ms=max(duration_ms, 0),
            )
            reset_request_account(account_token)
            reset_request_id(token)

    def _log_exception(
        self, scope: Scope, exc: Exception, secrets: SecretCollector
    ) -> None:
        try:
            description = secrets.redact(f"{type(exc).__name__}: {exc}")
            trace = secrets.redact("".join(traceback.format_exception(exc)))
        except Exception:  # noqa: BLE001 - never log unredacted text
            description, trace = type(exc).__name__, None
        self.technical_log.write(
            level="error",
            event=EXCEPTION_EVENT,
            result="error",
            method=scope["method"],
            path=scope["path"],
            error=description,
            traceback=trace,
        )

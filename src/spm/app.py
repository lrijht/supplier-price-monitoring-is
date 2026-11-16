"""Application assembly.

``create_app`` is the only place where the configuration is read; the values
are passed to the components as parameters.

Run: ``uvicorn spm.app:create_app --factory`` with SPM_SESSION_SECRET set.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from spm.api import install_error_handlers, internal_error_response
from spm.clock import Clock, SystemClock
from spm.config import Config, load_config
from spm.logging import JsonLinesLog, RequestLogMiddleware
from spm.storage import init_database


def create_app(config: Config | None = None, *, clock: Clock | None = None) -> FastAPI:
    if config is None:
        config = load_config(os.environ, Path(".env"))
    if clock is None:
        clock = SystemClock()

    action_log = JsonLinesLog(config.action_log_path, clock)
    technical_log = JsonLinesLog(config.technical_log_path, clock)
    database_path = config.database_path

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_database(database_path)
        yield

    # The contract is spec/openapi.yaml; no generated docs pages are served.
    app = FastAPI(
        title="Моніторинг цін постачальників",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(
        RequestLogMiddleware,
        action_log=action_log,
        technical_log=technical_log,
        error_response=internal_error_response,
    )
    return app

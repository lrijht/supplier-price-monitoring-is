"""Application assembly.

``create_app`` is the only place where the configuration is read; the values
are passed to the components as parameters. It also connects the parts that
must not import each other: the parsers of ``update`` are handed to
``services`` here (docs/architecture.md, section 5).

Run: ``uvicorn spm.app:create_app --factory`` with SPM_SESSION_SECRET set.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from spm import api, web
from spm.auth import AuthService
from spm.clock import Clock, SystemClock
from spm.config import Config, load_config
from spm.logging import JsonLinesLog, RequestLogMiddleware
from spm.services import ActionRecorder, Directories, SettingsService
from spm.storage import Database, init_database
from spm.update.parsers import available_parsers


def create_app(config: Config | None = None, *, clock: Clock | None = None) -> FastAPI:
    if config is None:
        config = load_config(os.environ, Path(".env"))
    if clock is None:
        clock = SystemClock()

    action_log = JsonLinesLog(config.action_log_path, clock)
    technical_log = JsonLinesLog(config.technical_log_path, clock)
    database_path = config.database_path
    database = Database(database_path)
    recorder = ActionRecorder(action_log)

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
    app.state.auth = AuthService(database, clock, action_log, config.session_secret)
    app.state.directories = Directories(database, recorder, available_parsers)
    app.state.settings = SettingsService(database, recorder)

    api.install_error_handlers(
        app,
        web_not_found=web.not_found,
        web_method_not_allowed=web.method_not_allowed,
    )
    app.include_router(api.router)
    app.include_router(web.router)
    app.add_middleware(
        RequestLogMiddleware,
        action_log=action_log,
        technical_log=technical_log,
        error_response=api.internal_error_response,
    )
    return app

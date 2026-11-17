"""Application assembly.

``create_app`` is the only place where the configuration is read; the values
are passed to the components as parameters. It also connects the parts that
must not import each other: the parsers of ``update`` and its implementation of
the run port are handed to ``services`` here (docs/architecture.md, section 5).

Run the system with one command (REQ-NF-014), SPM_SESSION_SECRET set:
``uvicorn spm.app:create_service --factory``. One process serves the web
interface and the API and runs the scheduler and the catch-up.
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
from spm.services import ActionRecorder, Directories, Runs, SettingsService, Views
from spm.storage import Database, init_database
from spm.update import UpdateRunner
from spm.update.parsers import available_parsers


def create_app(
    config: Config | None = None,
    *,
    clock: Clock | None = None,
    background_updates: bool = False,
) -> FastAPI:
    """The application. With ``background_updates`` the start-up performs the
    catch-up (REQ-F-023) and a scheduler thread checks the clock (REQ-F-018);
    without it nothing runs by itself (tests drive ``app.state.updates``)."""
    if config is None:
        config = load_config(os.environ, Path(".env"))
    if clock is None:
        clock = SystemClock()

    action_log = JsonLinesLog(config.action_log_path, clock)
    technical_log = JsonLinesLog(config.technical_log_path, clock)
    database_path = config.database_path
    database = Database(database_path)
    recorder = ActionRecorder(action_log)
    updates = UpdateRunner(database, clock, action_log, technical_log)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_database(database_path)
        if background_updates:
            updates.start_background()
        try:
            yield
        finally:
            if background_updates:
                updates.stop_background()

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
    app.state.settings = SettingsService(database, recorder, clock)
    app.state.updates = updates
    app.state.runs = Runs(database, recorder, clock, launcher=updates)
    app.state.views = Views(database, clock)

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


def create_service() -> FastAPI:
    """The system as it runs on the server: configuration from the environment
    or ``.env``, the system clock, the scheduler on (REQ-NF-014)."""
    return create_app(background_updates=True)

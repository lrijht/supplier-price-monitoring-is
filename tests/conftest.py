"""Shared fixtures.

Imports of ``spm`` and ``simulator`` happen inside fixtures, so that while the
code does not exist yet every test fails on its own instead of the whole
collection failing with one ImportError.
"""

from __future__ import annotations

import importlib
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from helpers import ADMIN_LOGIN, ADMIN_PASSWORD, MANAGER_LOGIN, MANAGER_PASSWORD

ROOT = Path(__file__).resolve().parents[1]

TEST_SESSION_SECRET = "test-session-secret-not-for-production"

# REQ-NF-013: tests never reach the external network. Only loopback is allowed.
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _check_address(address: object) -> None:
    if isinstance(address, tuple) and address:
        host = str(address[0])
        if host not in _LOCAL_HOSTS and not host.startswith("127."):
            raise RuntimeError(f"external network access in tests: {address!r}")


def _guarded_connect(self: socket.socket, address: object) -> None:
    _check_address(address)
    return _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
    _check_address(address)
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)


# --- system under test: spm -------------------------------------------------


@pytest.fixture
def spm_config_module():
    return importlib.import_module("spm.config")


@pytest.fixture
def spm_app_module():
    return importlib.import_module("spm.app")


@pytest.fixture
def spm_clock_module():
    return importlib.import_module("spm.clock")


@pytest.fixture
def config_factory(spm_config_module, tmp_path: Path) -> Callable[..., object]:
    """Build a Config with every path inside tmp_path; keyword overrides."""

    def make(**overrides: object) -> object:
        values: dict[str, object] = {
            "session_secret": TEST_SESSION_SECRET,
            "database_path": tmp_path / "spm.db",
            "action_log_path": tmp_path / "actions.log",
            "technical_log_path": tmp_path / "technical.log",
        }
        values.update(overrides)
        return spm_config_module.Config(**values)

    return make


@pytest.fixture
def config(config_factory):
    return config_factory()


@pytest.fixture
def clock(spm_clock_module):
    """Controlled clock, 2026-07-15 12:00 Kyiv summer time (UTC+3)."""
    return spm_clock_module.ManualClock(datetime(2026, 7, 15, 9, 0, tzinfo=UTC))


@pytest.fixture
def app_factory(spm_app_module, config, clock):
    def make(cfg: object | None = None, clk: object | None = None):
        return spm_app_module.create_app(cfg or config, clock=clk or clock)

    return make


@pytest.fixture
def app(app_factory):
    return app_factory()


@pytest.fixture
def client_factory():
    """Return a function that opens a TestClient (startup and shutdown run)."""
    from fastapi.testclient import TestClient

    opened: list[TestClient] = []

    def make(application) -> TestClient:
        tc = TestClient(application, raise_server_exceptions=False)
        tc.__enter__()
        opened.append(tc)
        return tc

    yield make
    for tc in opened:
        tc.__exit__(None, None, None)


@pytest.fixture
def client(app, client_factory):
    return client_factory(app)


@pytest.fixture
def read_log() -> Callable[[Path], list[dict]]:
    """Read a JSON Lines log file; every non-empty line must be one JSON object."""

    def read(path: Path) -> list[dict]:
        if not Path(path).exists():
            return []
        records = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    return read


@pytest.fixture
def add_failing_route():
    """Insert a test-only route that raises, ahead of the app's own routes.

    The route needs no session: per the interface the session check is a
    dependency of contract operations, not a global middleware.
    """
    from fastapi.routing import APIRoute

    def add(application, path: str, message: str) -> None:
        async def failing_endpoint() -> None:
            raise RuntimeError(message)

        route = APIRoute(path, failing_endpoint, methods=["GET", "POST"])
        application.router.routes.insert(0, route)

    return add


# --- simulator --------------------------------------------------------------


@pytest.fixture
def simulator_module():
    return importlib.import_module("simulator")


def _supplier(slug: str, name: str, layout: str, prefix: str) -> dict:
    return {
        "slug": slug,
        "name": name,
        "layout": layout,
        "mode": "normal",
        "delay_seconds": 2,
        "keep_items": 2,
        "items": [
            {
                "sku": f"{prefix}-1",
                "name": "Плита ДСП біла",
                "unit": "шт",
                "price": "1250.50",
            },
            {
                "sku": f"{prefix}-2",
                "name": "Кромка ПВХ 2 мм",
                "unit": "м.п.",
                "price": "18.40",
            },
            {
                "sku": f"{prefix}-3",
                "name": "Петля накладна",
                "unit": "шт",
                "price": None,
            },
            {
                "sku": f"{prefix}-4",
                "name": "Ручка-скоба 128",
                "unit": "шт",
                "price": "95.00",
            },
        ],
    }


@pytest.fixture
def sim_data() -> dict:
    """Fictional simulator data: 3 suppliers, one per layout, all in normal mode."""
    return {
        "suppliers": [
            _supplier("alfa", "Альфа", "table", "А"),
            _supplier("beta", "Бета", "cards", "Б"),
            _supplier("vega", "Вега", "list", "В"),
        ]
    }


@pytest.fixture
def sim_data_file(tmp_path: Path, sim_data: dict) -> Path:
    path = tmp_path / "simulator-data.json"
    path.write_text(json.dumps(sim_data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def write_sim_data(sim_data_file: Path) -> Callable[[dict], None]:
    def write(data: dict) -> None:
        sim_data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return write


@pytest.fixture
def sim_client(simulator_module, sim_data_file, client_factory):
    return client_factory(simulator_module.create_app(sim_data_file))


@pytest.fixture
def live_simulator(simulator_module, sim_data_file) -> Iterator[str]:
    """Run the simulator on a free loopback port; yield its base URL."""
    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(
            simulator_module.create_app(sim_data_file),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("simulator did not start on the loopback address")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


# --- B1.2: accounts, sessions, supplier items --------------------------------
# Interface added by the B1.2 tests: see logs/2026-11-16-b1-2-tests.md,
# section "Інтерфейс, заданий тестами".


@pytest.fixture
def auth_cli_module():
    return importlib.import_module("spm.auth.cli")


@pytest.fixture
def storage_module():
    return importlib.import_module("spm.storage")


@pytest.fixture
def run_account_command(auth_cli_module, config):
    """Run the account set-up command (REQ-F-006) in-process.

    ``password`` is what the person types at every password prompt. Returns
    the exit code (0 — created, otherwise refused); an argparse exit counts.
    The prompts the command showed are kept in ``run.prompts``.
    """

    def run(argv: list[str], password: str = "", cfg: object | None = None) -> int:
        def read_password(prompt: str) -> str:
            run.prompts.append(prompt)
            return password

        try:
            code = auth_cli_module.main(
                list(argv), config=cfg or config, read_password=read_password
            )
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return code

    run.prompts = []
    return run


@pytest.fixture
def accounts(run_account_command) -> None:
    """Administrator "admin" and manager "manager" with test passwords."""
    assert run_account_command([ADMIN_LOGIN, "admin"], ADMIN_PASSWORD) == 0
    assert run_account_command([MANAGER_LOGIN, "manager"], MANAGER_PASSWORD) == 0


def _logged_in(client, login: str, password: str):
    resp = client.post("/api/v1/sessions", json={"login": login, "password": password})
    assert resp.status_code == 201, resp.text
    return client


@pytest.fixture
def admin_client(app, client_factory, accounts):
    """A client of ``app`` with an administrator session opened through the API."""
    return _logged_in(client_factory(app), ADMIN_LOGIN, ADMIN_PASSWORD)


@pytest.fixture
def manager_client(app, client_factory, accounts):
    """A client of ``app`` with a manager session opened through the API."""
    return _logged_in(client_factory(app), MANAGER_LOGIN, MANAGER_PASSWORD)


@pytest.fixture
def add_item(storage_module, config):
    """Create a supplier item directly in storage (no update runs yet, T-15)."""
    from datetime import date

    def add(
        supplier_id: int,
        sku: str,
        name: str = "Позиція",
        unit: str = "шт",
        last_seen_date: date = date(2026, 7, 14),
    ) -> int:
        return storage_module.add_supplier_item(
            config.database_path,
            supplier_id=supplier_id,
            sku=sku,
            name=name,
            unit=unit,
            last_seen_date=last_seen_date,
        )

    return add


# --- B2: update runs, scheduler, feed ------------------------------------------
# Interface added by the B2 tests: see logs/2026-11-16-b2-tests.md, section
# "Інтерфейс, заданий тестами".


@pytest.fixture
def update_fetch_module():
    """Module with the page fetch timeout constant (REQ-F-026)."""
    return importlib.import_module("spm.update.fetch")


class SimServer:
    """The simulator on a loopback port, wrapped for tests.

    The wrapper counts requests per catalogue path and can hold the answer for
    a catalogue until the test releases it, so a run can be caught "in
    progress" without real waiting. The pages themselves come from the
    simulator and its data file (REQ-NF-013, REQ-NF-028).
    """

    def __init__(self, data_file: Path) -> None:
        self.data_file = data_file
        self.base = ""
        self.suppliers: dict[str, dict] = {}
        self._counts: dict[str, int] = {}
        self._holds: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self.write()

    # data file
    def write(self) -> None:
        data = {"suppliers": list(self.suppliers.values())}
        self.data_file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

    def put(
        self,
        slug: str,
        items: list[dict],
        *,
        name: str | None = None,
        layout: str = "table",
        mode: str = "normal",
        delay_seconds: float = 2,
        keep_items: int | None = None,
    ) -> None:
        """Set the page of one catalogue; other catalogues stay as they are."""
        self.suppliers[slug] = {
            "slug": slug,
            "name": name or slug,
            "layout": layout,
            "mode": mode,
            "delay_seconds": delay_seconds,
            "keep_items": len(items) if keep_items is None else keep_items,
            "items": items,
        }
        self.write()

    def mode(self, slug: str, mode: str, **fields: object) -> None:
        self.suppliers[slug].update(mode=mode, **fields)
        self.write()

    def url(self, slug: str) -> str:
        return f"{self.base}/catalog/{slug}"

    # requests
    def requests(self, slug: str) -> int:
        with self._lock:
            return self._counts.get(f"/catalog/{slug}", 0)

    def hold(self, slug: str) -> None:
        self._holds[slug] = threading.Event()

    def release(self, slug: str | None = None) -> None:
        for key, event in list(self._holds.items()):
            if slug is None or key == slug:
                event.set()

    def wrap(self, app):
        import asyncio

        async def asgi(scope, receive, send):
            if scope["type"] == "http":
                path = scope["path"]
                with self._lock:
                    self._counts[path] = self._counts.get(path, 0) + 1
                hold = self._holds.get(path.rsplit("/", 1)[-1])
                deadline = time.monotonic() + 60
                while hold is not None and not hold.is_set():
                    if time.monotonic() > deadline:
                        break
                    await asyncio.sleep(0.01)
            await app(scope, receive, send)

        return asgi


@pytest.fixture
def sim(simulator_module, tmp_path: Path) -> Iterator[SimServer]:
    """The simulator on a free loopback port with request counting and holds."""
    import uvicorn

    server_data = SimServer(tmp_path / "sim-b2.json")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(
            server_data.wrap(simulator_module.create_app(server_data.data_file)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("simulator did not start on the loopback address")
        time.sleep(0.02)
    server_data.base = f"http://127.0.0.1:{port}"
    yield server_data
    server_data.release()
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def updates(app, admin_client):
    """The update runner of ``app`` (the port of ``services`` that ``update``
    implements); the database exists because ``admin_client`` started the app."""
    return app.state.updates


@pytest.fixture
def world(app, admin_client, sim, updates, clock, storage_module, config):
    from helpers_b2 import World

    return World(
        app=app,
        admin=admin_client,
        sim=sim,
        updates=updates,
        clock=clock,
        storage=storage_module,
        config=config,
    )


@pytest.fixture
def keep_sessions(request, clock, monkeypatch) -> list:
    """Keep the test's sessions open while the clock jumps by hours and days.

    REQ-NF-021 ends a session after 8 idle hours of the application clock;
    B2 tests move that clock across days between requests. After every move
    each logged-in client of the test opens a new session through the API
    (``POST /sessions``), as a user would log in again. Clients:
    ``admin_client``, ``manager_client`` (if the test uses them) and the ones
    in the returned list (``restart`` adds its clients).
    """
    from helpers import ADMIN_LOGIN, ADMIN_PASSWORD, MANAGER_LOGIN, MANAGER_PASSWORD

    extra: list = []
    original = clock.advance

    def relogin(tc, login: str, password: str) -> None:
        resp = tc.post("/api/v1/sessions", json={"login": login, "password": password})
        assert resp.status_code == 201, resp.text

    def advance(delta) -> None:
        original(delta)
        for name, login, password in (
            ("admin_client", ADMIN_LOGIN, ADMIN_PASSWORD),
            ("manager_client", MANAGER_LOGIN, MANAGER_PASSWORD),
        ):
            if name in request.fixturenames:
                relogin(request.getfixturevalue(name), login, password)
        for tc in extra:
            relogin(tc, ADMIN_LOGIN, ADMIN_PASSWORD)

    monkeypatch.setattr(clock, "advance", advance)
    return extra


@pytest.fixture
def restart(spm_app_module, config, clock, client_factory, accounts, keep_sessions):
    """Start the system again on the same database, logs and clock.

    Returns ``(app, admin_client)``; nothing runs by itself — the test calls
    ``app.state.updates.startup()`` as the process does right after start.
    """
    from helpers import ADMIN_LOGIN, ADMIN_PASSWORD

    def start():
        application = spm_app_module.create_app(config, clock=clock)
        tc = client_factory(application)
        resp = tc.post(
            "/api/v1/sessions", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD}
        )
        assert resp.status_code == 201, resp.text
        keep_sessions.append(tc)
        return application, tc

    return start


@pytest.fixture
def worker(config) -> Iterator[Callable[..., object]]:
    """Run an update in a separate process that the test can kill.

    ``worker(moment, trigger, started_by)`` starts ``tests/update_worker.py``:
    a process of the system on the same database and logs, with a controlled
    clock fixed at ``moment``, that performs one run. ``.kill()`` stops it the
    way a stopped system process stops (REQ-F-024).
    """
    import os
    import subprocess
    import sys

    started: list[subprocess.Popen] = []

    def start(moment: datetime, trigger: str = "scheduled", started_by: str = ""):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tests" / "update_worker.py"),
                str(config.database_path),
                str(config.action_log_path),
                str(config.technical_log_path),
                TEST_SESSION_SECRET,
                moment.isoformat(),
                trigger,
                started_by,
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        started.append(proc)
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

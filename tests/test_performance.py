"""Performance tests (T-45): REQ-NF-008 and REQ-NF-009.

Marked ``performance``: the usual run leaves them out (``addopts`` in
pyproject.toml), and they run with a separate command:

    python -m pytest -m performance -s tests/test_performance.py

Times are measured with the standard library (``time.perf_counter``). Each test
prints one JSON line with the measured values and the machine characteristics
for the protocol (REQ-NF-009: processor, memory, operating system, Python).
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import sqlite3
import sys
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from helpers import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    API,
    MANAGER_LOGIN,
    MANAGER_PASSWORD,
    create_supplier,
)
from helpers_b2 import wait_run

pytestmark = pytest.mark.performance

ROOT = Path(__file__).resolve().parents[1]
LIMIT_SECONDS = 2.0  # REQ-NF-009
RUN_LIMIT = timedelta(minutes=5)  # REQ-NF-008

# REQ-NF-009, test volume: 1 000 materials, each linked at all 10 suppliers,
# daily prices for 1 year, a change feed of 10 000 events for that year.
MATERIALS = 1_000
SUPPLIERS = 10
DAYS = 365
EVENTS = 10_000
LAST_DAY = date(2026, 11, 17)
FIRST_DAY = LAST_DAY - timedelta(days=DAYS - 1)
# Kyiv 2026-11-17 18:00 (UTC+2): the prices of the last day are not stale.
NOW = datetime(2026, 11, 17, 16, 0, tzinfo=UTC)
REPEATS = 3


def _memory_bytes() -> int | None:
    if sys.platform == "win32":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def machine() -> dict:
    memory = _memory_bytes()
    return {
        "processor": platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(),
        "memory_gib": round(memory / 2**30, 1) if memory else None,
        "os": platform.platform(),
        "python": platform.python_version(),
    }


def report(name: str, values: dict) -> None:
    line = {"test": name, "machine": machine(), **values}
    print("\nPERFORMANCE " + json.dumps(line, ensure_ascii=False))


# --- REQ-NF-008: one run of all simulator suppliers within 5 minutes ----------


# REQ-NF-008: a run on the simulator with all its suppliers (the shipped data
# file, served on 127.0.0.1) — in the run log the finish minus the start is at
# most 5 minutes. The system runs on the system clock, as on the server.
def test_run_of_all_simulator_suppliers_within_5_minutes(
    spm_app_module, simulator_module, config, client_factory, tmp_path, accounts
):
    import socket
    import threading

    import uvicorn

    data_file = tmp_path / "sim-data.json"
    shutil.copyfile(ROOT / "simulator" / "data.json", data_file)
    sim_suppliers = json.loads(data_file.read_text(encoding="utf-8"))["suppliers"]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(
            simulator_module.create_app(data_file),
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
        assert time.monotonic() < deadline and thread.is_alive(), "simulator down"
        time.sleep(0.02)
    try:
        app = spm_app_module.create_app(config)  # system clock
        admin = client_factory(app)
        resp = admin.post(
            f"{API}/sessions", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD}
        )
        assert resp.status_code == 201, resp.text
        for s in sim_suppliers:
            create_supplier(
                admin,
                s["name"],
                catalog_url=f"http://127.0.0.1:{port}/catalog/{s['slug']}",
                parser=f"{s['layout']}_layout",
            )
        wall = time.perf_counter()
        resp = admin.post(f"{API}/runs")
        assert resp.status_code == 202, resp.text
        run = wait_run(admin, resp.json()["id"], timeout=RUN_LIMIT.total_seconds() + 60)
        wall = time.perf_counter() - wall
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    started = datetime.fromisoformat(run["started_at"])
    finished = datetime.fromisoformat(run["finished_at"])
    duration = finished - started
    report(
        "REQ-NF-008",
        {
            "suppliers": len(sim_suppliers),
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "duration_seconds": duration.total_seconds(),
            "wall_seconds": round(wall, 3),
        },
    )
    assert run["status"] == "success"
    assert {s["status"] for s in run["supplier_run_statuses"]} == {"success"}
    assert len(run["supplier_run_statuses"]) == len(sim_suppliers)
    assert timedelta(0) <= duration <= RUN_LIMIT


# --- REQ-NF-009: screens on the test volume within 2 seconds ------------------


def _price(material: int, supplier: int, day: int) -> str:
    base = 100 + material * 3 + supplier * 7
    step = ((day * 7 + supplier * 3 + material) % 11) - 5  # −5 … +5 per mille
    return str((Decimal(base) * (1000 + step) / 1000).quantize(Decimal("0.01")))


def fill_test_volume(database: Path) -> dict:
    """Write the REQ-NF-009 test volume straight into the database."""
    conn = sqlite3.connect(database)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executemany(
            "INSERT INTO suppliers (id, name, name_key, catalog_url, parser, active)"
            " VALUES (?, ?, ?, ?, 'table_layout', 1)",
            [
                (s, f"Постачальник {s:02d}", f"постачальник {s:02d}",
                 f"http://127.0.0.1:8001/catalog/s{s:02d}")
                for s in range(1, SUPPLIERS + 1)
            ],
        )  # fmt: skip
        conn.executemany(
            "INSERT INTO materials (id, name, name_key, unit, active)"
            " VALUES (?, ?, ?, 'шт', 1)",
            [
                (m, f"Матеріал {m:04d}", f"матеріал {m:04d}")
                for m in range(1, MATERIALS + 1)
            ],
        )

        def item_id(m: int, s: int) -> int:
            return (m - 1) * SUPPLIERS + s

        conn.executemany(
            "INSERT INTO supplier_items (id, supplier_id, sku, name, unit,"
            " last_seen_date, material_id, feed_base) VALUES (?, ?, ?, ?, 'шт', ?, ?, ?)",
            [
                (item_id(m, s), s, f"S{s:02d}-{m:04d}", f"Позиція {m:04d}",
                 LAST_DAY.isoformat(), m, _price(m, s, DAYS - 1))
                for m in range(1, MATERIALS + 1)
                for s in range(1, SUPPLIERS + 1)
            ],
        )  # fmt: skip
        days = [(d, (FIRST_DAY + timedelta(days=d)).isoformat()) for d in range(DAYS)]

        def prices():
            for m in range(1, MATERIALS + 1):
                for s in range(1, SUPPLIERS + 1):
                    iid = item_id(m, s)
                    for d, day in days:
                        yield iid, day, _price(m, s, d), "шт", m, 0

        conn.executemany(
            "INSERT INTO daily_prices (supplier_item_id, price_date, price, unit,"
            " material_id, unit_mismatch) VALUES (?, ?, ?, ?, ?, ?)",
            prices(),
        )

        def events():
            for k in range(EVENTS):
                m = k % MATERIALS + 1
                s = (k // MATERIALS) % SUPPLIERS + 1
                d = k * DAYS // EVENTS
                day = FIRST_DAY + timedelta(days=d)
                old, new = _price(m, s, max(d - 1, 0)), _price(m, s, d)
                percent = ((Decimal(new) - Decimal(old)) * 100 / Decimal(old)).quantize(
                    Decimal("0.1")
                )
                created = datetime(day.year, day.month, day.day, 1, 30, tzinfo=UTC)
                yield (
                    "price_change", day.isoformat(),
                    (created + timedelta(microseconds=k)).isoformat(),
                    m, s, item_id(m, s), old, new, str(percent), None,
                )  # fmt: skip

        conn.executemany(
            "INSERT INTO events (kind, event_date, created_at, material_id,"
            " supplier_id, supplier_item_id, old_price, new_price, change_percent,"
            " price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            events(),
        )
        conn.commit()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("materials", "suppliers", "supplier_items", "daily_prices",
                          "events")
        }  # fmt: skip
    finally:
        conn.close()
    return counts


def measure(client, path: str) -> list[float]:
    times = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        resp = client.get(path)
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200, (path, resp.status_code)
    return times


# REQ-NF-009: on the test volume the first page of the comparison list, the
# comparison of a material, the history of a material for the whole period and
# the first page of the change feed without filters each answer within 2 s.
def test_screens_on_test_volume_within_2_seconds(
    spm_app_module, spm_clock_module, storage_module, config, client_factory, accounts
):
    storage_module.init_database(config.database_path)
    fill_started = time.perf_counter()
    counts = fill_test_volume(config.database_path)
    fill_seconds = time.perf_counter() - fill_started
    assert counts == {
        "materials": MATERIALS,
        "suppliers": SUPPLIERS,
        "supplier_items": MATERIALS * SUPPLIERS,
        "daily_prices": MATERIALS * SUPPLIERS * DAYS,
        "events": EVENTS,
    }

    app = spm_app_module.create_app(config, clock=spm_clock_module.ManualClock(NOW))
    manager = client_factory(app)
    resp = manager.post(
        f"{API}/sessions", json={"login": MANAGER_LOGIN, "password": MANAGER_PASSWORD}
    )
    assert resp.status_code == 201, resp.text

    material = MATERIALS // 2
    screens = {
        "comparison_list_page_1": "/material-comparisons",
        "material_comparison": f"/material-comparisons/{material}",
        "material_history_all": f"/price-history?material_id={material}&period=all",
        "feed_page_1": "/events",
    }
    results = {name: measure(manager, path) for name, path in screens.items()}

    # The screens show the volume, not an empty page.
    page = manager.get(screens["material_history_all"]).text
    assert (
        FIRST_DAY.isoformat() in page or (FIRST_DAY + timedelta(1)).isoformat() in page
    )
    assert "Матеріал 0001" in manager.get(screens["comparison_list_page_1"]).text

    report(
        "REQ-NF-009",
        {
            "volume": counts,
            "fill_seconds": round(fill_seconds, 1),
            "repeats": REPEATS,
            "seconds": {k: [round(t, 3) for t in v] for k, v in results.items()},
        },
    )
    for name, times in results.items():
        assert max(times) <= LIMIT_SECONDS, (name, times)

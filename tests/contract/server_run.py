"""Run the contract scenarios against the real server on invented data (T-59).

Usage, from the repository root with the project's Python 3.12:

    python tests/contract/server_run.py LABEL [--port 8000] [--sim-port 8831]

What it does, every time the same way, so two runs can be compared:

1. Creates ``var/contract-LABEL/`` (it must not exist) with an invented
   simulator data file; the database and both logs of the run go there too.
2. Creates the accounts ``admin`` and ``manager`` with the set-up command
   (``spm.auth.cli``). The admin password is the one scenario П-01 logs in
   with; the manager password and the session secret are random and live only
   in memory and in the environment of the child processes.
3. Starts the simulator and the application with the start command of B2
   (``uvicorn spm.app:create_service --factory --no-access-log``).
4. Fills the system through the API: 4 suppliers, 42 manual runs, 5 materials,
   links, a unit change and a smaller page of one supplier, so that the fixed
   ids of ``scenarios.json`` (suppliers 1-4, materials 1-3, items 12, 21, 29,
   runs 40-42) mean what the scenarios expect.
5. Runs ``run_mock_scenarios.py`` in stages (``--only``). Some scenarios need
   states that exclude each other (a run in progress, no active supplier, an
   item without a link, a logged-out session, a failing database), so the
   stages put the system into each state first. Session cookies come from
   ``POST /sessions`` and are handed over with ``--sessions``.
6. Stops both processes and writes ``results.json``, one row per scenario in
   the order of ``scenarios.json``.

Standard library only. Nothing outside ``var/contract-LABEL/`` is written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).with_name("run_mock_scenarios.py")
SCENARIOS_FILE = Path(__file__).with_name("scenarios.json")
ADMIN_PASSWORD = "correct-password"  # the password of scenario П-01
RUN_COUNT = 42  # scenarios use runs 40, 41 and 42
SLOW_SECONDS = 5  # keeps a run in progress for Н-09, below the fetch timeout


def item(sku: str, name: str, unit: str, price: str | None) -> dict:
    return {"sku": sku, "name": name, "unit": unit, "price": price}


def simulator_data(port: int) -> dict:
    """Invented catalogues. Suppliers are processed by name, items in page
    order, so the item ids of the first run are 1-10, 11-22, 23-27, 28-32."""
    arka = [
        item("АР-101", "ЛДСП дуб сонома 16 мм", "шт", "1250.50"),
        item("АР-102", "ДВП біле 3 мм", "шт", "310.00"),
        item("АР-103", "ЛДСП графіт 16 мм", "шт", "1402.00"),
        item("АР-104", "ЛДСП білий 10 мм", "шт", "990.00"),
        item("АР-105", "Плита МДФ 16 мм", "шт", "1611.20"),
        item("АР-106", "Плита МДФ 22 мм", "шт", "2010.00"),
        item("АР-107", "ХДФ білий 3 мм", "шт", "355.40"),
        item("АР-108", "Стільниця дуб 38 мм", "шт", "3120.00"),
        item("АР-109", "Фанера 12 мм", "шт", "1105.00"),
        item("АР-110", "Фанера 18 мм", "шт", None),
    ]
    brama = [
        item("БМ-01", "ЛДСП дуб сонома 16 мм", "шт", "1199.00"),
        item("БМ-02", "ЛДСП горіх 16 мм", "шт", "1320.00"),
        item("БМ-03", "Кромка ПВХ біла 2 мм", "м.п.", "17.90"),
        item("БМ-04", "Кромка ПВХ дуб 2 мм", "м.п.", "20.80"),
        item("БМ-05", "Кромка ПВХ графіт 1 мм", "м.п.", "12.10"),
        item("БМ-06", "Петля накладна", "шт", "58.00"),
        item("БМ-07", "Ручка-скоба 96 мм", "шт", "74.50"),
        item("БМ-08", "Ручка-скоба 128 мм", "шт", "88.00"),
        item("БМ-09", "Напрямна 350 мм", "компл.", "190.00"),
        item("БМ-10", "Напрямна 450 мм", "компл.", "205.00"),
        item("БМ-11", "Плита ДСП біла 16 мм", "шт", "980.00"),
        item("БМ-12", "Шуруп 4х16", "уп.", None),
    ]
    vega = [
        item("ВФ-01", "Петля з доводчиком", "шт", "64.20"),
        item("ВФ-02", "Ручка-кнопка", "шт", "31.00"),
        item("ВФ-03", "Опора регульована", "шт", "22.40"),
        item("ВФ-04", "Полицетримач", "уп.", "45.00"),
        item("ВФ-05", "Стяжка ексцентрикова", "уп.", "118.00"),
    ]
    gran = [
        item("ГД-01", "Скло матове 4 мм", "м2", "640.00"),
        item("ГД-02", "ЛДСП дуб сонома 16 мм", "шт", "1288.00"),
        item("ГД-03", "Дзеркало 4 мм", "м2", "720.00"),
        item("ГД-04", "Профіль алюмінієвий", "м.п.", "96.00"),
        item("ГД-05", "Ущільнювач", "м.п.", "8.50"),
    ]

    def supplier(slug: str, name: str, layout: str, items: list[dict]) -> dict:
        return {
            "slug": slug,
            "name": name,
            "layout": layout,
            "mode": "normal",
            "delay_seconds": SLOW_SECONDS,
            "keep_items": 3,
            "items": items,
        }

    return {
        "suppliers": [
            supplier("arka", "Арка Плита", "table", arka),
            supplier("brama", "Брама Меблі", "cards", brama),
            supplier("vega", "Вега Фурнітура", "list", vega),
            supplier("gran", "Грань Декор", "table", gran),
        ]
    }


SUPPLIERS = [  # id 1-4
    ("Арка Плита", "arka", "table_layout"),
    ("Брама Меблі", "brama", "cards_layout"),
    ("Вега Фурнітура", "vega", "list_layout"),
    ("Грань Декор", "gran", "table_layout"),
]
MATERIALS = [  # id 1-5
    ("ЛДСП дуб сонома 16 мм", "шт"),  # П-10 (q=лдсп), П-12, П-14, П-15, П-22
    ("Плита МДФ 18 мм", "шт"),  # П-19 target, then deactivated by П-13
    ("Кромка ПВХ біла 2 мм", "м.п."),  # Н-12: unit differs from item 29
    ("ДВП біле 3 мм", "шт"),  # П-17: its item changes the unit to «уп»
    ("Плита ДСП біла 16 мм", "шт"),  # item 21 before П-19 relinks it
]
LINKS = [  # (item id, sku, material id) after the first run
    (1, "АР-101", 1),
    (2, "АР-102", 4),
    (11, "БМ-01", 1),  # Н-13: supplier 2 already has material 1
    (21, "БМ-11", 5),  # П-19 relinks it: 200
]
EXPECTED_ITEMS = {12: "БМ-02", 29: "ГД-02"}  # unlinked until the scenarios


# Stages: (name, scenario ids). The runner keeps the order of scenarios.json
# inside a stage; stages run in this order, each after its preparation.
STAGES = [
    (
        "main-1",
        ["П-01", "П-02", *[f"П-{n:02}" for n in (4, 5, 6, 7, 8, 9, 10)]]
        + [f"П-{n:02}" for n in (11, 12, 14, 15, 16, 17)]
        + ["Н-06"],
    ),
    ("links", ["П-18", "П-19", "П-20"]),
    ("deactivate-material", ["П-13"]),
    (
        "main-2",
        [f"П-{n:02}" for n in (*range(21, 27), *range(29, 38))]
        + [f"Н-{n:02}" for n in range(1, 45) if n not in (6, 9)],
    ),
    # A-06, the CSV export: the manager without search, the administrator with
    # «лдсп», and 401 without a session — on the data of main-2.
    ("export", ["П-38", "П-39", "Н-46"]),
    ("run-in-progress", ["П-27", "Н-09"]),
    ("database-locked", ["Н-45", "Н-47"]),
    ("no-active-suppliers", ["П-28"]),
    ("logout", ["П-03"]),
]


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.cookie: str | None = None

    def call(self, method: str, path: str, body: dict | None = None):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw, status, got = response.read(), response.status, response.headers
        except urllib.error.HTTPError as error:
            raw, status, got = error.read(), error.code, error.headers
        return status, (json.loads(raw) if raw else None), got

    def ok(self, method: str, path: str, body: dict | None = None, *, expect: int):
        status, data, _ = self.call(method, path, body)
        if status != expect:
            raise SystemExit(f"{method} {path}: {status}, expected {expect}: {data}")
        return data


def login(base_url: str, user: str, password: str) -> str:
    api = Api(base_url)
    status, data, headers = api.call(
        "POST", "/sessions", {"login": user, "password": password}
    )
    if status != 201:
        raise SystemExit(f"login {user}: {status} {data}")
    match = re.match(r"\s*(spm_session=[^;]+)", headers.get("Set-Cookie", ""))
    if match is None:
        raise SystemExit(f"login {user}: no session cookie")
    return match.group(1)


def wait_until_up(base_url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            Api(base_url).call("GET", "/sessions/current")
            return
        except OSError:
            time.sleep(0.2)
    raise SystemExit(f"{base_url} did not start")


def wait_run(api: Api, run_id: int, seconds: float = 120) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = api.ok("GET", f"/runs/{run_id}", expect=200)
        if run["status"] != "in_progress":
            return run
        time.sleep(0.1)
    raise SystemExit(f"run {run_id} did not finish")


def manual_run(api: Api, expected_id: int) -> dict:
    run = api.ok("POST", "/runs", expect=202)
    if run["id"] != expected_id:
        raise SystemExit(f"run id {run['id']}, expected {expected_id}")
    return wait_run(api, run["id"])


def edit_simulator(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change({s["slug"]: s for s in data["suppliers"]})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_item(supplier: dict, sku: str) -> dict:
    return next(i for i in supplier["items"] if i["sku"] == sku)


def create_accounts(env: dict[str, str]) -> None:
    from spm.auth import cli  # the set-up command of REQ-F-006
    from spm.config import load_config

    config = load_config(env)
    passwords = {"admin": ADMIN_PASSWORD, "manager": env["CONTRACT_MANAGER_PASSWORD"]}
    for user, password in passwords.items():
        code = cli.main(
            [user, user], config=config, read_password=lambda _, p=password: p
        )
        if code != 0:
            raise SystemExit(f"account {user}: exit code {code}")


def seed(api: Api, sim_data: Path, sim_port: int) -> None:
    for name, slug, parser in SUPPLIERS:
        api.ok(
            "POST",
            "/suppliers",
            {
                "name": name,
                "catalog_url": f"http://127.0.0.1:{sim_port}/catalog/{slug}",
                "parser": parser,
                "active": True,
            },
            expect=201,
        )
    manual_run(api, 1)  # creates the items 1-32

    unlinked = api.ok("GET", "/unlinked-items", expect=200)["items"]
    skus = {row["supplier_item"]["id"]: row["supplier_item"]["sku"] for row in unlinked}
    for item_id, sku in [*EXPECTED_ITEMS.items(), *[(i, s) for i, s, _ in LINKS]]:
        if skus.get(item_id) != sku:
            raise SystemExit(f"item {item_id} is {skus.get(item_id)}, expected {sku}")

    for name, unit in MATERIALS:
        api.ok(
            "POST",
            "/materials",
            {"name": name, "unit": unit, "active": True},
            expect=201,
        )
    for item_id, _, material_id in LINKS:
        api.ok(
            "PUT",
            f"/supplier-items/{item_id}/link",
            {"material_id": material_id},
            expect=201,
        )

    # П-17: the linked item АР-102 now comes in «уп»; its first price of the
    # date is marked, so it is an item that needs attention.
    edit_simulator(sim_data, lambda s: find_item(s["arka"], "АР-102").update(unit="уп"))
    manual_run(api, 2)  # prices and «з'явився» events of the linked items
    edit_simulator(
        sim_data, lambda s: find_item(s["arka"], "АР-101").update(price="1313.03")
    )
    for run_id in range(3, RUN_COUNT - 1):  # 3: «зміна ціни» +5 %; up to run 40
        manual_run(api, run_id)
    # Run 41: Вега shows 3 of its 5 items, «частково» (П-31 accepts the volume).
    edit_simulator(sim_data, lambda s: s["vega"].update(mode="reduced"))
    run = manual_run(api, RUN_COUNT - 1)
    vega = next(r for r in run["supplier_run_statuses"] if r["supplier"]["id"] == 3)
    if not vega["volume_acceptance_available"]:
        raise SystemExit(f"run 41: Вега is {vega['status']}, expected partial")
    # Run 42 without Вега, so run 41 stays its last run with a status.
    api.ok("PATCH", "/suppliers/3", {"active": False}, expect=200)
    manual_run(api, RUN_COUNT)


def run_stage(
    base_url: str, ids: list[str], sessions: Path, out: Path
) -> list[list[str]]:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            base_url,
            "--target",
            "server",
            "--sessions",
            str(sessions),
            "--only",
            *ids,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    out.write_text(result.stdout + result.stderr, encoding="utf-8")
    rows = []
    for line in result.stdout.splitlines()[2:]:
        if not line.strip():
            break
        rows.append([cell.strip() for cell in line.split("|")])
    if sorted(r[0] for r in rows) != sorted(ids):
        raise SystemExit(f"stage output does not match {ids}: see {out}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("label")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sim-port", type=int, default=8831)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # The scenarios go to localhost, as in docs/api/scenarios.md. Filling uses
    # the loopback address directly: on Windows "localhost" first tries ::1,
    # where the server does not listen, and every request waits for that.
    base_url = f"http://localhost:{args.port}/api/v1"
    seed_url = f"http://127.0.0.1:{args.port}/api/v1"
    work = ROOT / "var" / f"contract-{args.label}"
    work.mkdir(parents=True, exist_ok=False)
    sim_data = work / "sim-data.json"
    sim_data.write_text(
        json.dumps(simulator_data(args.sim_port), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    database = work / "spm.db"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
        "SPM_SESSION_SECRET": secrets.token_urlsafe(32),
        "SPM_DATABASE_PATH": str(database),
        "SPM_ACTION_LOG_PATH": str(work / "actions.log"),
        "SPM_TECHNICAL_LOG_PATH": str(work / "technical.log"),
        "CONTRACT_MANAGER_PASSWORD": secrets.token_urlsafe(16),
    }
    sys.path[:0] = [str(ROOT / "src")]
    create_accounts(env)
    manager_password = env.pop("CONTRACT_MANAGER_PASSWORD")

    processes = []
    try:
        for name, command in (
            ("sim", ["-m", "simulator", str(args.sim_port), str(sim_data)]),
            (
                "app",
                [
                    "-m",
                    "uvicorn",
                    "spm.app:create_service",
                    "--factory",
                    "--no-access-log",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
            ),
        ):
            log = (work / f"{name}.out").open("w", encoding="utf-8")
            processes.append(
                subprocess.Popen(
                    [sys.executable, *command],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        wait_until_up(seed_url)

        api = Api(seed_url)
        api.cookie = login(seed_url, "admin", ADMIN_PASSWORD)
        # The start-up catch-up (REQ-F-023) must find no supplier yet, or it
        # would take run id 1; wait for its «немає активних постачальників».
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if api.ok("GET", "/run-log-entries", expect=200)["total_items"]:
                break
            time.sleep(0.1)
        seed(api, sim_data, args.sim_port)

        sessions = work / "sessions.json"
        sessions.write_text(
            json.dumps(
                {
                    "admin": api.cookie,
                    "manager": login(seed_url, "manager", manager_password),
                }
            ),
            encoding="utf-8",
        )
        logout_sessions = work / "sessions-logout.json"
        logout_sessions.write_text(
            json.dumps({"admin": login(seed_url, "admin", ADMIN_PASSWORD)}),
            encoding="utf-8",
        )

        results: dict[str, dict] = {}
        for number, (stage, ids) in enumerate(STAGES, start=1):
            lock = None
            if stage == "run-in-progress":
                edit_simulator(sim_data, lambda s: s["arka"].update(mode="slow"))
            elif stage == "database-locked":
                # The artificial failure of Н-45 and Н-47: the database is held by
                # another connection, so the request fails after the busy
                # timeout and the server answers 500.
                lock = sqlite3.connect(database, isolation_level=None)
                lock.execute("BEGIN EXCLUSIVE")
            elif stage == "no-active-suppliers":
                for supplier in api.ok("GET", "/suppliers", expect=200)["items"]:
                    if supplier["active"]:
                        api.ok(
                            "PATCH",
                            f"/suppliers/{supplier['id']}",
                            {"active": False},
                            expect=200,
                        )
            try:
                rows = run_stage(
                    base_url,
                    ids,
                    logout_sessions if stage == "logout" else sessions,
                    work / f"stage-{number}-{stage}.txt",
                )
            finally:
                if lock is not None:
                    lock.execute("ROLLBACK")
                    lock.close()
            for row in rows:
                results[row[0]] = {
                    "id": row[0],
                    "request": row[1],
                    "expected": row[2],
                    "got": row[3],
                    "result": row[4],
                    "note": row[5] if len(row) > 5 else "",
                    "stage": f"{number} {stage}",
                }
            if stage == "run-in-progress":
                wait_run(api, RUN_COUNT + 1)
                edit_simulator(sim_data, lambda s: s["arka"].update(mode="normal"))
    finally:
        for process in reversed(processes):
            process.terminate()
            process.wait(timeout=10)

    order = [
        s["id"]
        for s in json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))["scenarios"]
    ]
    table = [results[i] for i in order]
    (work / "results.json").write_text(
        json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for row in table:
        print(" | ".join(str(row[k]) for k in ("id", "result", "got", "stage", "note")))
    failed = sum(1 for row in table if row["result"] == "FAIL")
    print(f"\n{len(table)} scenarios: {len(table) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

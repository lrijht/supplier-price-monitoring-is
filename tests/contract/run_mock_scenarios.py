"""Run the contract scenarios from scenarios.json against a mock or a real server.

Standard library only. Usage:

    python tests/contract/run_mock_scenarios.py [BASE_URL] [--target mock|server]

BASE_URL defaults to http://127.0.0.1:4010 (Prism serves paths without /api/v1).
Against the real server use http://localhost:8000/api/v1 --target server.

Checks per scenario: HTTP status, Content-Type of the body, `code` of a problem
response, `errors[].field`/`errors[].code` pairs, required and absent fields,
required response headers. Prism answers an unknown path or method in its own
error format, so for scenarios marked `prism_format` only the status is checked
when the target is the mock.

Exit code is 0 when every scenario passes, 1 otherwise.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:4010"
SCENARIOS_FILE = Path(__file__).with_name("scenarios.json")
TIMEOUT_SECONDS = 10
MISSING = object()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def build_url(base_url: str, path: str) -> str:
    # Paths in scenarios may hold Cyrillic query values; percent-encode them.
    return base_url.rstrip("/") + urllib.parse.quote(path, safe="/?=&")


def send(base_url: str, scenario: dict, sessions: dict) -> tuple[int, dict, bytes]:
    headers = {"Accept": "application/json, application/problem+json"}
    data = None
    if "body" in scenario:
        data = json.dumps(scenario["body"], ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif "raw_body" in scenario:
        data = scenario["raw_body"].encode("utf-8")
    if scenario.get("session"):
        headers["Cookie"] = sessions[scenario["session"]]
    headers.update(scenario.get("headers", {}))

    request = urllib.request.Request(
        build_url(base_url, scenario["path"]),
        data=data,
        headers=headers,
        method=scenario["method"],
    )
    try:
        with OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def lookup(document, dotted_path: str):
    """Return the value at a dotted path such as `items.0.id`, or MISSING."""
    current = document
    for part in dotted_path.split("."):
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return MISSING
    return current


def header(headers: dict, name: str):
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def check(
    scenario: dict, status: int, headers: dict, raw: bytes, target: str
) -> list[str]:
    expect = scenario["expect"]
    failures = []
    if status != expect["status"]:
        failures.append(f"status {status}, expected {expect['status']}")
        return failures
    if target == "mock" and scenario.get("mock", {}).get("prism_format"):
        return failures

    for name in expect.get("headers", []):
        if header(headers, name) is None:
            failures.append(f"header {name} missing")

    if not raw:
        if expect.get("code") or expect.get("required"):
            failures.append("empty body")
        return failures

    content_type = (header(headers, "Content-Type") or "").split(";")[0].strip()
    expected_type = "application/problem+json" if status >= 400 else "application/json"
    if content_type != expected_type:
        failures.append(f"Content-Type {content_type!r}, expected {expected_type}")

    try:
        body = json.loads(raw)
    except ValueError:
        failures.append("body is not JSON")
        return failures

    code = lookup(body, "code")
    if "code" in expect and code != expect["code"]:
        shown = "missing" if code is MISSING else repr(code)
        failures.append(f"code {shown}, expected {expect['code']!r}")
    if expect.get("errors"):
        actual = {(e.get("field"), e.get("code")) for e in body.get("errors") or []}
        for error in expect["errors"]:
            if (error["field"], error["code"]) not in actual:
                failures.append(f"errors[] lacks {error['field']}/{error['code']}")
    for path in expect.get("required", []):
        if lookup(body, path) is MISSING:
            failures.append(f"field {path} missing")
    for path in expect.get("absent", []):
        if lookup(body, path) is not MISSING:
            failures.append(f"field {path} must be absent")
    return failures


def run(base_url: str, target: str, only: set[str]) -> int:
    spec = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    rows = []
    for scenario in spec["scenarios"]:
        if only and scenario["id"] not in only:
            continue
        try:
            status, headers, raw = send(base_url, scenario, spec["sessions"])
            failures = check(scenario, status, headers, raw, target)
            got = str(status)
        except OSError as error:
            failures = [f"request failed: {error}"]
            got = "—"
        if (
            not failures
            and target == "mock"
            and scenario.get("mock", {}).get("prism_format")
        ):
            note = "status only (Prism error format)"
        else:
            note = "; ".join(failures)
        expected = str(scenario["expect"]["status"])
        if scenario["expect"].get("code"):
            expected += " " + scenario["expect"]["code"]
        rows.append(
            (
                scenario["id"],
                f"{scenario['method']} {scenario['path']}",
                expected,
                got,
                "FAIL" if failures else "PASS",
                note,
            )
        )

    titles = ("ID", "Request", "Expected", "Got", "Result", "Note")
    widths = [
        max(len(str(row[i])) for row in [titles, *rows]) for i in range(len(titles))
    ]
    for row in [titles, tuple("-" * w for w in widths), *rows]:
        print(
            " | ".join(
                str(cell).ljust(widths[i]) for i, cell in enumerate(row)
            ).rstrip()
        )

    failed = sum(1 for row in rows if row[4] == "FAIL")
    print(f"\n{len(rows)} scenarios: {len(rows) - failed} passed, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", nargs="?", default=DEFAULT_BASE_URL)
    parser.add_argument("--target", choices=("mock", "server"), default="mock")
    parser.add_argument("--only", nargs="*", default=[], help="scenario IDs to run")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run(args.base_url, args.target, set(args.only))


if __name__ == "__main__":
    sys.exit(main())

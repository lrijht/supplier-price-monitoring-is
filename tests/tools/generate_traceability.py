"""Generate spec/traceability.md from spec/srs.md and spec/openapi.yaml.

Standard library only. Columns taken from the SRS: source, acceptance criterion,
BDD (the "**Вимоги:**" line of each scenario in appendix A) and UC (the
"Вимоги" row of each use case table in section 3.7). The API column lists the
operationIds of spec/openapi.yaml whose x-req-ids contain the requirement, in
contract order. The column "Тікет" is carried over from the current matrix by
requirement ID.

The columns "Тест", "Код" and "Документація" list the files that cite the
requirement ID: pytest modules (tests/**/test_*.py) and the contract scenarios
(tests/contract/scenarios.json); system code (src/spm, including templates) and
the simulator; the design and API documents in DOC_FILES. CODE_EXTRA adds the
modules that implement a requirement without citing its ID (found by review),
NOTES fills the cells of requirements that are checked otherwise.

Usage:
    python tests/tools/generate_traceability.py          # rewrite the matrix
    python tests/tools/generate_traceability.py --check  # exit 1 on mismatch
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRS_PATH = ROOT / "spec" / "srs.md"
OPENAPI_PATH = ROOT / "spec" / "openapi.yaml"
MATRIX_PATH = ROOT / "spec" / "traceability.md"

DASH = "—"
CARRIED_COLUMNS = 4  # Тікет, Тест, Код, Документація (only Тікет is kept)

DOC_FILES = ("docs/architecture.md", "docs/api/resources.md", "docs/api/scenarios.md")
# The test of this generator cites IDs as sample data, not as requirements.
SKIP_TESTS = ("test_traceability.py",)

# Modules that implement a requirement but do not cite its ID (verification
# 2026-11-18, logs/2026-11-18-verification.md).
CODE_EXTRA = {
    "REQ-F-004": ["spm/api/requests.py", "spm/auth/service.py", "spm/web/routes.py"],
    "REQ-F-013": ["spm/services/directories.py", "spm/storage/schema.py"],
    "REQ-F-025": [
        "spm/update/runner.py",
        "spm/update/fetch.py",
        "spm/update/parsers.py",
    ],
    "REQ-F-027": ["spm/update/parsers.py", "spm/storage/updates.py"],
    "REQ-F-053": ["spm/update/runner.py", "spm/storage/updates.py"],
    "REQ-F-071": ["spm/api/routes.py"],
    "REQ-NF-003": ["spm/web/routes.py", "spm/web/templates/base.html"],
    "REQ-NF-011": ["pyproject.toml"],
    "REQ-NF-019": ["spm/storage/updates.py", "spm/services/runs.py"],
    "REQ-NF-025": ["pyproject.toml"],
}

# Cells of requirements without an automatic test or without code: (Тест, Код).
NOTES = {
    "REQ-NF-002": (
        "ручна перевірка в Chrome і Firefox (T-48), протоколу ще немає",
        None,
    ),
    "REQ-NF-008": ("немає — тест і протокол швидкодії T-45 не виконано", None),
    "REQ-NF-009": ("немає — тест швидкодії T-45 не виконано", None),
    "REQ-NF-010": ("не приймається (ціль проєктування)", "не приймається"),
    "REQ-NF-012": ("історія git (правило розробки)", "історія git"),
    "REQ-NF-023": ("історія git (правило розробки)", "історія git"),
}

INTRO = """# Матриця трасування вимог

Матриця зв'язує кожну вимогу `spec/srs.md` з її джерелом, критерієм прийняття, сценаріями BDD
(додаток А SRS) і сценаріями використання UC (SRS, п. 3.7). Джерело — це рішення SKED-діалогу
(стислий перелік — додаток В SRS), розділ задуму або правила проєкту. Колонку «Тікет» ведуть
вручну за `docs/tickets.md`.
Колонки «Тест», «Код» і «Документація» згенеровано за ID вимог у файлах репозиторію: модулі pytest
і сценарії контракту в `tests/`, код у `src/spm` та імітатор, документи `docs/architecture.md`,
`docs/api/resources.md` і `docs/api/scenarios.md`. Модулі, що реалізують вимогу без її ID, і
вимоги, які перевіряються інакше, внесено за звітом верифікації (`logs/2026-11-18-verification.md`).

Таблицю згенеровано з `spec/srs.md`. Критерії подано в один рядок; повне формулювання —
у SRS, і за розбіжності чинним є SRS. Вимоги впорядковано за ID.
Колонку «API» згенеровано з `spec/openapi.yaml`: це operationId операцій, у `x-req-ids`
яких є вимога, або «—»; після API-GATE контракт змінюється лише адендумом (REQ-NF-031, Р-117).

{totals}
BDD покривають ключові потоки й граничні випадки, UC — основні потоки ролей і системи. Вимоги без
сценарію (позначка «—») перевіряються напряму за критерієм прийняття. REQ-NF-010 — ціль
проєктування без приймання; REQ-NF-012 і REQ-NF-023 — правила розробки (SRS, п. 3.6), до приймання
продукту не входять.
"""

TABLE_HEAD = (
    "| REQ ID | Джерело | Критерій прийняття | BDD | UC | API | Тікет | Тест | Код | Документація |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
)

OUTRO = """## Операції API за вимогами

Зворотне трасування «REQ-ID → операції API» з методами, адресами, ролями й кодами — у
`docs/api/resources.md`, розділ 3.
"""

REQ_HEADING = re.compile(r"^#### (REQ-(?:F|NF)-\d{3})\. ")
BDD_HEADING = re.compile(r"^#### (BDD-\d{3})\. ")
UC_HEADING = re.compile(r"^#### (UC-\d{2})\. ")
ID_PATTERN = re.compile(r"(?:REQ-(?:F|NF)|BDD|UC)-\d+")


def plural(n: int, one: str, few: str, many: str) -> str:
    """Return the Ukrainian plural form for n."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def id_key(item_id: str) -> tuple[str, int]:
    prefix, _, number = item_id.rpartition("-")
    return prefix, int(number)


def parse_requirements(lines: list[str]) -> dict[str, dict[str, str]]:
    """Return source and one-line criterion of every requirement."""
    reqs: dict[str, dict[str, str]] = {}
    i = 0
    while i < len(lines):
        match = REQ_HEADING.match(lines[i])
        if not match:
            i += 1
            continue
        req_id = match.group(1)
        source = ""
        criterion_parts: list[str] = []
        i += 1
        while i < len(lines) and not lines[i].startswith("#"):
            line = lines[i]
            if line.startswith("- **Джерело:** "):
                source = line.removeprefix("- **Джерело:** ").strip()
            elif line.startswith("- **Критерій прийняття:**"):
                first = line.removeprefix("- **Критерій прийняття:**").strip()
                if first:
                    criterion_parts.append(first)
                i += 1
                # The criterion ends at the first non-empty line without indent.
                while i < len(lines):
                    nxt = lines[i]
                    if nxt.strip() == "":
                        i += 1
                        continue
                    if not nxt.startswith(" "):
                        break
                    criterion_parts.append(nxt.strip().removeprefix("- "))
                    i += 1
                continue
            i += 1
        reqs[req_id] = {"source": source, "criterion": " ".join(criterion_parts)}
    return reqs


def parse_bdd(lines: list[str]) -> dict[str, list[str]]:
    """Map requirement ID to BDD scenarios that list it."""
    links: dict[str, set[str]] = {}
    current = None
    for line in lines:
        match = BDD_HEADING.match(line)
        if match:
            current = match.group(1)
            continue
        if current and line.startswith("**Вимоги:**"):
            for req_id in ID_PATTERN.findall(line):
                links.setdefault(req_id, set()).add(current)
            current = None
    return {k: sorted(v, key=id_key) for k, v in links.items()}


def parse_uc(lines: list[str]) -> tuple[dict[str, list[str]], int]:
    """Map requirement ID to use cases whose "Вимоги" row lists it."""
    links: dict[str, set[str]] = {}
    current = None
    uc_ids: set[str] = set()
    for line in lines:
        match = UC_HEADING.match(line)
        if match:
            current = match.group(1)
            uc_ids.add(current)
            continue
        if line.startswith("#"):
            current = None
            continue
        if current and line.startswith("| Вимоги |"):
            for req_id in ID_PATTERN.findall(line):
                links.setdefault(req_id, set()).add(current)
    return {k: sorted(v, key=id_key) for k, v in links.items()}, len(uc_ids)


def parse_openapi(text: str) -> dict[str, list[str]]:
    """Map requirement ID to operationIds, in contract order (no YAML parser)."""
    links: dict[str, list[str]] = {}
    operation = None
    for line in text.splitlines():
        match = re.match(r"^\s+operationId:\s*(\S+)\s*$", line)
        if match:
            operation = match.group(1)
            continue
        match = re.match(r"^\s+x-req-ids:\s*\[(.*)\]\s*$", line)
        if match and operation:
            for req_id in ID_PATTERN.findall(match.group(1)):
                ops = links.setdefault(req_id, [])
                if operation not in ops:
                    ops.append(operation)
    return links


def parse_carried(matrix_text: str) -> dict[str, list[str]]:
    """Return the implementation columns of the current matrix by REQ ID."""
    carried: dict[str, list[str]] = {}
    for line in matrix_text.splitlines():
        if not line.startswith("| REQ-"):
            continue
        cells = line[2:-2].split(" | ")
        carried[cells[0]] = cells[-CARRIED_COLUMNS:]
    return carried


def join_or_dash(items: list[str], code: bool = False) -> str:
    if not items:
        return DASH
    return ", ".join(f"`{x}`" if code else x for x in items)


REQ_ID = re.compile(r"REQ-(?:F|NF)-\d{3}")


def cite_map(files: dict[str, str]) -> dict[str, list[str]]:
    """Map requirement ID to the names of the files whose text cites it."""
    links: dict[str, set[str]] = {}
    for name, text in files.items():
        for req_id in REQ_ID.findall(text):
            links.setdefault(req_id, set()).add(name)
    return {k: sorted(v) for k, v in links.items()}


def _texts(base: Path, patterns: tuple[str, ...], strip: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in patterns:
        for path in base.glob(pattern):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            if path.name in SKIP_TESTS:
                continue
            out[path.relative_to(strip).as_posix()] = read(path)
    return out


def scan_repository(root: Path = ROOT) -> dict[str, dict[str, list[str]]]:
    """Return the "Тест", "Код" and "Документація" links found in the repository."""
    tests = _texts(
        root / "tests", ("**/test_*.py", "contract/scenarios.json"), root / "tests"
    )
    code = _texts(root / "src", ("spm/**/*.py", "spm/**/*.html"), root / "src")
    code |= _texts(root, ("simulator/**/*.py",), root)
    docs = {name: read(root / name) for name in DOC_FILES if (root / name).is_file()}
    return {"test": cite_map(tests), "code": cite_map(code), "doc": cite_map(docs)}


def implementation_cells(
    req_id: str, links: dict[str, dict[str, list[str]]]
) -> list[str]:
    """Return the cells "Тест", "Код" and "Документація" of one requirement."""
    note_test, note_code = NOTES.get(req_id, (None, None))
    tests = links["test"].get(req_id, [])
    code = sorted(set(links["code"].get(req_id, [])) | set(CODE_EXTRA.get(req_id, [])))
    docs = links["doc"].get(req_id, [])
    return [
        join_or_dash(tests, code=True) if tests or not note_test else note_test,
        join_or_dash(code, code=True) if code or not note_code else note_code,
        join_or_dash(docs, code=True),
    ]


def generate(
    srs_text: str,
    openapi_text: str,
    matrix_text: str,
    links: dict[str, dict[str, list[str]]] | None = None,
) -> str:
    if links is None:
        links = scan_repository()
    lines = srs_text.splitlines()
    reqs = parse_requirements(lines)
    bdd = parse_bdd(lines)
    uc, uc_count = parse_uc(lines)
    api = parse_openapi(openapi_text)
    carried = parse_carried(matrix_text)
    bdd_count = sum(1 for line in lines if BDD_HEADING.match(line))

    def rows(kind: str) -> str:
        out = []
        ids = sorted((r for r in reqs if r.startswith(f"REQ-{kind}-")), key=id_key)
        for req_id in ids:
            req = reqs[req_id]
            ticket = carried.get(req_id, [""] * CARRIED_COLUMNS)[0]
            rest = [ticket, *implementation_cells(req_id, links)]
            cells = [
                req_id,
                req["source"],
                req["criterion"],
                join_or_dash(bdd.get(req_id, [])),
                join_or_dash(uc.get(req_id, [])),
                join_or_dash(api.get(req_id, []), code=True),
                *rest,
            ]
            out.append("| " + " | ".join(cells) + " |\n")
        return "".join(out)

    f_count = sum(1 for r in reqs if r.startswith("REQ-F-"))
    nf_count = sum(1 for r in reqs if r.startswith("REQ-NF-"))
    totals = (
        "Разом: "
        + plural(
            f_count,
            "функціональна вимога",
            "функціональні вимоги",
            "функціональних вимог",
        )
        + " і "
        + plural(nf_count, "нефункціональна", "нефункціональні", "нефункціональних")
        + ", "
        + plural(bdd_count, "сценарій BDD", "сценарії BDD", "сценаріїв BDD")
        + ", "
        + plural(
            uc_count,
            "сценарій використання",
            "сценарії використання",
            "сценаріїв використання",
        )
        + "."
    )
    return (
        INTRO.format(totals=totals)
        + "\n## Функціональні вимоги\n\n"
        + TABLE_HEAD
        + rows("F")
        + "\n## Нефункціональні вимоги\n\n"
        + TABLE_HEAD
        + rows("NF")
        + "\n"
        + OUTRO
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    current = read(MATRIX_PATH)
    result = generate(read(SRS_PATH), read(OPENAPI_PATH), current)
    if "--check" in argv:
        if result != current:
            print("spec/traceability.md differs from the generated matrix")
            return 1
        return 0
    with MATRIX_PATH.open("w", encoding="utf-8", newline="\n") as f:
        f.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

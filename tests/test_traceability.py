"""The traceability matrix must match what the generator builds from the SRS."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tests" / "tools" / "generate_traceability.py"


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_traceability", GENERATOR_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matrix_matches_generated_output_byte_for_byte():
    gen = load_generator()
    current = gen.MATRIX_PATH.read_bytes()
    generated = gen.generate(
        gen.read(gen.SRS_PATH),
        gen.read(gen.OPENAPI_PATH),
        current.decode("utf-8"),
    ).encode("utf-8")
    assert generated == current


def test_ukrainian_plural_forms():
    gen = load_generator()
    assert gen.plural(71, "вимога", "вимоги", "вимог") == "71 вимога"
    assert gen.plural(33, "вимога", "вимоги", "вимог") == "33 вимоги"
    assert gen.plural(12, "вимога", "вимоги", "вимог") == "12 вимог"
    assert gen.plural(70, "вимога", "вимоги", "вимог") == "70 вимог"


def test_implementation_columns_from_cited_ids():
    gen = load_generator()
    links = {
        "test": gen.cite_map({"test_a.py": "# REQ-F-001, BDD-001", "test_b.py": ""}),
        "code": gen.cite_map({"spm/x.py": "REQ-F-001 REQ-F-001"}),
        "doc": {},
    }
    assert gen.implementation_cells("REQ-F-001", links) == [
        "`test_a.py`",
        "`spm/x.py`",
        "—",
    ]
    # Code that does not cite its requirement comes from CODE_EXTRA.
    assert gen.implementation_cells("REQ-F-071", links)[1] == "`spm/api/routes.py`"
    # A requirement checked otherwise gets its note; a citing test wins over it.
    assert gen.implementation_cells("REQ-NF-012", links)[:2] == [
        "історія git (правило розробки)",
        "історія git",
    ]
    links["test"]["REQ-NF-009"] = ["test_performance.py"]
    assert gen.implementation_cells("REQ-NF-009", links)[0] == "`test_performance.py`"


def test_scan_skips_tools_and_reads_contract_scenarios():
    gen = load_generator()
    tests = gen.scan_repository()["test"]
    cited = {name for names in tests.values() for name in names}
    assert "contract/scenarios.json" in cited
    assert not any(name.startswith("tools/") for name in cited)
    assert "REQ-NF-010" not in tests
    assert "test_traceability.py" not in cited

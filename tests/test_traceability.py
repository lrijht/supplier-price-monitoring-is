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

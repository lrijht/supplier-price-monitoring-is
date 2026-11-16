"""T-05: application skeleton and configuration (REQ-NF-011, REQ-NF-022, REQ-NF-025)."""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET_ENV = "SPM_SESSION_SECRET"
OPTIONAL_ENV = {
    "database_path": "SPM_DATABASE_PATH",
    "action_log_path": "SPM_ACTION_LOG_PATH",
    "technical_log_path": "SPM_TECHNICAL_LOG_PATH",
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


# REQ-NF-011: the dependency description names Python 3.12.
def test_dependencies_require_python_3_12():
    assert "3.12" in _pyproject()["project"]["requires-python"]


# REQ-NF-011: the dependency description names FastAPI.
def test_dependencies_include_fastapi():
    deps = _pyproject()["project"]["dependencies"]
    assert any(re.match(r"fastapi\b", d, re.IGNORECASE) for d in deps)


# REQ-NF-011: the dependency description names SQLite (stdlib sqlite3, so it is
# stated in the project metadata rather than as a package).
def test_project_description_names_sqlite():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "sqlite" in text.lower()


# REQ-NF-011: the system runs on Python 3.12 (the interpreter used for tests).
def test_tests_run_on_python_3_12():
    assert sys.version_info[:2] == (3, 12)


# REQ-NF-022, П-7: the session signing key is the only mandatory secret; it is
# read from the environment.
def test_load_config_reads_session_secret_from_environment(spm_config_module):
    cfg = spm_config_module.load_config({SECRET_ENV: "from-env"}, env_file=None)
    assert cfg.session_secret == "from-env"


# REQ-NF-022: the configuration may come from a .env file outside the repository.
def test_load_config_reads_env_file(spm_config_module, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{SECRET_ENV}=from-file\n", encoding="utf-8")
    cfg = spm_config_module.load_config({}, env_file=env_file)
    assert cfg.session_secret == "from-file"


# REQ-NF-022: an environment variable takes precedence over the .env file.
def test_environment_overrides_env_file(spm_config_module, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{SECRET_ENV}=from-file\n", encoding="utf-8")
    cfg = spm_config_module.load_config({SECRET_ENV: "from-env"}, env_file=env_file)
    assert cfg.session_secret == "from-env"


# REQ-NF-022: optional parameters (database and log files) are read by name.
def test_load_config_reads_optional_paths(spm_config_module, tmp_path: Path):
    environ = {SECRET_ENV: "s"}
    for field, name in OPTIONAL_ENV.items():
        environ[name] = str(tmp_path / f"{field}.x")
    cfg = spm_config_module.load_config(environ, env_file=None)
    for field in OPTIONAL_ENV:
        assert Path(getattr(cfg, field)) == tmp_path / f"{field}.x"


# REQ-NF-022: without the mandatory secret the configuration is rejected and the
# message names the missing parameter.
@pytest.mark.parametrize("environ", [{}, {SECRET_ENV: ""}, {SECRET_ENV: "   "}])
def test_missing_secret_is_rejected_with_parameter_name(spm_config_module, environ):
    with pytest.raises(spm_config_module.ConfigError) as excinfo:
        spm_config_module.load_config(environ, env_file=None)
    assert SECRET_ENV in str(excinfo.value)


# REQ-NF-022: the system does not start without the secret: create_app() reads
# the configuration itself and fails, naming the parameter.
def test_app_does_not_start_without_secret(
    spm_app_module, spm_config_module, monkeypatch, tmp_path: Path
):
    monkeypatch.delenv(SECRET_ENV, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env file here
    with pytest.raises(spm_config_module.ConfigError) as excinfo:
        spm_app_module.create_app()
    assert SECRET_ENV in str(excinfo.value)


# REQ-NF-022: with the secret in the environment create_app() builds the app.
def test_app_starts_with_secret_from_environment(
    spm_app_module, monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(SECRET_ENV, "from-env")
    for name in OPTIONAL_ENV.values():
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    assert spm_app_module.create_app() is not None


# REQ-NF-022: the file with secrets is listed in .gitignore.
def test_env_file_is_git_ignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8-sig").splitlines()
    assert ".env" in [line.strip() for line in lines]


def _repository_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


# REQ-NF-022: no .env file in the repository, and a search for the secret's
# parameter name finds no assigned value (placeholders like <...> are allowed).
def test_repository_has_no_secret_values():
    files = _repository_files()
    assert not [f for f in files if f.name == ".env"]
    assignment = re.compile(SECRET_ENV + r"\s*[=:]\s*([^\s<$]\S*)")
    offenders = []
    for path in files:
        if path.suffix in {".png", ".pdf", ".docx", ".ico"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if assignment.search(text):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


# REQ-NF-022: the system creates no accounts with default passwords: after the
# first start on an empty database no account exists.
def test_no_default_accounts_after_first_start(app, client, config):
    assert Path(config.database_path).exists()
    with sqlite3.connect(config.database_path) as db:
        tables = [
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        account_tables = [t for t in tables if "account" in t.lower()]
        assert account_tables, "the schema has an accounts table"
        for table in account_tables:
            assert db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0


# REQ-NF-025: code style checks pass for the whole repository.
@pytest.mark.parametrize(
    "args", [["format", "--check", "."], ["check", "."]], ids=["format", "lint"]
)
def test_ruff_reports_nothing(args):
    result = subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

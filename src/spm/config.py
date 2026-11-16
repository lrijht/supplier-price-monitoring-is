"""Start-up configuration (REQ-NF-022).

The configuration comes from environment variables or a ``.env`` file kept out
of the repository. It is read once, in ``spm.app.create_app``; the values are
then passed to the components as parameters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

SESSION_SECRET_ENV = "SPM_SESSION_SECRET"
DATABASE_PATH_ENV = "SPM_DATABASE_PATH"
ACTION_LOG_PATH_ENV = "SPM_ACTION_LOG_PATH"
TECHNICAL_LOG_PATH_ENV = "SPM_TECHNICAL_LOG_PATH"

# Defaults are relative to the working directory: the service is started from
# the repository root, and var/ is ignored by git.
DEFAULT_DATABASE_PATH = Path("var") / "spm.db"
DEFAULT_ACTION_LOG_PATH = Path("var") / "actions.log"
DEFAULT_TECHNICAL_LOG_PATH = Path("var") / "technical.log"


class ConfigError(Exception):
    """The start-up configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Config:
    # repr=False keeps the secret out of reprs, tracebacks and logs.
    session_secret: str = field(repr=False)
    database_path: Path
    action_log_path: Path
    technical_log_path: Path

    def __post_init__(self) -> None:
        for name in ("database_path", "action_log_path", "technical_log_path"):
            object.__setattr__(self, name, Path(getattr(self, name)))


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a ``NAME=value`` file; a missing file gives no values."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def _path(values: Mapping[str, str], name: str, default: Path) -> Path:
    value = values.get(name, "").strip()
    return Path(value) if value else default


def load_config(environ: Mapping[str, str], env_file: Path | None = None) -> Config:
    """Build the configuration; environment variables override the file."""
    values: dict[str, str] = {}
    if env_file is not None:
        values.update(read_env_file(env_file))
    values.update(environ)

    secret = values.get(SESSION_SECRET_ENV, "")
    if not secret.strip():
        raise ConfigError(
            f"Не задано обов'язковий параметр {SESSION_SECRET_ENV} "
            "(ключ підпису сесії): система не стартує без нього."
        )
    return Config(
        session_secret=secret,
        database_path=_path(values, DATABASE_PATH_ENV, DEFAULT_DATABASE_PATH),
        action_log_path=_path(values, ACTION_LOG_PATH_ENV, DEFAULT_ACTION_LOG_PATH),
        technical_log_path=_path(
            values, TECHNICAL_LOG_PATH_ENV, DEFAULT_TECHNICAL_LOG_PATH
        ),
    )

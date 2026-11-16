"""Set-up command: create an account (REQ-F-006).

Usage: ``python -m spm.auth.cli LOGIN ROLE``. The password is asked
interactively and is never an argument of the command.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

from spm.auth.service import (
    ROLES,
    AccountRefused,
    AuthService,
    login_taken_message,
    validate_new_account,
    validate_password,
)
from spm.clock import SystemClock
from spm.config import Config, ConfigError, load_config
from spm.logging import JsonLinesLog
from spm.storage import Database, init_database

PASSWORD_PROMPT = "Пароль: "
REPEAT_PROMPT = "Повторіть пароль: "


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m spm.auth.cli",
        description=(
            "Створює обліковий запис менеджера або адміністратора. "
            "Пароль запитується інтерактивно під час виконання."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "login",
        help="логін: латинські літери, цифри, крапка, підкреслення, дефіс; 3…32 символи",
    )
    parser.add_argument("role", help="роль: " + " або ".join(ROLES))
    return parser


def _refuse(message: str) -> int:
    print(f"Обліковий запис не створено. {message}", file=sys.stderr)
    return 1


def main(
    argv: list[str] | None = None,
    *,
    config: Config | None = None,
    read_password: Callable[[str], str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if read_password is None:
        read_password = getpass.getpass
    if config is None:
        try:
            config = load_config(os.environ, Path(".env"))
        except ConfigError as exc:
            return _refuse(str(exc))

    init_database(config.database_path)
    # The command runs outside any HTTP request, so its record has no request
    # identifier (REQ-NF-032).
    auth = AuthService(
        Database(config.database_path),
        SystemClock(),
        JsonLinesLog(config.action_log_path, SystemClock()),
        config.session_secret,
    )
    try:
        validate_new_account(args.login, args.role)
        if auth.login_exists(args.login):
            raise AccountRefused(login_taken_message(args.login))
        try:
            password = read_password(PASSWORD_PROMPT)
            validate_password(password)
            if read_password(REPEAT_PROMPT) != password:
                raise AccountRefused("Паролі не збігаються.")
        except (EOFError, KeyboardInterrupt):
            raise AccountRefused("Пароль не введено.") from None
        account = auth.create_account(args.login, args.role, password)
    except AccountRefused as exc:
        return _refuse(str(exc))
    print(f"Обліковий запис «{account.login}» з роллю {account.role} створено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

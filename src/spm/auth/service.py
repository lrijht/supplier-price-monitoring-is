"""Accounts, login, logout, sessions and roles (REQ-F-001…REQ-F-006, REQ-NF-021).

The session cookie carries a random token signed with the session secret; the
database keeps only a hash of the token, so neither the cookie value nor the
password reaches storage or the logs (REQ-NF-020, REQ-NF-032).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from spm.auth.passwords import hash_password, verify_against_nothing, verify_password
from spm.clock import Clock
from spm.logging import JsonLinesLog, set_request_account
from spm.storage import Database, repositories

SESSION_COOKIE = "spm_session"
SESSION_LIFETIME = timedelta(hours=8)  # REQ-NF-021
# Attributes of the session cookie for the web interface and the API alike.
# SameSite=Lax, no Secure: no HTTPS in the trusted local network (ЗП-4).
SESSION_COOKIE_MAX_AGE = int(SESSION_LIFETIME.total_seconds())
SESSION_COOKIE_SCOPE = {"path": "/", "httponly": True, "samesite": "lax"}
WRONG_CREDENTIALS = "Неправильний логін або пароль."

ROLES = ("manager", "admin")
ADMIN = "admin"
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,32}")
MIN_PASSWORD_LENGTH = 8


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    login: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN


class AccountRefused(Exception):
    """The set-up command refuses to create the account; the message says why."""


def validate_new_account(login: str, role: str) -> None:
    if not LOGIN_PATTERN.fullmatch(login):
        raise AccountRefused(
            "Логін має складатися з латинських літер, цифр, крапки, підкреслення "
            "чи дефіса і мати від 3 до 32 символів."
        )
    if role not in ROLES:
        raise AccountRefused(
            "Роль має бути manager (менеджер) або admin (адміністратор)."
        )


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountRefused(
            f"Пароль має містити не менше {MIN_PASSWORD_LENGTH} символів."
        )


def login_taken_message(login: str) -> str:
    return f"Обліковий запис з логіном «{login}» уже існує."


def _account(row: repositories.AccountRow) -> Account:
    return Account(row.id, row.login, row.role)


def _moment(value: datetime) -> str:
    return value.isoformat()


class AuthService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        action_log: JsonLinesLog,
        session_secret: str,
    ) -> None:
        self._db = database
        self._clock = clock
        self._log = action_log
        self._secret = session_secret.encode("utf-8")

    # --- accounts (REQ-F-006) ---------------------------------------------------------

    def login_exists(self, login: str) -> bool:
        with self._db.transaction() as conn:
            return repositories.find_account_by_login(conn, login) is not None

    def create_account(self, login: str, role: str, password: str) -> Account:
        """Create an account; raise AccountRefused and change nothing otherwise."""
        validate_new_account(login, role)
        validate_password(password)
        password_hash = hash_password(password)
        with self._db.transaction() as conn:
            if repositories.find_account_by_login(conn, login) is not None:
                raise AccountRefused(login_taken_message(login))
            account_id = repositories.insert_account(conn, login, role, password_hash)
        self._log.write(
            level="info",
            event="account_created",
            result="success",
            account_login=login,
            account_role=role,
        )
        return Account(account_id, login, role)

    # --- sessions -------------------------------------------------------------------------

    def _sign(self, token: str) -> str:
        return hmac.new(self._secret, token.encode("ascii"), hashlib.sha256).hexdigest()

    def _token_hash(self, cookie_value: str | None) -> str | None:
        """The stored hash of a well-signed cookie's token, otherwise None."""
        if not cookie_value or "." not in cookie_value:
            return None
        token, _, signature = cookie_value.rpartition(".")
        try:
            expected = self._sign(token)
        except UnicodeEncodeError:
            return None
        if not hmac.compare_digest(expected, signature):
            return None
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def login(self, login: str, password: str) -> tuple[Account, str] | None:
        """Open a session; return the account and the cookie value, or None."""
        with self._db.transaction() as conn:
            row = repositories.find_account_by_login(conn, login)
        if row is None:
            verify_against_nothing(password)
        if row is None or not verify_password(password, row.password_hash):
            self._log.write(
                level="warning",
                event="login_failed",
                result="rejected",
                entered_login=login,
            )
            return None
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self._db.transaction() as conn:
            repositories.insert_session(
                conn, token_hash, row.id, _moment(self._clock.now())
            )
        account = _account(row)
        set_request_account(account.login, account.role)
        self._log.write(
            level="info",
            event="login_succeeded",
            result="success",
            login=account.login,
            role=account.role,
        )
        return account, f"{token}.{self._sign(token)}"

    def resolve(self, cookie_value: str | None) -> Account | None:
        """The account of a live session; the request counts as activity.

        A session idle for 8 hours or more ends here, when it is detected
        (REQ-NF-021, REQ-NF-032).
        """
        token_hash = self._token_hash(cookie_value)
        if token_hash is None:
            return None
        now = self._clock.now()
        with self._db.transaction() as conn:
            session = repositories.find_session(conn, token_hash)
            if session is None:
                return None
            last_seen = datetime.fromisoformat(session.last_seen_at)
            expired = now - last_seen >= SESSION_LIFETIME
            if expired:
                repositories.delete_session(conn, session.id)
            else:
                repositories.touch_session(conn, session.id, _moment(now))
        account = _account(session.account)
        if expired:
            self._log.write(
                level="info",
                event="session_expired",
                result="success",
                login=account.login,
                role=account.role,
            )
            return None
        set_request_account(account.login, account.role)
        return account

    def logout(self, cookie_value: str | None) -> bool:
        """End the session of this cookie only (REQ-F-002)."""
        account = self.resolve(cookie_value)
        if account is None:
            return False
        token_hash = self._token_hash(cookie_value)
        with self._db.transaction() as conn:
            session = repositories.find_session(conn, token_hash)
            if session is not None:
                repositories.delete_session(conn, session.id)
        self._log.write(
            level="info",
            event="logout",
            result="success",
            login=account.login,
            role=account.role,
        )
        return True

    # --- roles (REQ-F-003…REQ-F-005) ------------------------------------------------------

    def deny(
        self,
        account: Account,
        *,
        action: str,
        object_type: str | None,
        object_id: int | None,
    ) -> None:
        """Record the refusal «немає доступу»: one record, no action record."""
        self._log.write(
            level="warning",
            event="access_denied",
            result="rejected",
            login=account.login,
            role=account.role,
            action=action,
            object_type=object_type,
            object_id=object_id,
        )

"""Removal of secrets from text that goes into the logs (Р-125).

Passwords, session cookie values and whole request bodies never reach a log,
also when an exception message or a stack trace carries them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl

MASK = "***"
# Shorter values would mask unrelated text; they carry no real secret anyway.
_MIN_SECRET_LENGTH = 4
_MAX_BODY_BYTES = 1024 * 1024

_PATTERNS = [
    # password=..., "password": "...", passwd: ...
    re.compile(
        r"(?i)((?:password|passwd|pwd)[\w-]*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;&}]+)"
    ),
    # cookie values: spm_session=...
    re.compile(r"(?i)(spm_session\s*=\s*)([^\s;,\"']+)"),
]


def _is_password_key(key: object) -> bool:
    return isinstance(key, str) and "password" in key.lower()


def _password_values(data: object) -> Iterable[str]:
    if isinstance(data, dict):
        for key, value in data.items():
            if _is_password_key(key) and isinstance(value, str):
                yield value
            else:
                yield from _password_values(value)
    elif isinstance(data, list):
        for value in data:
            yield from _password_values(value)


class SecretCollector:
    """Collects the secret values of one HTTP request."""

    def __init__(self, headers: Iterable[tuple[bytes, bytes]]) -> None:
        self._values: set[str] = set()
        self._body = bytearray()
        self._content_type = ""
        for name, value in headers:
            lname = name.lower()
            if lname == b"cookie":
                self._add_cookie_header(value.decode("latin-1"))
            elif lname == b"content-type":
                self._content_type = value.decode("latin-1").lower()
            elif lname == b"authorization":
                self._add(value.decode("latin-1"))

    def _add(self, value: str) -> None:
        value = value.strip()
        if len(value) >= _MIN_SECRET_LENGTH:
            self._values.add(value)

    def _add_cookie_header(self, header: str) -> None:
        for part in header.split(";"):
            _, _, value = part.partition("=")
            self._add(value.strip().strip('"'))

    def feed_body(self, chunk: bytes) -> None:
        room = _MAX_BODY_BYTES - len(self._body)
        if room > 0 and chunk:
            self._body.extend(chunk[:room])

    def _body_values(self) -> set[str]:
        values: set[str] = set()
        if not self._body:
            return values
        text = self._body.decode("utf-8", errors="replace")
        values.add(text)  # the whole body never goes to a log
        if "json" in self._content_type:
            try:
                values.update(_password_values(json.loads(text)))
            except ValueError:
                pass
        elif "x-www-form-urlencoded" in self._content_type:
            values.update(v for k, v in parse_qsl(text) if _is_password_key(k))
        return {v for v in values if len(v.strip()) >= _MIN_SECRET_LENGTH}

    def redact(self, text: str) -> str:
        secrets = self._values | self._body_values()
        # Longest first, so a value inside another value is masked too.
        for value in sorted(secrets, key=len, reverse=True):
            text = text.replace(value, MASK)
        for pattern in _PATTERNS:
            text = pattern.sub(lambda m: m.group(1) + MASK, text)
        return text

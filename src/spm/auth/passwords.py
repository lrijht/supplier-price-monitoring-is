"""Password hashes with salt (REQ-NF-020), standard library only.

Format: ``scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16
_HASH_BYTES = 32


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=128 * n * r * 2,
        dklen=_HASH_BYTES,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, bytes.fromhex(digest))


# Checked when the login is unknown, so that a wrong login and a wrong password
# take the same time.
_DUMMY_HASH: str | None = None


def verify_against_nothing(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(8))
    verify_password(password, _DUMMY_HASH)

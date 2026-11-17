"""Getting a catalogue page: one HTTP GET, no retry (REQ-NF-004, REQ-F-026).

``FETCH_TIMEOUT_SECONDS`` is read at the moment of the request, so the tests
replace it with 1 s (REQ-NF-013).
"""

from __future__ import annotations

import httpx

FETCH_TIMEOUT_SECONDS = 30

UNAVAILABLE = "unavailable"
TIMEOUT = "timeout"


class FetchError(Exception):
    """The page was not received: ``reason_code`` is ``unavailable`` or ``timeout``."""

    def __init__(self, reason_code: str, detail: str, timeout: float) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.timeout = timeout  # the timeout of this request, seconds


def fetch_page(url: str) -> str:
    """The page text; a non-2xx answer or a refused connection is "сторінка
    недоступна", no answer within the timeout is "перевищено час очікування"."""
    timeout = FETCH_TIMEOUT_SECONDS
    try:
        # trust_env=False: no proxy from the environment between the system and
        # the catalogue address.
        response = httpx.get(
            url, timeout=timeout, follow_redirects=True, trust_env=False
        )
    except httpx.TimeoutException as exc:
        raise FetchError(TIMEOUT, f"{type(exc).__name__}: {exc}", timeout) from None
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise FetchError(UNAVAILABLE, f"{type(exc).__name__}: {exc}", timeout) from None
    if not response.is_success:
        raise FetchError(UNAVAILABLE, f"HTTP {response.status_code}", timeout)
    return response.text

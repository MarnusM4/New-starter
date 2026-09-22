"""Retry with exponential backoff for transient HTTP failures.

Zoho Desk, Graph and ARM all return 429 (throttling) and occasional 5xx under load. Wrap the
network call in `with_retries` so transient errors are retried (honouring Retry-After)
and permanent ones (4xx other than 429) fail fast.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

import requests

T = TypeVar("T")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def with_retries(
    call: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `call`, retrying transient HTTP errors with exponential backoff.

    `call` should perform the request and call raise_for_status(). A retryable status or a
    connection error is retried; anything else propagates immediately.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return call()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in RETRYABLE_STATUS or attempt >= max_attempts:
                raise
            delay = _retry_after(exc) or min(base_delay * 2 ** (attempt - 1), max_delay)
            sleep(delay)
        except requests.ConnectionError:
            if attempt >= max_attempts:
                raise
            sleep(min(base_delay * 2 ** (attempt - 1), max_delay))


def _retry_after(exc: requests.HTTPError) -> float | None:
    if exc.response is None:
        return None
    value = exc.response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None

"""
Shared HTTP retry / backoff helpers for external API clients.

Both ``DexScreenerClient`` and ``HeliusClient`` use these helpers so that
transient ``429`` and ``5xx`` responses are retried automatically with
exponential backoff and jitter. After retries are exhausted, callers receive
an :class:`UpstreamUnavailable` exception so they can record an explicit
``data_unavailable`` risk_check row instead of silently producing a
misleading empty / "no risks found" analysis.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)


logger = logging.getLogger(__name__)


DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_MAX_WAIT_SECONDS = 30.0


class UpstreamUnavailable(Exception):
    """
    Raised when an external API is still failing after retries are exhausted.

    Callers should treat this as "data unavailable" — typically by recording
    a ``data_unavailable`` risk_check row rather than writing a misleading
    empty analysis. Distinguishing this from a non-retryable ``HTTPStatusError``
    (e.g. 404) lets the pipeline tell the difference between "endpoint says
    no data" and "we never reached the upstream".
    """


def is_retryable_http_error(exc: BaseException) -> bool:
    """
    Return True for transient errors worth retrying.

    Retryable:
        * ``429 Too Many Requests``
        * any ``5xx`` server error
        * timeouts and network errors

    Not retryable:
        * other ``4xx`` (the request itself is wrong; retrying won't help)
        * anything else
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or 500 <= status < 600

    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    ):
        return True

    return False


def build_async_retrying(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
) -> AsyncRetrying:
    """
    Configure :class:`tenacity.AsyncRetrying` for our retry semantics:
    up to ``max_attempts`` tries with random-exponential backoff (1s..max),
    retrying only on transient errors per :func:`is_retryable_http_error`.
    """
    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=1, max=max_wait_seconds),
        retry=retry_if_exception(is_retryable_http_error),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=False,
    )


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    **kwargs: Any,
) -> httpx.Response:
    """
    Issue ``client.request(method, url, **kwargs)`` with retry on 429/5xx and
    network errors.

    Raises:
        UpstreamUnavailable: All retries exhausted on a retryable error.
        httpx.HTTPStatusError: Non-retryable HTTP status (e.g. 404). Propagated
            unchanged so callers can distinguish "endpoint says no data" from
            "couldn't reach upstream".
    """
    try:
        async for attempt in build_async_retrying(
            max_attempts=max_attempts,
            max_wait_seconds=max_wait_seconds,
        ):
            with attempt:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
    except RetryError as exc:
        last = exc.last_attempt.exception() if exc.last_attempt else None
        raise UpstreamUnavailable(
            f"Upstream unavailable after retries: {method} {url} ({last!r})"
        ) from last

    # ``AsyncRetrying`` either returns from inside the loop or raises above.
    # This line is unreachable in practice; included for type-checker peace.
    raise UpstreamUnavailable(f"Unexpected retry termination for {method} {url}")

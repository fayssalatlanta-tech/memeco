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

import asyncio
import logging
import random
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
RETRY_AFTER_MAX_SECONDS = 30.0


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


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse the ``Retry-After`` header to a float of seconds.

    Helius and DexScreener both send this on 429 responses. Honoring it
    is far more effective than blind exponential backoff because it
    tells us exactly how long the upstream wants us to wait.

    Returns ``None`` when the header is absent or unparseable.
    """
    raw = response.headers.get("retry-after") if response is not None else None
    if not raw:
        return None
    try:
        return min(float(raw), RETRY_AFTER_MAX_SECONDS)
    except (TypeError, ValueError):
        return None


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

    Honors ``Retry-After`` on 429 responses — when the server tells us how
    long to wait we sleep for that long instead of using random backoff.
    A small jitter is added so that multiple concurrent retriers don't
    all fire at the same wall-clock instant.

    Raises:
        UpstreamUnavailable: All retries exhausted on a retryable error.
        httpx.HTTPStatusError: Non-retryable HTTP status (e.g. 404). Propagated
            unchanged so callers can distinguish "endpoint says no data" from
            "couldn't reach upstream".
    """
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if not is_retryable_http_error(exc) or attempt >= max_attempts:
                if not is_retryable_http_error(exc):
                    raise
                last_error = exc
                break
            last_error = exc
            wait_for = _retry_after_seconds(exc.response)
            if wait_for is None:
                # Random exponential fallback (similar shape to the old
                # tenacity-based retry) when no Retry-After hint exists.
                wait_for = min(max_wait_seconds, 0.5 * (2 ** (attempt - 1)))
            wait_for += random.uniform(0, 0.2)  # jitter so concurrent tasks don't sync
            logger.warning(
                "Retrying %s %s in %.2fs after %s (attempt %d/%d)",
                method, url, wait_for, exc.response.status_code,
                attempt, max_attempts,
            )
            await asyncio.sleep(wait_for)
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as exc:
            if attempt >= max_attempts:
                last_error = exc
                break
            last_error = exc
            wait_for = min(max_wait_seconds, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.2)
            logger.warning(
                "Retrying %s %s in %.2fs after %r (attempt %d/%d)",
                method, url, wait_for, exc, attempt, max_attempts,
            )
            await asyncio.sleep(wait_for)

    raise UpstreamUnavailable(
        f"Upstream unavailable after retries: {method} {url} ({last_error!r})"
    ) from last_error

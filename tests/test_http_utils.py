"""
Tests for the shared HTTP retry helper.

Verifies:
    * Retries kick in on 429 and 5xx responses, and we eventually succeed
      if the upstream recovers.
    * Non-retryable 4xx responses (e.g. 404) propagate as
      :class:`httpx.HTTPStatusError` immediately, without consuming the
      full retry budget.
    * Persistent retryable failures raise :class:`UpstreamUnavailable`
      after the retry budget is exhausted.
"""

import asyncio
import unittest
from typing import Any

import httpx

from app.http_utils import (
    UpstreamUnavailable,
    is_retryable_http_error,
    request_with_retry,
)


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code}",
        request=request,
        response=response,
    )


class IsRetryableHTTPErrorTests(unittest.TestCase):
    def test_429_is_retryable(self) -> None:
        self.assertTrue(is_retryable_http_error(_http_status_error(429)))

    def test_500_is_retryable(self) -> None:
        self.assertTrue(is_retryable_http_error(_http_status_error(503)))

    def test_404_is_not_retryable(self) -> None:
        self.assertFalse(is_retryable_http_error(_http_status_error(404)))

    def test_400_is_not_retryable(self) -> None:
        self.assertFalse(is_retryable_http_error(_http_status_error(400)))

    def test_timeout_is_retryable(self) -> None:
        self.assertTrue(
            is_retryable_http_error(httpx.ConnectTimeout("boom"))
        )

    def test_value_error_is_not_retryable(self) -> None:
        self.assertFalse(is_retryable_http_error(ValueError("nope")))


class _FakeAsyncClient:
    """
    Minimal stand-in for ``httpx.AsyncClient`` so ``request_with_retry``
    can be exercised without real network or sleeps.
    """

    def __init__(self, responses: list[Any]) -> None:
        # Each entry in ``responses`` is either an ``httpx.Response`` to
        # return or an ``Exception`` to raise.
        self._responses = list(responses)
        self.call_count = 0

    async def request(self, method: str, url: str, **_kwargs: Any) -> httpx.Response:
        self.call_count += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"ok": True},
        request=httpx.Request("GET", "https://example.test/"),
    )


def _status_response(code: int) -> httpx.Response:
    return httpx.Response(
        code,
        request=httpx.Request("GET", "https://example.test/"),
    )


class RequestWithRetryTests(unittest.TestCase):
    """End-to-end behavior tests for ``request_with_retry``."""

    def _run(self, coro):
        # No-op sleep so retries don't actually wait.
        async def runner():
            original_sleep = asyncio.sleep

            async def fast_sleep(_seconds: float) -> None:  # pragma: no cover
                await original_sleep(0)

            asyncio.sleep = fast_sleep  # type: ignore[assignment]
            try:
                return await coro
            finally:
                asyncio.sleep = original_sleep  # type: ignore[assignment]

        return asyncio.run(runner())

    def test_succeeds_on_first_try(self) -> None:
        client = _FakeAsyncClient([_ok_response()])
        response = self._run(
            request_with_retry(client, "GET", "https://example.test/")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.call_count, 1)

    def test_retries_429_then_succeeds(self) -> None:
        client = _FakeAsyncClient(
            [_status_response(429), _status_response(429), _ok_response()]
        )
        response = self._run(
            request_with_retry(client, "GET", "https://example.test/")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.call_count, 3)

    def test_retries_503_then_succeeds(self) -> None:
        client = _FakeAsyncClient(
            [_status_response(503), _ok_response()]
        )
        response = self._run(
            request_with_retry(client, "GET", "https://example.test/")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.call_count, 2)

    def test_404_is_not_retried(self) -> None:
        client = _FakeAsyncClient([_status_response(404)])
        with self.assertRaises(httpx.HTTPStatusError) as ctx:
            self._run(
                request_with_retry(client, "GET", "https://example.test/")
            )
        self.assertEqual(ctx.exception.response.status_code, 404)
        # Only one attempt: 4xx is non-retryable.
        self.assertEqual(client.call_count, 1)

    def test_persistent_429_raises_upstream_unavailable(self) -> None:
        client = _FakeAsyncClient([_status_response(429)] * 5)
        with self.assertRaises(UpstreamUnavailable):
            self._run(
                request_with_retry(
                    client,
                    "GET",
                    "https://example.test/",
                    max_attempts=3,
                )
            )
        self.assertEqual(client.call_count, 3)

    def test_persistent_timeout_raises_upstream_unavailable(self) -> None:
        client = _FakeAsyncClient(
            [httpx.ConnectTimeout("nope")] * 5
        )
        with self.assertRaises(UpstreamUnavailable):
            self._run(
                request_with_retry(
                    client,
                    "GET",
                    "https://example.test/",
                    max_attempts=2,
                )
            )
        self.assertEqual(client.call_count, 2)


if __name__ == "__main__":
    unittest.main()

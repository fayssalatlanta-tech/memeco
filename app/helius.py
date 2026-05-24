import asyncio
import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from app.http_utils import request_with_retry

load_dotenv()

logger = logging.getLogger(__name__)


class HeliusClient:
    """
    Helius HTTP / RPC client.

    Behavior:
        * One persistent ``httpx.AsyncClient`` is reused for the lifetime of
          the instance — TLS handshake + connection pooling is reused
          across many calls. Wallet manipulation, cluster, dev-flow and
          reverse-discovery services hammer this client; opening a fresh
          ``AsyncClient`` per call (the previous behavior) was a measurable
          tax.
        * Outgoing requests are rate-limited via a shared lock /
          ``min_request_interval_seconds`` (env
          ``HELIUS_MIN_REQUEST_INTERVAL_SECONDS``, default 0.1). Same shape
          as :class:`DexScreenerClient` for symmetry.
        * Transient failures (429 / 5xx / network / timeout) retry with
          exponential backoff + jitter via tenacity.
        * On persistent upstream failure, callers see
          :class:`UpstreamUnavailable` rather than getting silently empty
          lists. RPC errors returned in the JSON body still raise
          :class:`RuntimeError` as before.

    Use as an async context manager to ensure the underlying client is
    closed::

        async with HeliusClient() as client:
            ...
    """

    BASE_URL = "https://api-mainnet.helius-rpc.com"
    RPC_BASE_URL = "https://mainnet.helius-rpc.com"

    def __init__(self) -> None:
        self.api_key = os.getenv("HELIUS_API_KEY")
        self.timeout = httpx.Timeout(20.0)
        self.min_request_interval_seconds = float(
            os.getenv("HELIUS_MIN_REQUEST_INTERVAL_SECONDS", "0.1")
        )
        self._last_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ---- Connection lifecycle -------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> "HeliusClient":
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.aclose()

    # ---- Rate limiter & low-level request ------------------------------------

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_for = self.min_request_interval_seconds - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request_at = time.monotonic()

    def _require_api_key(self) -> str:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")
        return self.api_key

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        await self._wait_for_rate_limit()
        client = self._get_client()
        return await request_with_retry(client, method, url, **kwargs)

    # ---- REST endpoints -------------------------------------------------------

    async def get_address_transactions(
        self,
        address: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        api_key = self._require_api_key()
        url = f"{self.BASE_URL}/v0/addresses/{address}/transactions"
        params = {"api-key": api_key, "limit": limit}

        response = await self._request("GET", url, params=params)
        data = response.json()
        return data if isinstance(data, list) else []

    async def get_enhanced_transactions(
        self,
        signatures: list[str],
    ) -> list[dict[str, Any]]:
        if not signatures:
            return []

        api_key = self._require_api_key()
        url = f"{self.BASE_URL}/v0/transactions"
        params = {"api-key": api_key}
        payload = {"transactions": signatures[:100]}

        response = await self._request("POST", url, params=params, json=payload)
        data = response.json()
        return data if isinstance(data, list) else []

    async def get_webhooks(self) -> list[dict[str, Any]]:
        api_key = self._require_api_key()
        url = f"{self.BASE_URL}/v0/webhooks"
        params = {"api-key": api_key}

        response = await self._request("GET", url, params=params)
        data = response.json()
        return data if isinstance(data, list) else []

    async def create_webhook(
        self,
        webhook_url: str,
        account_addresses: list[str],
        transaction_types: list[str] | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        api_key = self._require_api_key()
        url = f"{self.BASE_URL}/v0/webhooks"
        params = {"api-key": api_key}
        payload: dict[str, Any] = {
            "webhookURL": webhook_url,
            "transactionTypes": transaction_types or ["SWAP"],
            "accountAddresses": account_addresses,
            "webhookType": "enhanced",
            "txnStatus": "success",
        }
        if auth_header:
            payload["authHeader"] = auth_header

        response = await self._request("POST", url, params=params, json=payload)
        return response.json()

    async def update_webhook(
        self,
        webhook_id: str,
        webhook_url: str,
        account_addresses: list[str],
        transaction_types: list[str] | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        api_key = self._require_api_key()
        url = f"{self.BASE_URL}/v0/webhooks/{webhook_id}"
        params = {"api-key": api_key}
        payload: dict[str, Any] = {
            "webhookURL": webhook_url,
            "transactionTypes": transaction_types or ["SWAP"],
            "accountAddresses": account_addresses,
            "webhookType": "enhanced",
            "txnStatus": "success",
        }
        if auth_header:
            payload["authHeader"] = auth_header

        response = await self._request("PUT", url, params=params, json=payload)
        return response.json()

    # ---- JSON-RPC -------------------------------------------------------------

    async def rpc(self, method: str, params: list[Any]) -> Any:
        api_key = self._require_api_key()
        url = f"{self.RPC_BASE_URL}/?api-key={api_key}"
        payload = {
            "jsonrpc": "2.0",
            "id": "quant-platform",
            "method": method,
            "params": params,
        }

        response = await self._request("POST", url, json=payload)
        data = response.json()

        if data.get("error"):
            raise RuntimeError(f"Helius RPC error for {method}: {data['error']}")

        return data.get("result")

    async def get_signatures_for_address(
        self,
        address: str,
        limit: int = 100,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        config: dict[str, Any] = {"limit": limit}
        if before:
            config["before"] = before

        result = await self.rpc("getSignaturesForAddress", [address, config])
        return result if isinstance(result, list) else []

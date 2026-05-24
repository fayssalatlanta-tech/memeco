import asyncio
import logging
import math
import os
import time
from typing import Any

import httpx

from app.http_utils import UpstreamUnavailable, request_with_retry

logger = logging.getLogger(__name__)


BONDING_DEX_IDS = {"pumpfun"}

LATEST_SOURCE_ENDPOINTS = {
    "profile": "/token-profiles/latest/v1",
    "community_takeover": "/community-takeovers/latest/v1",
    "ad": "/ads/latest/v1",
    "boost_latest": "/token-boosts/latest/v1",
    "boost_top": "/token-boosts/top/v1",
}


def safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def is_bonding_pair(pair: dict[str, Any]) -> bool:
    return str(pair.get("dexId") or "").lower() in BONDING_DEX_IDS


def pair_activity_score(pair: dict[str, Any]) -> float:
    txns = pair.get("txns") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}

    h1_txns = safe_int((txns.get("h1") or {}).get("buys")) + safe_int((txns.get("h1") or {}).get("sells"))
    h24_txns = safe_int((txns.get("h24") or {}).get("buys")) + safe_int((txns.get("h24") or {}).get("sells"))
    liquidity_usd = safe_float(liquidity.get("usd"))
    volume_h1 = safe_float(volume.get("h1"))
    volume_h24 = safe_float(volume.get("h24"))

    return (
        math.log10(liquidity_usd + 1) * 12
        + math.log10(volume_h1 + 1) * 8
        + math.log10(volume_h24 + 1) * 4
        + h1_txns * 0.4
        + h24_txns * 0.02
    )


def preferred_pair_score(pair: dict[str, Any]) -> tuple[float, int, float]:
    pair_created_at = safe_int(pair.get("pairCreatedAt"))
    non_bonding_bonus = 1_000_000 if not is_bonding_pair(pair) else 0
    recency_bonus = pair_created_at / 1_000_000_000

    return (
        non_bonding_bonus + recency_bonus + pair_activity_score(pair),
        pair_created_at,
        safe_float((pair.get("liquidity") or {}).get("usd")),
    )


def select_preferred_pair(pairs: list[dict[str, Any]], chain_id: str) -> dict[str, Any] | None:
    valid_pairs = [
        pair
        for pair in pairs
        if pair.get("chainId") == chain_id
        and not is_bonding_pair(pair)
    ]

    if not valid_pairs:
        return None

    return max(valid_pairs, key=preferred_pair_score)


def normalize_latest_candidate(item: dict[str, Any], source: str) -> dict[str, Any] | None:
    token_address = item.get("tokenAddress")
    chain_id = item.get("chainId")
    if not token_address or not chain_id:
        return None

    candidate = dict(item)
    candidate["_source"] = source
    candidate["_source_endpoint"] = LATEST_SOURCE_ENDPOINTS.get(source, "/token-profiles/latest/v1")
    return candidate


def dedupe_latest_candidates(
    source_items: list[tuple[str, list[dict[str, Any]]]],
    chain_id: str = "solana",
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    for source, items in source_items:
        for item in items:
            candidate = normalize_latest_candidate(item, source)
            if not candidate or candidate.get("chainId") != chain_id:
                continue

            token_address = candidate["tokenAddress"]
            existing = candidates.get(token_address)
            if not existing:
                candidate["_sources"] = [source]
                candidates[token_address] = candidate
                continue

            sources = existing.setdefault("_sources", [])
            if source not in sources:
                sources.append(source)

            if not existing.get("icon") and candidate.get("icon"):
                existing["icon"] = candidate["icon"]
            if not existing.get("description") and candidate.get("description"):
                existing["description"] = candidate["description"]
            if not existing.get("links") and candidate.get("links"):
                existing["links"] = candidate["links"]

    return list(candidates.values())


def sort_discovered_pairs_by_recency(
    discovered: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return sorted(
        discovered,
        key=lambda item: (
            safe_int(item[1].get("pairCreatedAt")),
            pair_activity_score(item[1]),
        ),
        reverse=True,
    )


class DexScreenerClient:
    """
    DexScreener HTTP client.

    Behavior:
        * One persistent ``httpx.AsyncClient`` is reused for the lifetime of
          the instance (TLS handshake reused across calls).
        * Requests are rate-limited to no more than one every
          ``DEXSCREENER_MIN_REQUEST_INTERVAL_SECONDS`` seconds (default 0.35).
        * Transient failures (429 / 5xx / network / timeout) are retried
          automatically with exponential backoff + jitter.
        * On persistent upstream failure, public methods log loudly and
          return their natural empty value (``[]`` / ``{}`` / ``None``)
          to preserve current call-site semantics. Callers that need to
          distinguish "no data" from "upstream broken" can use the
          ``_strict`` variants which raise :class:`UpstreamUnavailable`.

    Use as an async context manager to ensure the underlying client is
    closed::

        async with DexScreenerClient() as client:
            ...
    """

    BASE_URL = "https://api.dexscreener.com"

    def __init__(self) -> None:
        self.timeout = httpx.Timeout(10.0)
        self.min_request_interval_seconds = float(
            os.getenv("DEXSCREENER_MIN_REQUEST_INTERVAL_SECONDS", "0.35")
        )
        self._last_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "QuantIntelligencePlatform/1.0",
        }
        self._client: httpx.AsyncClient | None = None

    # ---- Connection lifecycle -------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> "DexScreenerClient":
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.aclose()

    # ---- Rate limiter & low-level GET ----------------------------------------

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_for = self.min_request_interval_seconds - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request_at = time.monotonic()

    async def _get_json(self, url: str) -> Any:
        """
        Issue a rate-limited, retried GET. Raises :class:`UpstreamUnavailable`
        on persistent failure. Non-retryable HTTP errors (e.g. 404) propagate
        as :class:`httpx.HTTPStatusError`.
        """
        await self._wait_for_rate_limit()
        client = self._get_client()
        response = await request_with_retry(client, "GET", url)
        return response.json()

    # ---- Public API (back-compat: log + empty on failure) --------------------

    async def get_latest_profiles(self) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}/token-profiles/latest/v1"
        return await self._safe_get_list(url, "latest profiles")

    async def get_latest_community_takeovers(self) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}{LATEST_SOURCE_ENDPOINTS['community_takeover']}"
        return await self._safe_get_list(url, "community takeovers")

    async def get_latest_ads(self) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}{LATEST_SOURCE_ENDPOINTS['ad']}"
        return await self._safe_get_list(url, "latest ads")

    async def get_latest_boosted_tokens(self) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}{LATEST_SOURCE_ENDPOINTS['boost_latest']}"
        return await self._safe_get_list(url, "latest boosts")

    async def get_top_boosted_tokens(self) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}{LATEST_SOURCE_ENDPOINTS['boost_top']}"
        return await self._safe_get_list(url, "top boosts")

    async def get_token_pairs(
        self,
        chain_id: str,
        token_address: str,
    ) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}/token-pairs/v1/{chain_id}/{token_address}"
        return await self._safe_get_list(url, f"token pairs ({token_address})")

    async def get_tokens(
        self,
        chain_id: str,
        token_addresses: list[str],
    ) -> list[dict[str, Any]]:
        cleaned = [address for address in token_addresses if address]
        if not cleaned:
            return []

        url = f"{self.BASE_URL}/tokens/v1/{chain_id}/{','.join(cleaned[:30])}"
        return await self._safe_get_list(url, f"token batch ({len(cleaned)})")

    async def get_token_orders(
        self,
        chain_id: str,
        token_address: str,
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}/orders/v1/{chain_id}/{token_address}"
        try:
            data = await self._get_json(url)
        except UpstreamUnavailable as exc:
            logger.error("DexScreener orders upstream unavailable for %s: %s", token_address, exc)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "DexScreener orders HTTP %d for %s",
                exc.response.status_code,
                token_address,
            )
            return {}

        if isinstance(data, dict):
            return data

        logger.warning("Unexpected token orders response format for %s", token_address)
        return {}

    async def get_preferred_token_pair(
        self,
        chain_id: str,
        token_address: str,
    ) -> dict[str, Any] | None:
        pairs = await self.get_token_pairs(chain_id, token_address)
        if not pairs:
            return None
        return select_preferred_pair(pairs, chain_id)

    async def get_best_pair_by_liquidity(
        self,
        chain_id: str,
        token_address: str,
    ) -> dict[str, Any] | None:
        return await self.get_preferred_token_pair(chain_id, token_address)

    # ---- Strict variants (raise UpstreamUnavailable) -------------------------

    async def get_token_pairs_strict(
        self,
        chain_id: str,
        token_address: str,
    ) -> list[dict[str, Any]]:
        """
        Like :meth:`get_token_pairs` but raises :class:`UpstreamUnavailable`
        on persistent failure instead of swallowing it as ``[]``. Use this
        when callers need to distinguish "no pairs" from "couldn't reach
        DexScreener" (e.g. to record a ``data_unavailable`` risk_check).
        """
        url = f"{self.BASE_URL}/token-pairs/v1/{chain_id}/{token_address}"
        data = await self._get_json(url)  # may raise UpstreamUnavailable
        return data if isinstance(data, list) else []

    async def get_preferred_token_pair_strict(
        self,
        chain_id: str,
        token_address: str,
    ) -> dict[str, Any] | None:
        pairs = await self.get_token_pairs_strict(chain_id, token_address)
        if not pairs:
            return None
        return select_preferred_pair(pairs, chain_id)

    # ---- Internals -----------------------------------------------------------

    async def _safe_get_list(self, url: str, label: str) -> list[dict[str, Any]]:
        try:
            data = await self._get_json(url)
        except UpstreamUnavailable as exc:
            logger.error("DexScreener upstream unavailable for %s: %s", label, exc)
            return []
        except httpx.HTTPStatusError as exc:
            logger.error("DexScreener %s HTTP %d", label, exc.response.status_code)
            return []

        if isinstance(data, list):
            return data

        logger.warning("Unexpected %s response format", label)
        return []

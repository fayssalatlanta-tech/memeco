from __future__ import annotations

from decimal import Decimal
from typing import Any

import asyncpg

try:
    from dexscreener import DexScreenerClient, safe_float
except ModuleNotFoundError:
    from app.dexscreener import DexScreenerClient, safe_float


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


async def fetch_tracked_tokens(pool: asyncpg.Pool, limit: int = 300) -> list[str]:
    sql = """
    SELECT DISTINCT token_address
    FROM whale_performance_tracking
    WHERE token_address IS NOT NULL
    ORDER BY token_address
    LIMIT $1;
    """
    async with pool.acquire() as conn:
        return [row["token_address"] for row in await conn.fetch(sql, limit)]


async def refresh_whale_trade_prices(pool: asyncpg.Pool, limit: int = 300) -> dict[str, Any]:
    token_addresses = await fetch_tracked_tokens(pool, limit=limit)
    client = DexScreenerClient()
    refreshed = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for idx in range(0, len(token_addresses), 30):
                pairs = await client.get_tokens("solana", token_addresses[idx : idx + 30])
                for pair in pairs:
                    base_address = (pair.get("baseToken") or {}).get("address")
                    if not base_address:
                        continue
                    price_usd = safe_float(pair.get("priceUsd")) or None
                    price_native = safe_float(pair.get("priceNative")) or None
                    if not price_native:
                        continue

                    await conn.execute(
                        """
                        UPDATE whale_performance_tracking
                        SET current_price_usd = $2,
                            current_price_native = $3,
                            current_value_sol = GREATEST(
                                COALESCE((raw_json->>'net_token_amount')::numeric, 0),
                                0
                            ) * $3,
                            current_unrealized_pnl_sol = (
                                COALESCE(native_received_sol, 0)
                                + (
                                    GREATEST(
                                        COALESCE((raw_json->>'net_token_amount')::numeric, 0),
                                        0
                                    ) * $3
                                )
                                - COALESCE(native_spent_sol, 0)
                            ),
                            price_refreshed_at = NOW()
                        WHERE token_address = $1;
                        """,
                        base_address,
                        _decimal_or_none(price_usd),
                        _decimal_or_none(price_native),
                    )
                    refreshed += 1

    return {
        "tracked_tokens": len(token_addresses),
        "dexscreener_batches": (len(token_addresses) + 29) // 30,
        "tokens_refreshed": refreshed,
    }

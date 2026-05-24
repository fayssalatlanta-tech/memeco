import asyncpg
from validation import require_keys

async def upsert_token_price(pool: asyncpg.Pool, price_data: dict) -> dict:
    require_keys(
        price_data,
        ["time", "pair_id"],
        context="price_data",
    )

   
    sql = """
    INSERT INTO token_prices (
        time,
        pair_id,
        price_usd,
        price_native,
        liquidity_usd,
        volume_5m_usd,
        volume_1h_usd,
        volume_6h_usd,
        volume_24h_usd,
        buys_5m,
        sells_5m,
        buys_1h,
        sells_1h,
        buys_24h,
        sells_24h,
        market_cap_usd,
        fdv_usd,
        source
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9,
        $10, $11, $12, $13, $14, $15, $16, $17, $18
    )
    ON CONFLICT (time, pair_id)
    DO UPDATE SET
        price_usd = EXCLUDED.price_usd,
        price_native = EXCLUDED.price_native,
        liquidity_usd = EXCLUDED.liquidity_usd,
        volume_5m_usd = EXCLUDED.volume_5m_usd,
        volume_1h_usd = EXCLUDED.volume_1h_usd,
        volume_6h_usd = EXCLUDED.volume_6h_usd,
        volume_24h_usd = EXCLUDED.volume_24h_usd,
        buys_5m = EXCLUDED.buys_5m,
        sells_5m = EXCLUDED.sells_5m,
        buys_1h = EXCLUDED.buys_1h,
        sells_1h = EXCLUDED.sells_1h,
        buys_24h = EXCLUDED.buys_24h,
        sells_24h = EXCLUDED.sells_24h,
        market_cap_usd = EXCLUDED.market_cap_usd,
        fdv_usd = EXCLUDED.fdv_usd,
        source = EXCLUDED.source
    RETURNING *;
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            price_data["time"],
            price_data["pair_id"],
            price_data["price_usd"],
            price_data["price_native"],
            price_data["liquidity_usd"],
            price_data["volume_5m_usd"],
            price_data["volume_1h_usd"],
            price_data["volume_6h_usd"],
            price_data["volume_24h_usd"],
            price_data["buys_5m"],
            price_data["sells_5m"],
            price_data["buys_1h"],
            price_data["sells_1h"],
            price_data["buys_24h"],
            price_data["sells_24h"],
            price_data["market_cap_usd"],
            price_data["fdv_usd"],
            price_data["source"],
        )

    return dict(row)
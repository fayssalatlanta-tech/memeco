import asyncpg
from app.validation import require_keys

async def upsert_token_pair(pool: asyncpg.Pool, pair_data: dict) -> dict:
    sql = """
    INSERT INTO token_pairs (
        token_id,
        chain,
        pair_address,
        base_token_address,
        quote_token_address,
        quote_token_symbol,
        dex_id,
        url,
        pair_created_at,
        is_primary
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10
    )
    ON CONFLICT (chain, pair_address)
    DO UPDATE SET
        token_id = EXCLUDED.token_id,
        base_token_address = EXCLUDED.base_token_address,
        quote_token_address = EXCLUDED.quote_token_address,
        quote_token_symbol = EXCLUDED.quote_token_symbol,
        dex_id = EXCLUDED.dex_id,
        url = EXCLUDED.url,
        pair_created_at = EXCLUDED.pair_created_at,
        is_primary = EXCLUDED.is_primary,
        last_seen_at = NOW()
    RETURNING *;
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            pair_data["token_id"],
            pair_data["chain"],
            pair_data["pair_address"],
            pair_data["base_token_address"],
            pair_data["quote_token_address"],
            pair_data["quote_token_symbol"],
            pair_data["dex_id"],
            pair_data["url"],
            pair_data["pair_created_at"],
            pair_data["is_primary"],
        )

    return dict(row)
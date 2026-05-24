import asyncpg
from app.validation import require_keys

async def upsert_token(pool: asyncpg.Pool, token: dict) -> dict:
    require_keys(
    token,
    ["chain", "address"],
    context="token",
)
    sql = """
    INSERT INTO tokens (
        chain,
        address,
        symbol,
        name,
        decimals,
        source,
        creator_address
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7
    )
    ON CONFLICT (chain, address)
    DO UPDATE SET
        symbol = EXCLUDED.symbol,
        name = EXCLUDED.name,
        decimals = EXCLUDED.decimals,
        source = EXCLUDED.source,
        creator_address = EXCLUDED.creator_address,
        last_seen_at = NOW(),
        is_active = TRUE
    RETURNING
        id,
        chain,
        address,
        symbol,
        name,
        decimals,
        source,
        creator_address,
        first_seen_at,
        last_seen_at;
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            token["chain"],
            token["address"],
            token["symbol"],
            token["name"],
            token["decimals"],
            token["source"],
            token["creator_address"],
        )

    return dict(row)
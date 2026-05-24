import json

import asyncpg


async def start_ingestion_run(pool: asyncpg.Pool, source: str) -> int:
    sql = """
    INSERT INTO ingestion_runs (source, status, started_at)
    VALUES ($1, 'running', NOW())
    RETURNING id;
    """

    async with pool.acquire() as conn:
        return await conn.fetchval(sql, source)


async def finish_ingestion_run(
    pool: asyncpg.Pool,
    run_id: int,
    status: str,
    tokens_found: int,
    tokens_saved: int,
    pairs_saved: int,
    prices_saved: int,
    errors_count: int,
    error_message: str | None = None,
) -> None:
    sql = """
    UPDATE ingestion_runs
    SET status = $1,
        finished_at = NOW(),
        tokens_found = $2,
        tokens_saved = $3,
        pairs_saved = $4,
        prices_saved = $5,
        errors_count = $6,
        error_message = $7
    WHERE id = $8;
    """

    async with pool.acquire() as conn:
        await conn.execute(
            sql,
            status,
            tokens_found,
            tokens_saved,
            pairs_saved,
            prices_saved,
            errors_count,
            error_message,
            run_id,
        )


async def save_raw_snapshot(
    pool: asyncpg.Pool,
    run_id: int,
    source: str,
    endpoint: str,
    chain: str | None,
    token_address: str | None,
    pair_address: str | None,
    raw_json: dict,
) -> None:
    sql = """
    INSERT INTO raw_api_snapshots (
        run_id,
        source,
        endpoint,
        chain,
        token_address,
        pair_address,
        raw_json
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb);
    """

    async with pool.acquire() as conn:
        await conn.execute(
            sql,
            run_id,
            source,
            endpoint,
            chain,
            token_address,
            pair_address,
            json.dumps(raw_json),
        )

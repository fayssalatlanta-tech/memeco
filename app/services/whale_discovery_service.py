import json
from collections import defaultdict
from typing import Any

import asyncpg

from app.whale_scoring_logic import WhaleTrade, classify_elite_wallet, summarize_whale_trades

MIN_PROFIT_SOL_FOR_DISCOVERY = 10.0


def parse_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def trade_from_wallet_row(row: dict[str, Any]) -> WhaleTrade | None:
    details = parse_json(row.get("details"), {})
    early_buyer = details.get("early_buyer") or {}
    native_spent = float(early_buyer.get("native_spent") or 0)
    pnl_sol = early_buyer.get("realized_pnl_native")
    roi = early_buyer.get("realized_roi")
    seconds_from_launch = row.get("seconds_from_launch")

    if native_spent <= 0:
        return None

    return WhaleTrade(
        amount_sol=native_spent,
        pnl_sol=float(pnl_sol) if pnl_sol is not None else None,
        roi_percent=float(roi) * 100 if roi is not None else None,
        minutes_after_launch=(
            float(seconds_from_launch) / 60
            if seconds_from_launch is not None
            else None
        ),
        tx_per_minute=float(details.get("tx_per_minute") or 0),
    )


async def fetch_wallet_trade_rows(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        wi.wallet_address,
        wi.token_id,
        wi.pair_id,
        wi.first_entry_at,
        wi.seconds_from_launch,
        wi.details,
        t.address AS token_address,
        t.symbol AS token_symbol
    FROM wallet_intelligence_results wi
    JOIN tokens t
        ON t.id = wi.token_id
    WHERE wi.first_entry_at IS NOT NULL
      AND wi.details ? 'early_buyer';
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [dict(row) for row in rows]


async def upsert_elite_wallet(
    conn: asyncpg.Connection,
    wallet_address: str,
    summary: dict[str, Any],
    label: str,
    source: str = "wallet_intelligence",
) -> int:
    sql = """
    INSERT INTO elite_wallets (
        wallet_address,
        label,
        total_profit_sol,
        total_profit_30d_sol,
        win_rate_percent,
        avg_roi_percent,
        avg_minutes_after_launch,
        trade_count,
        profitable_trade_count,
        reliability_score,
        bot_flag,
        status,
        source,
        details,
        last_scored_at
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
        CASE WHEN $11 THEN 'EXCLUDED' ELSE 'WATCHING' END,
        $13,
        $12::jsonb,
        NOW()
    )
    ON CONFLICT (wallet_address) DO UPDATE
    SET label = EXCLUDED.label,
        total_profit_sol = EXCLUDED.total_profit_sol,
        total_profit_30d_sol = EXCLUDED.total_profit_30d_sol,
        win_rate_percent = EXCLUDED.win_rate_percent,
        avg_roi_percent = EXCLUDED.avg_roi_percent,
        avg_minutes_after_launch = EXCLUDED.avg_minutes_after_launch,
        trade_count = EXCLUDED.trade_count,
        profitable_trade_count = EXCLUDED.profitable_trade_count,
        reliability_score = EXCLUDED.reliability_score,
        bot_flag = EXCLUDED.bot_flag,
        status = EXCLUDED.status,
        source = EXCLUDED.source,
        details = EXCLUDED.details,
        last_scored_at = NOW()
    RETURNING id;
    """

    return await conn.fetchval(
        sql,
        wallet_address,
        label,
        summary["total_profit_sol"],
        summary["total_profit_30d_sol"],
        summary["win_rate_percent"],
        summary["avg_roi_percent"],
        summary["avg_minutes_after_launch"],
        summary["trade_count"],
        summary["profitable_trade_count"],
        summary["reliability_score"],
        summary["bot_flag"],
        json.dumps(summary),
        source,
    )


async def upsert_performance_row(
    conn: asyncpg.Connection,
    elite_wallet_id: int,
    row: dict[str, Any],
) -> None:
    details = parse_json(row.get("details"), {})
    early_buyer = details.get("early_buyer") or {}
    roi = early_buyer.get("realized_roi")
    seconds_from_launch = row.get("seconds_from_launch")

    sql = """
    INSERT INTO whale_performance_tracking (
        elite_wallet_id,
        wallet_address,
        token_id,
        pair_id,
        token_address,
        token_symbol,
        entry_at,
        exit_at,
        minutes_after_launch,
        native_spent_sol,
        native_received_sol,
        pnl_sol,
        roi_percent,
        trade_status,
        source,
        raw_json
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, ($8::jsonb->>'first_exit_at')::timestamptz,
        $9, $10, $11, $12, $13, $14, 'wallet_intelligence', $8::jsonb
    )
    ON CONFLICT (wallet_address, token_address, source) DO UPDATE
    SET elite_wallet_id = EXCLUDED.elite_wallet_id,
        token_id = EXCLUDED.token_id,
        pair_id = EXCLUDED.pair_id,
        token_symbol = EXCLUDED.token_symbol,
        entry_at = EXCLUDED.entry_at,
        exit_at = EXCLUDED.exit_at,
        minutes_after_launch = EXCLUDED.minutes_after_launch,
        native_spent_sol = EXCLUDED.native_spent_sol,
        native_received_sol = EXCLUDED.native_received_sol,
        pnl_sol = EXCLUDED.pnl_sol,
        roi_percent = EXCLUDED.roi_percent,
        trade_status = EXCLUDED.trade_status,
        raw_json = EXCLUDED.raw_json;
    """

    await conn.execute(
        sql,
        elite_wallet_id,
        row["wallet_address"],
        row.get("token_id"),
        row.get("pair_id"),
        row.get("token_address"),
        row.get("token_symbol"),
        row.get("first_entry_at"),
        json.dumps(details, default=str),
        float(seconds_from_launch) / 60 if seconds_from_launch is not None else None,
        float(early_buyer.get("native_spent") or 0),
        float(early_buyer.get("native_received") or 0),
        early_buyer.get("realized_pnl_native"),
        float(roi) * 100 if roi is not None else None,
        early_buyer.get("status") or "OBSERVED",
    )


async def run_whale_discovery_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await fetch_wallet_trade_rows(pool)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        grouped[row["wallet_address"]].append(row)

    saved = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for wallet_address, wallet_rows in grouped.items():
                trades = [
                    trade
                    for trade in (trade_from_wallet_row(row) for row in wallet_rows)
                    if trade is not None
                ]
                summary = summarize_whale_trades(trades)
                label = classify_elite_wallet(summary)

                if (
                    summary["total_profit_sol"] < MIN_PROFIT_SOL_FOR_DISCOVERY
                    and label != "ELITE_SMART_MONEY"
                ):
                    continue

                elite_wallet_id = await upsert_elite_wallet(conn, wallet_address, summary, label)

                for row in wallet_rows:
                    await upsert_performance_row(conn, elite_wallet_id, row)

                saved.append(
                    {
                        "wallet_address": wallet_address,
                        "elite_wallet_id": elite_wallet_id,
                        "label": label,
                        **summary,
                    }
                )

    return saved

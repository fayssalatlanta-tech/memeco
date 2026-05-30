import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncio
import asyncpg
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app.db import create_pool
from app.dexscreener import DexScreenerClient
from app.helius import HeliusClient
from app.jobs.scan_state import get_scan_state, subscribe, unsubscribe
from app.jobs.workers import (
    is_valid_solana_address,
    start_manual_token_job,
    start_scan_job,
    whale_signal_token_worker,
)
from app.services.whale_consistency_auditor_service import run_whale_consistency_audit
from app.services.whale_price_refresh_service import refresh_whale_trade_prices
from app.services.whale_signal_service import save_live_whale_signal
from app.services.whale_survival_service import run_whale_survival_service
from app.services.whale_webhook_service import sync_whale_webhook

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
WEB_DIST_DIR = APP_DIR.parent / "web" / "dist"

NOISE_TOKEN_ADDRESSES = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


def json_default(value):
    return str(value)


async def fetch_summary(pool: asyncpg.Pool) -> dict:
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH latest_decisions AS (
                    SELECT DISTINCT ON (token_id)
                        final_watchlist_status,
                        final_watchlist_pass
                    FROM watchlist_decisions
                    ORDER BY token_id, run_id DESC, created_at DESC, id DESC
                )
                SELECT
                    final_watchlist_status,
                    final_watchlist_pass,
                    COUNT(*) AS count
                FROM latest_decisions
                GROUP BY final_watchlist_status, final_watchlist_pass
                ORDER BY count DESC;
                """
            )

            latest_run = await conn.fetchrow(
                """
                SELECT
                    id,
                    source,
                    status,
                    tokens_found,
                    tokens_saved,
                    pairs_saved,
                    prices_saved,
                    errors_count,
                    started_at,
                    finished_at
                FROM ingestion_runs
                ORDER BY id DESC
                LIMIT 1;
                """
            )

            unique_tokens = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT token_id)
                FROM watchlist_decisions;
                """
            )

        return {
            "counts": [dict(row) for row in rows],
            "latest_run": dict(latest_run) if latest_run else None,
            "unique_tokens": unique_tokens or 0,
        }
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def fetch_watchlist(pool: asyncpg.Pool, status: str | None, limit: int) -> list[dict]:
    try:
        where_conditions = ["LOWER(COALESCE(p.dex_id, '')) <> 'pumpfun'"]
        params: list[Any] = [limit]

        # ``status`` accepts a single value ("WATCHLIST_PASS") or a
        # comma-separated list ("WATCHLIST_PASS,WATCHLIST_PASS_HIGH_RISK")
        # so the dashboard filter chips can multi-select. Empty / missing
        # means "no status filter".
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if statuses:
                where_conditions.append(
                    "latest_wd.final_watchlist_status = ANY($2::text[])"
                )
                params.append(statuses)

        where = "WHERE " + " AND ".join(where_conditions)

        sql = f"""
            WITH latest_wd AS (
                SELECT DISTINCT ON (token_id)
                    *
                FROM watchlist_decisions
                ORDER BY token_id, run_id DESC, created_at DESC, id DESC
            )
            SELECT
                latest_wd.id,
                latest_wd.run_id,
                latest_wd.token_id,
                latest_wd.pair_id,
                t.symbol,
                t.name,
                t.address AS token_address,
                p.dex_id,
                p.pair_created_at,
                first_profile.first_seen_at AS dexscreener_first_seen_at,
                CASE
                    WHEN p.pair_created_at IS NULL THEN NULL
                    ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - p.pair_created_at)) / 60, 2)
                END AS pair_age_minutes,
                CASE
                    WHEN first_profile.first_seen_at IS NULL THEN NULL
                    ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - first_profile.first_seen_at)) / 60, 2)
                END AS dexscreener_age_minutes,
                CASE
                    WHEN p.pair_created_at IS NULL THEN 'NOT_ON_DEX'
                    WHEN LOWER(COALESCE(p.dex_id, '')) = 'pumpfun' THEN 'PUMPFUN_BONDING'
                    ELSE 'DEX_LISTED'
                END AS bonding_curve_status,
                NULL::numeric AS bonding_curve_progress,
                COALESCE(pair_ads.active_boosts, 0) AS dex_active_boosts,
                COALESCE(order_ads.paid_order_count, 0) AS dex_paid_order_count,
                COALESCE(order_ads.boost_order_count, 0) AS dex_boost_order_count,
                COALESCE(order_ads.approved_order_types, '[]'::jsonb) AS dex_paid_order_types,
                logo.logo_url,
                latest_price.price_usd,
                latest_price.price_native,
                latest_price.time AS price_time,
                latest_price.liquidity_usd,
                latest_price.volume_5m_usd,
                latest_price.volume_1h_usd,
                latest_price.volume_6h_usd,
                latest_price.volume_24h_usd,
                latest_price.buys_5m,
                latest_price.sells_5m,
                latest_price.buys_1h,
                latest_price.sells_1h,
                latest_price.buys_24h,
                latest_price.sells_24h,
                latest_price.market_cap_usd,
                latest_price.fdv_usd,
                latest_raw.price_change AS dexscreener_price_change,
                CASE
                    WHEN price_1h.price_usd > 0 THEN
                        ROUND(((latest_price.price_usd - price_1h.price_usd) / price_1h.price_usd) * 100, 2)
                    ELSE NULL
                END AS price_change_1h_pct,
                CASE
                    WHEN price_4h.price_usd > 0 THEN
                        ROUND(((latest_price.price_usd - price_4h.price_usd) / price_4h.price_usd) * 100, 2)
                    ELSE NULL
                END AS price_change_4h_pct,
                CASE
                    WHEN price_24h.price_usd > 0 THEN
                        ROUND(((latest_price.price_usd - price_24h.price_usd) / price_24h.price_usd) * 100, 2)
                    ELSE NULL
                END AS price_change_24h_pct,
                COALESCE(sparkline.sparkline_points, '[]'::jsonb) AS price_sparkline,
                latest_wd.market_filter_status,
                latest_wd.market_filter_pass,
                latest_wd.market_warning_level,
                latest_wd.contract_risk_status,
                latest_wd.contract_risk_pass,
                latest_wd.risk_score,
                latest_wd.top_holders_percent,
                latest_wd.wallet_status,
                latest_wd.wallet_pass,
                latest_wd.top_holder_percent,
                latest_wd.top10_holders_percent,
                latest_wd.cluster_status,
                latest_wd.cluster_pass,
                latest_wd.largest_cluster_size,
                latest_wd.largest_cluster_funder,
                latest_wd.manipulation_status,
                latest_wd.manipulation_pass,
                latest_wd.manipulation_score,
                manipulation.manipulation_reason,
                manipulation.shared_funder_cluster_size,
                manipulation.token_distributor_count,
                manipulation.linked_wallet_count,
                manipulation.coordinated_dump_count,
                latest_wd.intelligence_summary,
                latest_wd.final_watchlist_status,
                latest_wd.final_watchlist_pass,
                latest_wd.final_watchlist_reason,
                dashboard_details.details,
                latest_wd.created_at
            FROM latest_wd
            JOIN tokens t
                ON t.id = latest_wd.token_id
            LEFT JOIN token_pairs p
                ON p.id = latest_wd.pair_id
            LEFT JOIN LATERAL (
                SELECT ras.raw_json->>'icon' AS logo_url
                FROM raw_api_snapshots ras
                WHERE ras.token_address = t.address
                  AND ras.endpoint = '/token-profiles/latest/v1'
                ORDER BY ras.created_at DESC
                LIMIT 1
            ) logo ON TRUE
            LEFT JOIN LATERAL (
                SELECT MIN(ras.created_at) AS first_seen_at
                FROM raw_api_snapshots ras
                WHERE ras.token_address = t.address
                  AND ras.endpoint = '/token-profiles/latest/v1'
            ) first_profile ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    CASE
                        WHEN ras.raw_json->'boosts'->>'active' ~ '^[0-9]+$'
                            THEN (ras.raw_json->'boosts'->>'active')::int
                        ELSE 0
                    END AS active_boosts
                FROM raw_api_snapshots ras
                WHERE ras.token_address = t.address
                  AND ras.endpoint = '/token-pairs/v1/solana/{{tokenAddress}}'
                ORDER BY ras.created_at DESC
                LIMIT 1
            ) pair_ads ON TRUE
            LEFT JOIN LATERAL (
                WITH latest_orders AS (
                    SELECT ras.raw_json
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = t.address
                      AND ras.endpoint = '/orders/v1/solana/{{tokenAddress}}'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ),
                normalized AS (
                    SELECT
                        CASE
                            WHEN jsonb_typeof(raw_json->'orders') = 'array' THEN raw_json->'orders'
                            ELSE '[]'::jsonb
                        END AS orders_json,
                        CASE
                            WHEN jsonb_typeof(raw_json->'boosts') = 'array' THEN raw_json->'boosts'
                            ELSE '[]'::jsonb
                        END AS boosts_json
                    FROM latest_orders
                )
                SELECT
                    jsonb_array_length(orders_json) AS paid_order_count,
                    jsonb_array_length(boosts_json) AS boost_order_count,
                    COALESCE(
                        (
                            SELECT jsonb_agg(DISTINCT order_item->>'type')
                            FROM jsonb_array_elements(orders_json) AS order_item
                            WHERE order_item->>'status' IN ('approved', 'processing')
                        ),
                        '[]'::jsonb
                    ) AS approved_order_types
                FROM normalized
            ) order_ads ON TRUE
            LEFT JOIN LATERAL (
                SELECT tp.time, tp.price_usd
                    , tp.price_native
                    , tp.liquidity_usd
                    , tp.volume_5m_usd
                    , tp.volume_1h_usd
                    , tp.volume_6h_usd
                    , tp.volume_24h_usd
                    , tp.buys_5m
                    , tp.sells_5m
                    , tp.buys_1h
                    , tp.sells_1h
                    , tp.buys_24h
                    , tp.sells_24h
                    , tp.market_cap_usd
                    , tp.fdv_usd
                FROM token_prices tp
                WHERE tp.pair_id = latest_wd.pair_id
                  AND tp.price_usd IS NOT NULL
                ORDER BY tp.time DESC
                LIMIT 1
            ) latest_price ON TRUE
            LEFT JOIN LATERAL (
                SELECT ras.raw_json->'priceChange' AS price_change
                FROM raw_api_snapshots ras
                WHERE ras.token_address = t.address
                  AND ras.endpoint = '/token-pairs/v1/solana/{{tokenAddress}}'
                ORDER BY ras.created_at DESC
                LIMIT 1
            ) latest_raw ON TRUE
            LEFT JOIN LATERAL (
                SELECT tp.price_usd
                FROM token_prices tp
                WHERE tp.pair_id = latest_wd.pair_id
                  AND tp.price_usd IS NOT NULL
                  AND latest_price.time IS NOT NULL
                  AND tp.time <= latest_price.time - INTERVAL '1 hour'
                ORDER BY tp.time DESC
                LIMIT 1
            ) price_1h ON TRUE
            LEFT JOIN LATERAL (
                SELECT tp.price_usd
                FROM token_prices tp
                WHERE tp.pair_id = latest_wd.pair_id
                  AND tp.price_usd IS NOT NULL
                  AND latest_price.time IS NOT NULL
                  AND tp.time <= latest_price.time - INTERVAL '4 hours'
                ORDER BY tp.time DESC
                LIMIT 1
            ) price_4h ON TRUE
            LEFT JOIN LATERAL (
                SELECT tp.price_usd
                FROM token_prices tp
                WHERE tp.pair_id = latest_wd.pair_id
                  AND tp.price_usd IS NOT NULL
                  AND latest_price.time IS NOT NULL
                  AND tp.time <= latest_price.time - INTERVAL '24 hours'
                ORDER BY tp.time DESC
                LIMIT 1
            ) price_24h ON TRUE
            LEFT JOIN LATERAL (
                -- 24-hour price sparkline. Read from the hourly continuous
                -- aggregate (migration 012) so this stays cheap and keeps
                -- working past the 30-day raw_prices retention cutoff.
                -- Returns up to 24 chronologically-ordered close prices.
                SELECT
                    COALESCE(
                        jsonb_agg(close_price_usd ORDER BY bucket ASC),
                        '[]'::jsonb
                    ) AS sparkline_points
                FROM (
                    SELECT bucket, close_price_usd
                    FROM token_prices_hourly
                    WHERE pair_id = latest_wd.pair_id
                      AND close_price_usd IS NOT NULL
                      AND bucket >= NOW() - INTERVAL '24 hours'
                    ORDER BY bucket DESC
                    LIMIT 24
                ) recent_buckets
            ) sparkline ON TRUE
            LEFT JOIN LATERAL (
                SELECT jsonb_build_object(
                    'liquidity_usd', latest_wd.details->'liquidity_usd',
                    'market_cap_usd', latest_wd.details->'market_cap_usd',
                    'fdv_usd', to_jsonb(latest_price.fdv_usd),
                    'volume_5m_usd', to_jsonb(latest_price.volume_5m_usd),
                    'volume_1h_usd', COALESCE(latest_wd.details->'volume_1h_usd', to_jsonb(latest_price.volume_1h_usd)),
                    'volume_6h_usd', to_jsonb(latest_price.volume_6h_usd),
                    'volume_24h_usd', to_jsonb(latest_price.volume_24h_usd),
                    'liquidity_status', latest_wd.details->'liquidity_status',
                    'liquidity_trap_status', latest_wd.details->'liquidity_trap_status',
                    'liquidity_trap_score', latest_wd.details->'liquidity_trap_score',
                    'liquidity_trap_reason', latest_wd.details->'liquidity_trap_reason',
                    'liquidity_trap_warnings', latest_wd.details->'liquidity_trap_warnings',
                    'lp_lock', latest_wd.details->'lp_lock',
                    'dev_audit_status', latest_wd.details->'dev_audit_status',
                    'dev_audit_reason', latest_wd.details->'dev_audit_reason',
                    'dev_wallet_address', latest_wd.details->'dev_wallet_address',
                    'dev_sold_token_amount', latest_wd.details->'dev_sold_token_amount',
                    'dev_total_token_out', latest_wd.details->'dev_total_token_out',
                    'dev_flow_status', latest_wd.details->'dev_flow_status',
                    'dev_flow_reason', latest_wd.details->'dev_flow_reason',
                    'shadow_dev_score', latest_wd.details->'shadow_dev_score',
                    'dev_proxy_dump_count', latest_wd.details->'dev_proxy_dump_count',
                    'dev_splitter_count', latest_wd.details->'dev_splitter_count',
                    'insider_probability_score', latest_wd.details->'insider_probability_score',
                    'insider_probability_level', latest_wd.details->'insider_probability_level',
                    'insider_probability_reasons', latest_wd.details->'insider_probability_reasons'
                ) AS details
            ) dashboard_details ON TRUE
            LEFT JOIN wallet_manipulation_results manipulation
                ON manipulation.run_id = latest_wd.run_id
               AND manipulation.token_id = latest_wd.token_id
            {where}
            ORDER BY latest_wd.run_id DESC, latest_wd.created_at DESC
            LIMIT $1;
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [dict(row) for row in rows]
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def fetch_token_detail(pool: asyncpg.Pool, run_id: int, token_id: int) -> dict:
    try:
        async with pool.acquire() as conn:
            token = await conn.fetchrow(
                """
                SELECT
                    wd.id,
                    wd.run_id,
                    wd.token_id,
                    wd.pair_id,
                    t.symbol,
                    t.name,
                    t.address AS token_address,
                    p.dex_id,
                    p.url AS pair_url,
                    p.pair_address,
                    p.pair_created_at,
                    first_profile.first_seen_at AS dexscreener_first_seen_at,
                    first_price.time AS first_price_snapshot_at,
                    first_promotion.first_seen_at AS dex_promotion_first_seen_at,
                    COALESCE(pair_ads.active_boosts, 0) AS dex_active_boosts,
                    COALESCE(order_ads.paid_order_count, 0) AS dex_paid_order_count,
                    COALESCE(order_ads.boost_order_count, 0) AS dex_boost_order_count,
                    COALESCE(order_ads.approved_order_types, '[]'::jsonb) AS dex_paid_order_types,
                    logo.logo_url,
                    wd.market_filter_status,
                    wd.market_filter_pass,
                    wd.market_warning_level,
                    wd.contract_risk_status,
                    wd.contract_risk_pass,
                    wd.risk_score,
                    wd.top_holders_percent,
                    wd.wallet_status,
                    wd.wallet_pass,
                    wd.top_holder_percent,
                    wd.top10_holders_percent,
                    wd.cluster_status,
                    wd.cluster_pass,
                    wd.largest_cluster_size,
                    wd.largest_cluster_funder,
                    wd.manipulation_status,
                    wd.manipulation_pass,
                    wd.manipulation_score,
                    manipulation.manipulation_reason,
                    manipulation.shared_funder_cluster_size,
                    manipulation.token_distributor_count,
                    manipulation.linked_wallet_count,
                    manipulation.coordinated_dump_count,
                    wd.intelligence_summary,
                    wd.final_watchlist_status,
                    wd.final_watchlist_pass,
                    wd.final_watchlist_reason,
                    wd.details,
                    wd.created_at
                FROM watchlist_decisions wd
                JOIN tokens t
                    ON t.id = wd.token_id
                LEFT JOIN token_pairs p
                    ON p.id = wd.pair_id
                LEFT JOIN LATERAL (
                    SELECT ras.raw_json->>'icon' AS logo_url
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = t.address
                      AND ras.endpoint = '/token-profiles/latest/v1'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ) logo ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        CASE
                            WHEN ras.raw_json->'boosts'->>'active' ~ '^[0-9]+$'
                                THEN (ras.raw_json->'boosts'->>'active')::int
                            ELSE 0
                        END AS active_boosts
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = t.address
                      AND ras.endpoint = '/token-pairs/v1/solana/{tokenAddress}'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ) pair_ads ON TRUE
                LEFT JOIN LATERAL (
                    SELECT MIN(ras.created_at) AS first_seen_at
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = t.address
                      AND ras.endpoint = '/token-profiles/latest/v1'
                ) first_profile ON TRUE
                LEFT JOIN LATERAL (
                    SELECT tp.time
                    FROM token_prices tp
                    WHERE tp.pair_id = wd.pair_id
                      AND tp.price_usd IS NOT NULL
                    ORDER BY tp.time ASC
                    LIMIT 1
                ) first_price ON TRUE
                LEFT JOIN LATERAL (
                    WITH latest_orders AS (
                        SELECT ras.raw_json
                        FROM raw_api_snapshots ras
                        WHERE ras.token_address = t.address
                          AND ras.endpoint = '/orders/v1/solana/{tokenAddress}'
                        ORDER BY ras.created_at DESC
                        LIMIT 1
                    ),
                    normalized AS (
                        SELECT
                            CASE
                                WHEN jsonb_typeof(raw_json->'orders') = 'array' THEN raw_json->'orders'
                                ELSE '[]'::jsonb
                            END AS orders_json,
                            CASE
                                WHEN jsonb_typeof(raw_json->'boosts') = 'array' THEN raw_json->'boosts'
                                ELSE '[]'::jsonb
                            END AS boosts_json
                        FROM latest_orders
                    )
                    SELECT
                        jsonb_array_length(orders_json) AS paid_order_count,
                        jsonb_array_length(boosts_json) AS boost_order_count,
                        COALESCE(
                            (
                                SELECT jsonb_agg(DISTINCT order_item->>'type')
                                FROM jsonb_array_elements(orders_json) AS order_item
                                WHERE order_item->>'status' IN ('approved', 'processing')
                            ),
                            '[]'::jsonb
                    ) AS approved_order_types
                    FROM normalized
                ) order_ads ON TRUE
                LEFT JOIN LATERAL (
                    SELECT MIN(created_at) AS first_seen_at
                    FROM (
                        SELECT ras.created_at
                        FROM raw_api_snapshots ras
                        WHERE ras.token_address = t.address
                          AND ras.endpoint = '/token-pairs/v1/solana/{tokenAddress}'
                          AND ras.raw_json->'boosts'->>'active' ~ '^[0-9]+$'
                          AND (ras.raw_json->'boosts'->>'active')::int > 0
                        UNION ALL
                        SELECT ras.created_at
                        FROM raw_api_snapshots ras
                        WHERE ras.token_address = t.address
                          AND ras.endpoint = '/orders/v1/solana/{tokenAddress}'
                          AND (
                              CASE
                                  WHEN jsonb_typeof(ras.raw_json->'orders') = 'array'
                                      THEN jsonb_array_length(ras.raw_json->'orders')
                                  ELSE 0
                              END > 0
                              OR CASE
                                  WHEN jsonb_typeof(ras.raw_json->'boosts') = 'array'
                                      THEN jsonb_array_length(ras.raw_json->'boosts')
                                  ELSE 0
                              END > 0
                          )
                    ) promotion_events
                ) first_promotion ON TRUE
                LEFT JOIN wallet_manipulation_results manipulation
                    ON manipulation.run_id = wd.run_id
                   AND manipulation.token_id = wd.token_id
                WHERE wd.run_id = $1
                  AND wd.token_id = $2;
                """,
                run_id,
                token_id,
            )

            wallets = await conn.fetch(
                """
                SELECT
                    wi.wallet_address,
                    wi.rank,
                    wi.holder_percent,
                    wi.labels,
                    wi.wallet_score,
                    wi.first_entry_at,
                    wi.seconds_from_launch,
                    wi.total_token_in,
                    wi.total_token_out,
                    wi.net_token_amount,
                    wi.transaction_count,
                    wi.funding_source,
                    wi.details,
                    th.amount AS holder_amount,
                    fe.funder_address,
                    fe.amount_lamports,
                    fe.timestamp AS funded_at,
                    fe.signature AS funding_signature
                FROM wallet_intelligence_results wi
                LEFT JOIN token_holders th
                    ON th.run_id = wi.run_id
                   AND th.token_id = wi.token_id
                   AND th.owner_address = wi.wallet_address
                LEFT JOIN wallet_funding_edges fe
                    ON fe.run_id = wi.run_id
                   AND fe.token_id = wi.token_id
                   AND fe.holder_address = wi.wallet_address
                   AND fe.source = 'helius'
                WHERE wi.run_id = $1
                  AND wi.token_id = $2
                ORDER BY wi.rank NULLS LAST, wi.wallet_score ASC;
                """,
                run_id,
                token_id,
            )

            holders = await conn.fetch(
                """
                SELECT
                    owner_address,
                    rank,
                    amount,
                    percent,
                    source
                FROM token_holders
                WHERE run_id = $1
                  AND token_id = $2
                ORDER BY rank
                LIMIT 20;
                """,
                run_id,
                token_id,
            )

            relationships = await conn.fetch(
                """
                SELECT
                    from_wallet,
                    to_wallet,
                    relation_type,
                    amount,
                    signature,
                    timestamp
                FROM wallet_relationship_edges
                WHERE run_id = $1
                  AND token_id = $2
                ORDER BY timestamp DESC NULLS LAST
                LIMIT 50;
                """,
                run_id,
                token_id,
            )

        return {
            "token": dict(token) if token else None,
            "wallets": [dict(row) for row in wallets],
            "holders": [dict(row) for row in holders],
            "relationships": [dict(row) for row in relationships],
        }
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def fetch_runs(pool: asyncpg.Pool, limit: int) -> list[dict]:
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    source,
                    status,
                    tokens_found,
                    tokens_saved,
                    pairs_saved,
                    prices_saved,
                    errors_count,
                    started_at,
                    finished_at
                FROM ingestion_runs
                ORDER BY id DESC
                LIMIT $1;
                """,
                limit,
            )

        return [dict(row) for row in rows]
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def fetch_whale_radar(pool: asyncpg.Pool, limit: int, wallet_address: str | None = None) -> dict:
    min_alert_amount_sol = float(os.getenv("WHALE_SIGNAL_ALERT_MIN_SOL", "0.1"))
    min_alert_score = float(os.getenv("WHALE_SIGNAL_ALERT_MIN_SCORE_10", "5"))
    confluence_min_wallets = int(os.getenv("WHALE_CONFLUENCE_MIN_WALLETS", "2"))
    confluence_window_hours = int(os.getenv("WHALE_CONFLUENCE_WINDOW_HOURS", "24"))

    try:
        async with pool.acquire() as conn:
            leaderboard = await conn.fetch(
                """
                SELECT
                    elite_wallets.id,
                    elite_wallets.wallet_address,
                    elite_wallets.label,
                    elite_wallets.total_profit_sol,
                    elite_wallets.total_profit_30d_sol,
                    elite_wallets.win_rate_percent,
                    elite_wallets.avg_roi_percent,
                    elite_wallets.avg_minutes_after_launch,
                    elite_wallets.trade_count,
                    elite_wallets.profitable_trade_count,
                    elite_wallets.reliability_score,
                    ROUND(elite_wallets.reliability_score / 10, 2) AS reliability_score_10,
                    elite_wallets.bot_flag,
                    elite_wallets.status,
                    survival.survival_rate_percent,
                    survival.rugged_trade_count,
                    survival.whale_style,
                    survival.exit_style,
                    survival.laddering_score,
                    survival.security_level,
                    survival.warning_flags AS survival_warnings,
                    survival.favorite_token_symbols,
                    elite_wallets.details,
                    elite_wallets.first_discovered_at,
                    elite_wallets.last_scored_at
                FROM elite_wallets
                LEFT JOIN whale_survival_profiles survival
                    ON survival.wallet_address = elite_wallets.wallet_address
                ORDER BY elite_wallets.bot_flag ASC, elite_wallets.reliability_score DESC, elite_wallets.total_profit_sol DESC
                LIMIT $1;
                """,
                limit,
            )

            live_signal_where = ""
            live_signal_params: list[Any] = [limit]
            if wallet_address:
                live_signal_where = "WHERE s.wallet_address = $2"
                live_signal_params.append(wallet_address)

            live_signals = await conn.fetch(
                f"""
                SELECT
                    s.id,
                    s.wallet_address,
                    s.token_address,
                    COALESCE(s.token_symbol, t.symbol) AS token_symbol,
                    t.name AS token_name,
                    logo.logo_url,
                    s.signal_type,
                    s.amount_sol,
                    s.price_usd,
                    s.signature,
                    s.source,
                    s.signal_at,
                    ew.label,
                    ew.reliability_score,
                    ROUND(ew.reliability_score / 10, 2) AS reliability_score_10,
                    survival.security_level,
                    latest_decision.run_id AS decision_run_id,
                    latest_decision.token_id AS decision_token_id,
                    latest_decision.final_watchlist_status,
                    latest_decision.final_watchlist_pass
                FROM live_whale_signals s
                LEFT JOIN elite_wallets ew
                    ON ew.id = s.elite_wallet_id
                LEFT JOIN whale_survival_profiles survival
                    ON survival.wallet_address = s.wallet_address
                LEFT JOIN tokens t
                    ON t.address = s.token_address
                LEFT JOIN LATERAL (
                    SELECT
                        wd.run_id,
                        wd.token_id,
                        wd.final_watchlist_status,
                        wd.final_watchlist_pass
                    FROM watchlist_decisions wd
                    WHERE wd.token_id = t.id
                    ORDER BY wd.run_id DESC, wd.created_at DESC, wd.id DESC
                    LIMIT 1
                ) latest_decision ON TRUE
                LEFT JOIN LATERAL (
                    SELECT ras.raw_json->>'icon' AS logo_url
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = s.token_address
                      AND ras.endpoint = '/token-profiles/latest/v1'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ) logo ON TRUE
                {live_signal_where}
                ORDER BY s.signal_at DESC, s.id DESC
                LIMIT $1;
                """,
                *live_signal_params,
            )

            high_signal_alerts = await conn.fetch(
                """
                SELECT
                    s.id,
                    s.wallet_address,
                    s.token_address,
                    COALESCE(s.token_symbol, t.symbol) AS token_symbol,
                    t.name AS token_name,
                    logo.logo_url,
                    s.signal_type,
                    s.amount_sol,
                    s.price_usd,
                    s.signature,
                    s.source,
                    s.signal_at,
                    ew.label,
                    ew.reliability_score,
                    ROUND(ew.reliability_score / 10, 2) AS reliability_score_10,
                    survival.security_level,
                    latest_decision.run_id AS decision_run_id,
                    latest_decision.token_id AS decision_token_id,
                    latest_decision.final_watchlist_status,
                    latest_decision.final_watchlist_pass
                FROM live_whale_signals s
                LEFT JOIN elite_wallets ew
                    ON ew.id = s.elite_wallet_id
                LEFT JOIN whale_survival_profiles survival
                    ON survival.wallet_address = s.wallet_address
                LEFT JOIN tokens t
                    ON t.address = s.token_address
                LEFT JOIN LATERAL (
                    SELECT
                        wd.run_id,
                        wd.token_id,
                        wd.final_watchlist_status,
                        wd.final_watchlist_pass
                    FROM watchlist_decisions wd
                    WHERE wd.token_id = t.id
                    ORDER BY wd.run_id DESC, wd.created_at DESC, wd.id DESC
                    LIMIT 1
                ) latest_decision ON TRUE
                LEFT JOIN LATERAL (
                    SELECT ras.raw_json->>'icon' AS logo_url
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = s.token_address
                      AND ras.endpoint = '/token-profiles/latest/v1'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ) logo ON TRUE
                WHERE s.signal_type IN ('BUY', 'TOKEN_IN')
                  AND COALESCE(s.amount_sol, 0) >= $1
                  AND COALESCE(ew.reliability_score, 0) >= ($2 * 10)
                  AND COALESCE(survival.security_level, 'UNPROVEN') NOT IN ('RISKY', 'INSIDER_RISK')
                  AND s.token_address IS NOT NULL
                  AND s.token_address <> ALL($3::text[])
                ORDER BY
                    COALESCE(ew.reliability_score, 0) DESC,
                    COALESCE(s.amount_sol, 0) DESC,
                    s.signal_at DESC,
                    s.id DESC
                LIMIT 20;
                """,
                min_alert_amount_sol,
                min_alert_score,
                list(NOISE_TOKEN_ADDRESSES),
            )

            confluence_alerts = await conn.fetch(
                """
                WITH candidate_signals AS (
                    SELECT
                        s.wallet_address,
                        s.token_address,
                        COALESCE(s.token_symbol, t.symbol) AS token_symbol,
                        t.name AS token_name,
                        s.amount_sol,
                        s.signal_at,
                        ew.reliability_score,
                        ROUND(ew.reliability_score / 10, 2) AS reliability_score_10,
                        survival.security_level,
                        logo.logo_url,
                        latest_decision.run_id AS decision_run_id,
                        latest_decision.token_id AS decision_token_id,
                        latest_decision.final_watchlist_status,
                        latest_decision.final_watchlist_pass
                    FROM live_whale_signals s
                    LEFT JOIN elite_wallets ew
                        ON ew.id = s.elite_wallet_id
                    LEFT JOIN whale_survival_profiles survival
                        ON survival.wallet_address = s.wallet_address
                    LEFT JOIN tokens t
                        ON t.address = s.token_address
                    LEFT JOIN LATERAL (
                        SELECT
                            wd.run_id,
                            wd.token_id,
                            wd.final_watchlist_status,
                            wd.final_watchlist_pass
                        FROM watchlist_decisions wd
                        WHERE wd.token_id = t.id
                        ORDER BY wd.run_id DESC, wd.created_at DESC, wd.id DESC
                        LIMIT 1
                    ) latest_decision ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT ras.raw_json->>'icon' AS logo_url
                        FROM raw_api_snapshots ras
                        WHERE ras.token_address = s.token_address
                          AND ras.endpoint = '/token-profiles/latest/v1'
                        ORDER BY ras.created_at DESC
                        LIMIT 1
                    ) logo ON TRUE
                    WHERE s.signal_type IN ('BUY', 'TOKEN_IN')
                      AND s.signal_at >= NOW() - ($4::int * INTERVAL '1 hour')
                      AND COALESCE(s.amount_sol, 0) >= $1
                      AND COALESCE(ew.reliability_score, 0) >= ($2 * 10)
                      AND COALESCE(survival.security_level, 'UNPROVEN') NOT IN ('RISKY', 'INSIDER_RISK')
                      AND s.token_address IS NOT NULL
                      AND s.token_address <> ALL($3::text[])
                )
                SELECT
                    token_address,
                    MAX(token_symbol) AS token_symbol,
                    MAX(token_name) AS token_name,
                    MAX(logo_url) AS logo_url,
                    COUNT(DISTINCT wallet_address) AS wallet_count,
                    COALESCE(ROUND(SUM(COALESCE(amount_sol, 0)), 4), 0) AS total_amount_sol,
                    COALESCE(ROUND(AVG(COALESCE(reliability_score_10, 0)), 2), 0) AS avg_reliability_score_10,
                    MAX(signal_at) AS latest_signal_at,
                    ARRAY_AGG(DISTINCT wallet_address) AS wallet_addresses,
                    MAX(decision_run_id) AS decision_run_id,
                    MAX(decision_token_id) AS decision_token_id,
                    MAX(final_watchlist_status) AS final_watchlist_status,
                    BOOL_OR(COALESCE(final_watchlist_pass, false)) AS final_watchlist_pass
                FROM candidate_signals
                GROUP BY token_address
                HAVING COUNT(DISTINCT wallet_address) >= $5
                ORDER BY wallet_count DESC, total_amount_sol DESC, latest_signal_at DESC
                LIMIT 12;
                """,
                min_alert_amount_sol,
                min_alert_score,
                list(NOISE_TOKEN_ADDRESSES),
                confluence_window_hours,
                confluence_min_wallets,
            )

            summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS wallet_count,
                    COUNT(*) FILTER (WHERE elite_wallets.label = 'ELITE_SMART_MONEY') AS elite_count,
                    COUNT(*) FILTER (WHERE elite_wallets.bot_flag) AS bot_excluded_count,
                    COUNT(*) FILTER (WHERE survival.security_level = 'SAFE_TO_WATCH') AS safe_to_watch_count,
                    COUNT(*) FILTER (WHERE survival.security_level = 'RISKY') AS risky_survival_count,
                    COALESCE(ROUND(AVG(elite_wallets.reliability_score), 2), 0) AS avg_reliability_score,
                    COALESCE(ROUND(SUM(elite_wallets.total_profit_sol), 4), 0) AS total_tracked_profit_sol
                FROM elite_wallets
                LEFT JOIN whale_survival_profiles survival
                    ON survival.wallet_address = elite_wallets.wallet_address;
                """
            )

            shadow = await conn.fetchrow(
                """
                SELECT
                    COALESCE(ROUND(SUM(COALESCE(current_unrealized_pnl_sol, pnl_sol)), 4), 0) AS shadow_profit_sol,
                    COUNT(*) AS tracked_trade_count,
                    COUNT(*) FILTER (WHERE COALESCE(current_unrealized_pnl_sol, pnl_sol) > 0) AS winning_trade_count
                FROM whale_performance_tracking
                WHERE created_at >= NOW() - INTERVAL '24 hours';
                """
            )

            webhook = await conn.fetchrow(
                """
                SELECT
                    webhook_id,
                    webhook_url,
                    active,
                    status,
                    jsonb_array_length(account_addresses) AS watched_wallets,
                    updated_at,
                    last_error
                FROM whale_webhook_configs
                WHERE provider = 'helius'
                ORDER BY updated_at DESC, id DESC
                LIMIT 1;
                """
            )

            signal_jobs = await conn.fetch(
                """
                SELECT
                    id,
                    wallet_address,
                    token_address,
                    signal_type,
                    status,
                    reason,
                    run_id,
                    final_watchlist_status,
                    error_message,
                    created_at,
                    finished_at
                FROM whale_signal_analysis_jobs
                ORDER BY created_at DESC, id DESC
                LIMIT $1;
                """,
                limit,
            )

        return {
            "summary": dict(summary) if summary else {},
            "shadow_performance": dict(shadow) if shadow else {},
            "webhook": dict(webhook) if webhook else None,
            "leaderboard": [dict(row) for row in leaderboard],
            "live_signals": [dict(row) for row in live_signals],
            "high_signal_alerts": [dict(row) for row in high_signal_alerts],
            "confluence_alerts": [dict(row) for row in confluence_alerts],
            "signal_jobs": [dict(row) for row in signal_jobs],
            "signal_settings": {
                "alert_min_amount_sol": min_alert_amount_sol,
                "alert_min_score_10": min_alert_score,
                "confluence_min_wallets": confluence_min_wallets,
                "confluence_window_hours": confluence_window_hours,
                "ignored_alert_tokens": sorted(NOISE_TOKEN_ADDRESSES),
            },
        }
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def fetch_wallet_detail(pool: asyncpg.Pool, wallet_address: str) -> dict:
    try:
        async with pool.acquire() as conn:
            wallet = await conn.fetchrow(
                """
                SELECT
                    ew.id,
                    ew.wallet_address,
                    ew.label,
                    ew.total_profit_sol,
                    ew.total_profit_30d_sol,
                    ew.win_rate_percent,
                    ew.avg_roi_percent,
                    ew.avg_minutes_after_launch,
                    ew.trade_count,
                    ew.profitable_trade_count,
                    ew.reliability_score,
                    ROUND(ew.reliability_score / 10, 2) AS reliability_score_10,
                    ew.bot_flag,
                    ew.status,
                    ew.source,
                    ew.details,
                    ew.first_discovered_at,
                    ew.last_scored_at,
                    wsp.survival_rate_percent,
                    wsp.rugged_trade_count,
                    wsp.survived_trade_count,
                    wsp.total_trades_checked,
                    wsp.avg_hold_minutes,
                    wsp.whale_style,
                    wsp.exit_style,
                    wsp.laddering_score,
                    wsp.dev_shadow_flag,
                    wsp.dev_shadow_reason,
                    wsp.security_level,
                    wsp.warning_flags,
                    wsp.favorite_token_symbols,
                    wsp.details AS survival_details
                FROM elite_wallets ew
                LEFT JOIN whale_survival_profiles wsp
                    ON wsp.wallet_address = ew.wallet_address
                WHERE ew.wallet_address = $1;
                """,
                wallet_address,
            )

            if not wallet:
                return {"wallet": None, "trades": [], "signals": [], "stats": {}}

            trades = await conn.fetch(
                """
                SELECT
                    wpt.id,
                    wpt.wallet_address,
                    wpt.token_address,
                    COALESCE(wpt.token_symbol, t.symbol) AS token_symbol,
                    t.name AS token_name,
                    logo.logo_url,
                    wpt.entry_at,
                    wpt.exit_at,
                    wpt.minutes_after_launch,
                    wpt.native_spent_sol,
                    wpt.native_received_sol,
                    wpt.pnl_sol,
                    wpt.roi_percent,
                    wpt.trade_status,
                    wpt.source,
                    wpt.current_price_usd,
                    wpt.current_price_native,
                    wpt.current_value_sol,
                    wpt.current_unrealized_pnl_sol,
                    wpt.price_refreshed_at,
                    latest_price.market_cap_usd,
                    latest_price.fdv_usd,
                    latest_price.liquidity_usd,
                    latest_price.volume_24h_usd,
                    latest_decision.run_id AS decision_run_id,
                    latest_decision.token_id AS decision_token_id,
                    latest_decision.final_watchlist_status,
                    latest_decision.final_watchlist_pass
                FROM whale_performance_tracking wpt
                LEFT JOIN tokens t
                    ON t.address = wpt.token_address
                LEFT JOIN LATERAL (
                    SELECT ras.raw_json->>'icon' AS logo_url
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = wpt.token_address
                      AND ras.endpoint = '/token-profiles/latest/v1'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ) logo ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        tp.market_cap_usd,
                        tp.fdv_usd,
                        tp.liquidity_usd,
                        tp.volume_24h_usd
                    FROM token_prices tp
                    JOIN token_pairs pair_for_price
                        ON pair_for_price.id = tp.pair_id
                    WHERE pair_for_price.token_id = t.id
                    ORDER BY tp.time DESC
                    LIMIT 1
                ) latest_price ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        wd.run_id,
                        wd.token_id,
                        wd.final_watchlist_status,
                        wd.final_watchlist_pass
                    FROM watchlist_decisions wd
                    WHERE wd.token_id = t.id
                    ORDER BY wd.run_id DESC, wd.created_at DESC, wd.id DESC
                    LIMIT 1
                ) latest_decision ON TRUE
                WHERE wpt.wallet_address = $1
                ORDER BY COALESCE(wpt.exit_at, wpt.entry_at, wpt.created_at) DESC
                LIMIT 120;
                """,
                wallet_address,
            )

            signals = await conn.fetch(
                """
                SELECT
                    s.id,
                    s.wallet_address,
                    s.token_address,
                    COALESCE(s.token_symbol, t.symbol) AS token_symbol,
                    t.name AS token_name,
                    logo.logo_url,
                    s.signal_type,
                    s.amount_sol,
                    s.price_usd,
                    s.signature,
                    s.source,
                    s.signal_at
                FROM live_whale_signals s
                LEFT JOIN tokens t
                    ON t.address = s.token_address
                LEFT JOIN LATERAL (
                    SELECT ras.raw_json->>'icon' AS logo_url
                    FROM raw_api_snapshots ras
                    WHERE ras.token_address = s.token_address
                      AND ras.endpoint = '/token-profiles/latest/v1'
                    ORDER BY ras.created_at DESC
                    LIMIT 1
                ) logo ON TRUE
                WHERE s.wallet_address = $1
                ORDER BY s.signal_at DESC, s.id DESC
                LIMIT 80;
                """,
                wallet_address,
            )

            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS trade_count,
                    COUNT(*) FILTER (WHERE COALESCE(pnl_sol, current_unrealized_pnl_sol, 0) > 0) AS profitable_count,
                    COUNT(*) FILTER (WHERE roi_percent > 500) AS roi_over_500,
                    COUNT(*) FILTER (WHERE roi_percent BETWEEN 200 AND 500) AS roi_200_500,
                    COUNT(*) FILTER (WHERE roi_percent BETWEEN 0 AND 200) AS roi_0_200,
                    COUNT(*) FILTER (WHERE roi_percent BETWEEN -50 AND 0) AS roi_neg_50_0,
                    COUNT(*) FILTER (WHERE roi_percent < -50) AS roi_below_neg_50,
                    COUNT(*) FILTER (WHERE native_spent_sol < 1) AS buy_small,
                    COUNT(*) FILTER (WHERE native_spent_sol >= 1 AND native_spent_sol < 5) AS buy_medium,
                    COUNT(*) FILTER (WHERE native_spent_sol >= 5) AS buy_large,
                    COALESCE(ROUND(SUM(COALESCE(pnl_sol, current_unrealized_pnl_sol, 0)), 4), 0) AS total_pnl_sol,
                    COALESCE(ROUND(SUM(COALESCE(current_unrealized_pnl_sol, 0)), 4), 0) AS unrealized_pnl_sol,
                    COALESCE(ROUND(SUM(COALESCE(native_spent_sol, 0)), 4), 0) AS total_spent_sol,
                    COALESCE(ROUND(SUM(COALESCE(native_received_sol, 0)), 4), 0) AS total_received_sol,
                    COALESCE(ROUND(AVG(roi_percent), 2), 0) AS avg_roi_percent,
                    COALESCE(ROUND(AVG(minutes_after_launch), 2), 0) AS avg_minutes_after_launch
                FROM whale_performance_tracking
                WHERE wallet_address = $1;
                """,
                wallet_address,
            )

        return {
            "wallet": dict(wallet),
            "trades": [dict(row) for row in trades],
            "signals": [dict(row) for row in signals],
            "stats": dict(stats) if stats else {},
        }
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def store_whale_signal(pool: asyncpg.Pool, payload: dict) -> dict:
    try:
        return await save_live_whale_signal(pool, payload)
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def store_whale_signal_payload(app: FastAPI, payload) -> dict:
    pool = app.state.pool
    if isinstance(payload, list):
        saved = []
        for item in payload:
            if isinstance(item, dict):
                signal = await store_whale_signal(pool, item)
                signal["auto_analysis"] = await maybe_queue_whale_signal_analysis(app, signal)
                saved.append(signal)
        return {"saved_count": len(saved), "signals": saved}
    if isinstance(payload, dict):
        signal = await store_whale_signal(pool, payload)
        signal["auto_analysis"] = await maybe_queue_whale_signal_analysis(app, signal)
        return signal
    raise ValueError("Webhook payload must be a JSON object or array")


async def maybe_queue_whale_signal_analysis(app: FastAPI, signal: dict) -> dict:
    pool = app.state.pool
    token_address = str(signal.get("token_address") or "").strip()
    wallet_address = str(signal.get("wallet_address") or "").strip()
    signal_type = str(signal.get("signal_type") or "").upper()
    min_auto_analyze_amount = float(os.getenv("WHALE_SIGNAL_AUTO_ANALYZE_MIN_SOL", "0.1"))

    if signal_type not in {"BUY", "TOKEN_IN"}:
        return {"queued": False, "reason": "Signal is not a buy/token-in event"}
    if not token_address or not is_valid_solana_address(token_address):
        return {"queued": False, "reason": "Missing or invalid token address"}
    if token_address in NOISE_TOKEN_ADDRESSES:
        return {"queued": False, "reason": "Noise token is ignored for auto-analysis"}
    if float(signal.get("amount_sol") or 0) < min_auto_analyze_amount:
        return {"queued": False, "reason": f"Signal amount is below {min_auto_analyze_amount} SOL"}

    try:
        async with pool.acquire() as conn:
            profile = await conn.fetchrow(
                """
                SELECT
                    ew.label,
                    ew.reliability_score,
                    ew.bot_flag,
                    wsp.security_level
                FROM elite_wallets ew
                LEFT JOIN whale_survival_profiles wsp
                    ON wsp.wallet_address = ew.wallet_address
                WHERE ew.wallet_address = $1;
                """,
                wallet_address,
            )

            if not profile:
                return {"queued": False, "reason": "Wallet is not tracked"}
            if profile["bot_flag"]:
                return {"queued": False, "reason": "Wallet is bot-excluded"}
            if profile["security_level"] in {"RISKY", "INSIDER_RISK"}:
                return {"queued": False, "reason": f"Wallet security is {profile['security_level']}"}

            existing_decision = await conn.fetchrow(
                """
                SELECT wd.run_id, wd.final_watchlist_status
                FROM watchlist_decisions wd
                JOIN tokens t
                    ON t.id = wd.token_id
                WHERE t.address = $1
                ORDER BY wd.run_id DESC, wd.created_at DESC, wd.id DESC
                LIMIT 1;
                """,
                token_address,
            )
            if existing_decision:
                return {
                    "queued": False,
                    "reason": "Token already analyzed",
                    "run_id": existing_decision["run_id"],
                    "final_watchlist_status": existing_decision["final_watchlist_status"],
                }

            row = await conn.fetchrow(
                """
                INSERT INTO whale_signal_analysis_jobs (
                    signal_id,
                    wallet_address,
                    token_address,
                    signal_type,
                    status,
                    reason
                )
                VALUES ($1, $2, $3, $4, 'QUEUED', 'Queued from whale live signal')
                ON CONFLICT (token_address) DO UPDATE
                SET signal_id = COALESCE(whale_signal_analysis_jobs.signal_id, EXCLUDED.signal_id)
                RETURNING id, status;
                """,
                signal.get("id"),
                wallet_address,
                token_address,
                signal_type,
            )

            if row["status"] not in {"QUEUED", "FAILED"}:
                return {"queued": False, "reason": f"Existing job is {row['status']}", "job_id": row["id"]}

            asyncio.create_task(
                whale_signal_token_worker(
                    app.state.pool,
                    app.state.dexscreener_client,
                    app.state.helius_client,
                    token_address,
                    row["id"],
                )
            )

            return {"queued": True, "job_id": row["id"], "reason": "Queued from whale live signal"}
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


async def run_whale_action(pool: asyncpg.Pool, action: str) -> dict:
    try:
        if action == "audit":
            return await run_whale_consistency_audit(pool)
        if action == "refresh-prices":
            return await refresh_whale_trade_prices(pool)
        if action == "sync-webhook":
            return await sync_whale_webhook(pool)
        if action == "survival":
            return await run_whale_survival_service(pool)
        raise ValueError(f"Unknown whale action: {action}")
    finally:
        pass  # pool lifetime managed by FastAPI lifespan


def parse_limit_str(raw: str | None, default: int = 50, maximum: int = 200) -> int:
    """Parse a query-string limit value, clamped to ``[1, maximum]``.

    Falls back to ``default`` when the parameter is missing or empty.
    Raises :class:`ValueError` for non-integer input — handlers translate
    this into a 400 so frontend bugs surface instead of being swallowed.
    """
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"limit must be an integer, got {raw!r}") from exc
    return max(1, min(value, maximum))


# ----------------------------------------------------------------------------
# FastAPI application
# ----------------------------------------------------------------------------


class QuantJSONResponse(JSONResponse):
    """JSONResponse that mirrors the original `json.dumps(default=str)` behavior.

    Preserves Decimal/datetime/UUID serialization as strings to keep API
    responses byte-compatible with the previous BaseHTTPRequestHandler version.
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            default=json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create one asyncpg pool and one HTTP client of each kind for the
    entire application lifetime.

    Singletons are stored on ``app.state`` so request handlers and async
    workers can reuse them without each one creating short-lived sockets
    and TLS handshakes. The shared rate limiters inside each client only
    serialize calls per-instance; making them process-wide closes the gap
    where two concurrent services could collectively exceed upstream
    limits.
    """
    pool = await create_pool()
    dexscreener_client = DexScreenerClient()
    helius_client = HeliusClient()

    app.state.pool = pool
    app.state.dexscreener_client = dexscreener_client
    app.state.helius_client = helius_client
    try:
        yield
    finally:
        await dexscreener_client.aclose()
        await helius_client.aclose()
        await pool.close()


app = FastAPI(
    title="Quant Watchlist",
    version="0.2.0",
    default_response_class=QuantJSONResponse,
    lifespan=lifespan,
)


@app.middleware("http")
async def add_no_store_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def _static(name: str) -> Response:
    path = STATIC_DIR / name
    if not path.exists():
        return Response(content="Static file not found", status_code=404)
    return FileResponse(path, media_type="text/html; charset=utf-8")


def _vite_or_static(page_slug: str, legacy_filename: str) -> Response:
    """Prefer the Vite-built page if present, fall back to the legacy
    ``app/static/<filename>`` HTML otherwise.

    The Vite build emits ``web/dist/pages/<slug>/index.html`` with hashed
    asset references that resolve via the ``/static/dist/...`` route. We
    only serve it when the build output is on disk so the legacy page
    keeps working in environments where ``npm run build`` hasn't run yet
    (e.g. before CI is wired up).
    """
    vite_html = WEB_DIST_DIR / "pages" / page_slug / "index.html"
    if vite_html.is_file():
        return FileResponse(vite_html, media_type="text/html; charset=utf-8")
    return _static(legacy_filename)


# Content-type whitelist for /static/{path}. Anything not on this list is 404.
_STATIC_ASSET_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}


# ---- HTML page routes -------------------------------------------------------


@app.get("/", include_in_schema=False)
async def page_dashboard() -> Response:
    return _static("dashboard.html")


@app.get("/token", include_in_schema=False)
async def page_token_detail() -> Response:
    return _static("token_detail.html")


@app.get("/whale-radar", include_in_schema=False)
async def page_whale_radar() -> Response:
    return _static("whale_radar.html")


@app.get("/wallet", include_in_schema=False)
async def page_wallet_detail() -> Response:
    return _vite_or_static("wallet", "wallet_detail.html")


@app.get("/system", include_in_schema=False)
async def page_system() -> Response:
    return _vite_or_static("system", "system.html")


@app.get("/static/dist/{path:path}", include_in_schema=False)
async def page_vite_asset(path: str) -> Response:
    """Serve hashed assets from the Vite build (``web/dist``).

    The built HTML references files like ``/static/dist/assets/system-<hash>.js``.
    We resolve those against ``WEB_DIST_DIR`` with the same content-type
    whitelist used by ``page_static_asset``.
    """
    if not WEB_DIST_DIR.exists():
        return Response(content="Not found", status_code=404)

    candidate = (WEB_DIST_DIR / path).resolve()
    try:
        candidate.relative_to(WEB_DIST_DIR.resolve())
    except ValueError:
        return Response(content="Not found", status_code=404)

    if not candidate.is_file():
        return Response(content="Not found", status_code=404)

    media_type = _STATIC_ASSET_CONTENT_TYPES.get(candidate.suffix.lower())
    if media_type is None:
        return Response(content="Not found", status_code=404)

    return FileResponse(candidate, media_type=media_type)


@app.get("/static/{path:path}", include_in_schema=False)
async def page_static_asset(path: str) -> Response:
    # Reject any path that tries to escape STATIC_DIR.
    candidate = (STATIC_DIR / path).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return Response(content="Not found", status_code=404)

    if not candidate.is_file():
        return Response(content="Not found", status_code=404)

    media_type = _STATIC_ASSET_CONTENT_TYPES.get(candidate.suffix.lower())
    if media_type is None:
        # Don't serve arbitrary file types; HTML pages have their own routes.
        return Response(content="Not found", status_code=404)

    return FileResponse(candidate, media_type=media_type)


# ---- API GET routes ---------------------------------------------------------


@app.get("/api/health")
async def api_health() -> dict:
    return {"status": "ok"}


@app.get("/api/summary")
async def api_summary(request: Request) -> dict:
    return await fetch_summary(request.app.state.pool)


def _parse_limit_or_400(
    raw: str | None,
    default: int,
    maximum: int,
) -> tuple[int | None, Response | None]:
    """Helper that returns either ``(limit, None)`` or ``(None, 400 response)``."""
    try:
        return parse_limit_str(raw, default=default, maximum=maximum), None
    except ValueError as exc:
        return None, QuantJSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/watchlist")
async def api_watchlist(
    request: Request,
    status: str | None = None,
    limit: str | None = None,
) -> Response:
    parsed, error = _parse_limit_or_400(limit, default=50, maximum=200)
    if error is not None:
        return error
    return QuantJSONResponse(
        await fetch_watchlist(
            request.app.state.pool,
            status=status,
            limit=parsed,
        )
    )


@app.get("/api/token-detail")
async def api_token_detail(
    request: Request,
    run_id: str = "",
    token_id: str = "",
) -> Response:
    try:
        run_id_int = int(run_id)
        token_id_int = int(token_id)
    except ValueError:
        return QuantJSONResponse(
            {"error": "run_id and token_id are required integers"},
            status_code=400,
        )
    payload = await fetch_token_detail(
        request.app.state.pool,
        run_id=run_id_int,
        token_id=token_id_int,
    )
    return QuantJSONResponse(payload)


@app.get("/api/runs")
async def api_runs(request: Request, limit: str | None = None) -> Response:
    parsed, error = _parse_limit_or_400(limit, default=10, maximum=100)
    if error is not None:
        return error
    return QuantJSONResponse(
        await fetch_runs(
            request.app.state.pool,
            limit=parsed,
        )
    )


@app.get("/api/whale-radar")
async def api_whale_radar(
    request: Request,
    limit: str | None = None,
    wallet: str | None = None,
) -> Response:
    parsed, error = _parse_limit_or_400(limit, default=50, maximum=300)
    if error is not None:
        return error
    return QuantJSONResponse(
        await fetch_whale_radar(
            request.app.state.pool,
            limit=parsed,
            wallet_address=wallet,
        )
    )


@app.get("/api/wallet-detail")
async def api_wallet_detail(
    request: Request,
    wallet: str = "",
    address: str = "",
) -> Response:
    addr = (wallet or address).strip()
    if not is_valid_solana_address(addr):
        return QuantJSONResponse({"error": "wallet is required"}, status_code=400)
    payload = await fetch_wallet_detail(request.app.state.pool, addr)
    return QuantJSONResponse(payload)


@app.get("/api/scan/status")
async def api_scan_status() -> dict:
    return get_scan_state()


@app.get("/api/events")
async def api_events(request: Request) -> StreamingResponse:
    """
    Server-Sent Events stream of scan / state changes.

    Each connected browser tab gets its own queue. A heartbeat comment
    every 15s keeps proxies from killing the connection. The current
    state is sent on connect so the client doesn't need to make a
    separate /api/scan/status fetch.
    """
    queue = subscribe()

    async def event_stream():
        try:
            # Initial snapshot so the client doesn't see "Loading..."
            # until the next state change.
            yield _sse_format("scan_state", get_scan_state())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat comment -- ignored by EventSource clients
                    # but keeps middleware boxes from terminating idle
                    # connections.
                    yield ": heartbeat\n\n"
                    continue
                yield _sse_format(event["type"], event["data"])
        finally:
            unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable Nginx buffering if proxied
        },
    )


def _sse_format(event_type: str, data: Any) -> str:
    """Format an SSE message: ``event: <type>\\ndata: <json>\\n\\n``."""
    payload = json.dumps(data, default=json_default, separators=(",", ":"))
    return f"event: {event_type}\ndata: {payload}\n\n"


# ---- /api/system ------------------------------------------------------------
#
# Operational visibility for the local dashboard. Tells the operator at a
# glance whether external APIs are configured, how recently each ingested,
# whether retention is still cleaning up, the database size, and the last
# few failed ingestion runs.

async def fetch_system_status(pool: asyncpg.Pool) -> dict:
    helius_key = os.getenv("HELIUS_API_KEY")
    rugcheck_key = os.getenv("RUGCHECK_API_KEY")
    webhook_url = os.getenv("WHALE_WEBHOOK_URL") or os.getenv("HELIUS_WHALE_WEBHOOK_URL")
    webhook_auth = os.getenv("WHALE_WEBHOOK_AUTH_HEADER") or os.getenv("HELIUS_WEBHOOK_AUTH_HEADER")

    # Roll-up of the last hour's outbound activity per source. Each
    # ingest writes a row into raw_api_snapshots so this is a free
    # "Helius/DexScreener requests" approximator.
    activity_sql = """
        SELECT
            source,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '1 hour')   AS req_1h,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS req_24h,
            MAX(created_at) AS last_seen
        FROM raw_api_snapshots
        GROUP BY source
        ORDER BY source;
    """

    # Recent failed runs — good for ops triage.
    failed_runs_sql = """
        SELECT id, source, status, error_message, started_at, finished_at
        FROM ingestion_runs
        WHERE status = 'failed' OR errors_count > 0
        ORDER BY id DESC
        LIMIT 5;
    """

    # DB size totals.
    db_size_sql = """
        SELECT
            pg_size_pretty(pg_database_size(current_database())) AS db_size_pretty,
            pg_database_size(current_database())                 AS db_size_bytes;
    """

    # Hypertable + retention info from Timescale catalog. Returns rows only
    # when the extension is installed; gracefully empty otherwise.
    timescale_sql = """
        SELECT
            h.hypertable_name AS table_name,
            h.compression_enabled,
            (SELECT COUNT(*) FROM timescaledb_information.chunks c
              WHERE c.hypertable_name = h.hypertable_name) AS chunk_count
        FROM timescaledb_information.hypertables h
        ORDER BY h.hypertable_name;
    """
    retention_sql = """
        SELECT j.hypertable_name AS table_name, j.config->>'drop_after' AS drop_after
        FROM timescaledb_information.jobs j
        WHERE j.proc_name = 'policy_retention'
        ORDER BY j.hypertable_name;
    """

    # Whale webhook config snapshot.
    webhook_sql = """
        SELECT webhook_url, status, active, jsonb_array_length(account_addresses) AS watched, updated_at, last_error
        FROM whale_webhook_configs
        WHERE provider = 'helius'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1;
    """

    # Latest scan state — the in-memory SCAN_STATE is already exposed via
    # /api/scan/status; we also include the row count of latest decisions
    # so the page has a "watchlist depth" number to show.
    decisions_sql = """
        SELECT COUNT(*) AS total_decisions,
               COUNT(*) FILTER (WHERE final_watchlist_status = 'WATCHLIST_PASS') AS pass,
               COUNT(*) FILTER (WHERE final_watchlist_status = 'WATCHLIST_PASS_HIGH_RISK') AS pass_high_risk,
               MAX(created_at) AS latest_at
        FROM watchlist_decisions;
    """

    async with pool.acquire() as conn:
        activity = await conn.fetch(activity_sql)
        failed = await conn.fetch(failed_runs_sql)
        size = await conn.fetchrow(db_size_sql)
        try:
            tables = await conn.fetch(timescale_sql)
            retention = await conn.fetch(retention_sql)
        except asyncpg.exceptions.UndefinedTableError:
            tables, retention = [], []
        except asyncpg.exceptions.PostgresError:
            tables, retention = [], []
        webhook = await conn.fetchrow(webhook_sql)
        decisions = await conn.fetchrow(decisions_sql)

    return {
        "config": {
            "helius_configured": bool(helius_key),
            "rugcheck_configured": bool(rugcheck_key),
            "whale_webhook_url_configured": bool(webhook_url),
            "whale_webhook_auth_configured": bool(webhook_auth),
        },
        "activity": [dict(row) for row in activity],
        "failed_runs": [dict(row) for row in failed],
        "db_size": dict(size) if size else {},
        "hypertables": [dict(row) for row in tables],
        "retention_policies": [dict(row) for row in retention],
        "whale_webhook": dict(webhook) if webhook else None,
        "decisions": dict(decisions) if decisions else {},
        "scan_state": get_scan_state(),
    }


@app.get("/api/system")
async def api_system(request: Request) -> Response:
    payload = await fetch_system_status(request.app.state.pool)
    return QuantJSONResponse(payload)


# ---- API POST routes --------------------------------------------------------


@app.post("/api/scan")
async def api_scan_post(request: Request) -> Response:
    started, state = start_scan_job(request.app)
    status_code = 202 if started else 409
    return QuantJSONResponse(state, status_code=status_code)


@app.post("/api/analyze-token")
async def api_analyze_token(request: Request) -> Response:
    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return QuantJSONResponse({"error": "Invalid JSON body"}, status_code=400)

    if not isinstance(payload, dict):
        return QuantJSONResponse({"error": "Invalid JSON body"}, status_code=400)

    token_address = str(payload.get("token_address") or "").strip()
    started, state = start_manual_token_job(request.app, token_address)
    if not started and state.get("error") == "Invalid Solana token address":
        return QuantJSONResponse(state, status_code=400)

    status_code = 202 if started else 409
    return QuantJSONResponse(state, status_code=status_code)


def _whale_webhook_auth_ok(provided: str | None, expected: str | None) -> bool:
    """
    Constant-time comparison for the whale-signal webhook ``Authorization``
    header.

    Returns True iff:
        * No expected secret is configured (auth disabled), OR
        * The provided header matches the expected one byte-for-byte.

    Uses :func:`hmac.compare_digest` so a remote attacker cannot learn the
    secret by timing repeated requests with progressively-correct prefixes.
    Both arguments are encoded to bytes first because ``compare_digest``
    requires equal-type operands and short-circuits on length mismatch.
    """
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


@app.post("/api/whale-signal")
async def api_whale_signal(request: Request) -> Response:
    expected_auth = os.getenv("WHALE_WEBHOOK_AUTH_HEADER") or os.getenv("HELIUS_WEBHOOK_AUTH_HEADER")
    if not _whale_webhook_auth_ok(
        request.headers.get("Authorization"),
        expected_auth,
    ):
        return QuantJSONResponse({"error": "Unauthorized webhook"}, status_code=401)

    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return QuantJSONResponse({"error": "Invalid JSON body"}, status_code=400)

    try:
        saved = await store_whale_signal_payload(request.app, payload)
    except Exception as exc:
        return QuantJSONResponse({"error": str(exc)}, status_code=400)

    return QuantJSONResponse(saved, status_code=202)


@app.post("/api/whale-radar/{action}")
async def api_whale_radar_action(action: str, request: Request) -> Response:
    if action not in {"audit", "refresh-prices", "sync-webhook", "survival"}:
        return QuantJSONResponse({"error": "Not found"}, status_code=404)
    try:
        result = await run_whale_action(request.app.state.pool, action)
    except Exception as exc:
        return QuantJSONResponse({"error": str(exc)}, status_code=400)
    return QuantJSONResponse(result, status_code=202)


def main() -> None:
    host = os.getenv("MEMECO_HOST", "127.0.0.1")
    port = int(os.getenv("MEMECO_PORT", "8000"))
    print(f"Quant watchlist dashboard: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

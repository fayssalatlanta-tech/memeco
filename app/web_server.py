import asyncio
import json
import threading
import traceback
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from db import create_pool
from ingest_dexscreener import ingest_manual_token, main as run_ingestion
from services.cluster_analysis_service import run_cluster_analysis_service
from services.contract_risk_service import run_contract_risk_service
from services.liquidity_filter_service import run_liquidity_filter_service
from services.dev_wallet_audit_service import run_dev_wallet_audit_service
from services.market_filter_service import (
    get_early_dex_candidates,
    save_market_filter_results,
)
from services.wallet_analysis_service import run_wallet_analysis_service
from services.wallet_intelligence_service import run_wallet_intelligence_service
from services.wallet_manipulation_service import run_wallet_manipulation_service
from services.dev_wallet_flow_service import run_dev_wallet_flow_service
from services.watchlist_decision_service import run_watchlist_decision_service
from services.whale_signal_service import save_live_whale_signal
from services.whale_consistency_auditor_service import run_whale_consistency_audit
from services.whale_price_refresh_service import refresh_whale_trade_prices
from services.whale_webhook_service import sync_whale_webhook
from services.whale_survival_service import run_whale_survival_service


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SCAN_LOCK = threading.Lock()
SCAN_STATE = {
    "running": False,
    "status": "idle",
    "stage": "idle",
    "message": "No scan has been started",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "steps": [],
}

NOISE_TOKEN_ADDRESSES = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


def json_default(value):
    return str(value)


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def get_scan_state() -> dict:
    with SCAN_LOCK:
        return dict(SCAN_STATE)


def update_scan_state(**updates) -> None:
    with SCAN_LOCK:
        SCAN_STATE.update(updates)


def append_scan_step(name: str, status: str, message: str | None = None) -> None:
    with SCAN_LOCK:
        steps = list(SCAN_STATE.get("steps") or [])
        steps.append(
            {
                "name": name,
                "status": status,
                "message": message,
                "at": utc_now_iso(),
            }
        )
        SCAN_STATE["steps"] = steps[-20:]


async def run_analysis_pipeline_with_status() -> None:
    pool = await create_pool()

    try:
        update_scan_state(stage="market_filter", message="Running Market Filter")
        append_scan_step("Market Filter", "running")
        market_candidates = await get_early_dex_candidates(pool)
        market_results = await save_market_filter_results(pool, market_candidates)
        append_scan_step("Market Filter", "done", f"Saved {len(market_results)} results")

        update_scan_state(stage="contract_risk", message="Running Contract Risk")
        append_scan_step("Contract Risk", "running")
        contract_results = await run_contract_risk_service(pool)
        append_scan_step("Contract Risk", "done", f"Saved {len(contract_results)} results")

        update_scan_state(stage="liquidity_filter", message="Running Liquidity Filter")
        append_scan_step("Liquidity Filter", "running")
        liquidity_results = await run_liquidity_filter_service(pool)
        append_scan_step("Liquidity Filter", "done", f"Saved {len(liquidity_results)} results")

        update_scan_state(stage="wallet_analysis", message="Running Wallet Analysis")
        append_scan_step("Wallet Analysis", "running")
        wallet_results = await run_wallet_analysis_service(pool)
        append_scan_step("Wallet Analysis", "done", f"Saved {len(wallet_results)} results")

        update_scan_state(stage="cluster_analysis", message="Running Cluster Analysis")
        append_scan_step("Cluster Analysis", "running")
        cluster_results = await run_cluster_analysis_service(pool)
        append_scan_step("Cluster Analysis", "done", f"Saved {len(cluster_results)} results")

        update_scan_state(stage="wallet_intelligence", message="Running Wallet Intelligence")
        append_scan_step("Wallet Intelligence", "running")
        intelligence_results = await run_wallet_intelligence_service(pool)
        append_scan_step("Wallet Intelligence", "done", f"Saved {len(intelligence_results)} results")

        update_scan_state(stage="wallet_manipulation", message="Running Wallet Manipulation")
        append_scan_step("Wallet Manipulation", "running")
        manipulation_results = await run_wallet_manipulation_service(pool)
        append_scan_step("Wallet Manipulation", "done", f"Saved {len(manipulation_results)} results")

        update_scan_state(stage="dev_wallet_audit", message="Running Dev Wallet Audit")
        append_scan_step("Dev Wallet Audit", "running")
        dev_audit_results = await run_dev_wallet_audit_service(pool)
        append_scan_step("Dev Wallet Audit", "done", f"Saved {len(dev_audit_results)} results")

        update_scan_state(stage="dev_wallet_flow", message="Running Dev Wallet Flow")
        append_scan_step("Dev Wallet Flow", "running")
        dev_flow_results = await run_dev_wallet_flow_service(pool)
        append_scan_step("Dev Wallet Flow", "done", f"Saved {len(dev_flow_results)} results")

        update_scan_state(stage="watchlist_decision", message="Running Watchlist Decision")
        append_scan_step("Watchlist Decision", "running")
        watchlist_results = await run_watchlist_decision_service(pool)
        append_scan_step("Watchlist Decision", "done", f"Saved {len(watchlist_results)} results")
    finally:
        await pool.close()


def scan_worker() -> None:
    update_scan_state(
        running=True,
        status="running",
        stage="ingestion",
        message="Ingesting DexScreener data",
        started_at=utc_now_iso(),
        finished_at=None,
        error=None,
        steps=[],
    )

    try:
        append_scan_step("DexScreener Ingestion", "running")
        asyncio.run(run_ingestion())
        append_scan_step("DexScreener Ingestion", "done")
        update_scan_state(message="Running analysis pipeline")
        asyncio.run(run_analysis_pipeline_with_status())
        update_scan_state(
            running=False,
            status="finished",
            stage="finished",
            message="Scan finished successfully",
            finished_at=utc_now_iso(),
            error=None,
        )
    except Exception as exc:
        update_scan_state(
            running=False,
            status="failed",
            stage="failed",
            message="Scan failed",
            finished_at=utc_now_iso(),
            error=f"{exc}\n{traceback.format_exc()}",
        )
        append_scan_step("Scan", "failed", str(exc))


def manual_token_worker(token_address: str) -> None:
    update_scan_state(
        running=True,
        status="running",
        stage="manual_ingestion",
        message=f"Analyzing token {token_address}",
        started_at=utc_now_iso(),
        finished_at=None,
        error=None,
        steps=[],
    )

    try:
        append_scan_step("Manual Token Ingestion", "running", token_address)
        saved = asyncio.run(ingest_manual_token(token_address))
        run_id = saved["run_id"]
        symbol = saved["token"].get("symbol") or token_address
        append_scan_step("Manual Token Ingestion", "done", f"Saved {symbol} in run #{run_id}")

        update_scan_state(message="Running analysis pipeline")
        asyncio.run(run_analysis_pipeline_with_status())
        update_scan_state(
            running=False,
            status="finished",
            stage="finished",
            message=f"Manual token analysis finished for {symbol}",
            finished_at=utc_now_iso(),
            error=None,
        )
    except Exception as exc:
        update_scan_state(
            running=False,
            status="failed",
            stage="failed",
            message="Manual token analysis failed",
            finished_at=utc_now_iso(),
            error=f"{exc}\n{traceback.format_exc()}",
        )
        append_scan_step("Manual Token Analysis", "failed", str(exc))


async def latest_decision_for_token(pool, token_address: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                wd.run_id,
                wd.final_watchlist_status
            FROM watchlist_decisions wd
            JOIN tokens t
                ON t.id = wd.token_id
            WHERE t.address = $1
            ORDER BY wd.run_id DESC, wd.created_at DESC, wd.id DESC
            LIMIT 1;
            """,
            token_address,
        )
    return dict(row) if row else None


async def mark_signal_analysis_started(job_id: int) -> None:
    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE whale_signal_analysis_jobs
                SET status = 'RUNNING',
                    started_at = NOW(),
                    error_message = NULL
                WHERE id = $1;
                """,
                job_id,
            )
    finally:
        await pool.close()


async def mark_signal_analysis_finished(job_id: int, token_address: str) -> None:
    pool = await create_pool()
    try:
        decision = await latest_decision_for_token(pool, token_address)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE whale_signal_analysis_jobs
                SET status = 'FINISHED',
                    finished_at = NOW(),
                    run_id = $2,
                    final_watchlist_status = $3
                WHERE id = $1;
                """,
                job_id,
                (decision or {}).get("run_id"),
                (decision or {}).get("final_watchlist_status"),
            )
    finally:
        await pool.close()


async def mark_signal_analysis_failed(job_id: int, error_message: str) -> None:
    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE whale_signal_analysis_jobs
                SET status = 'FAILED',
                    finished_at = NOW(),
                    error_message = $2
                WHERE id = $1;
                """,
                job_id,
                error_message[:2000],
            )
    finally:
        await pool.close()


def whale_signal_token_worker(token_address: str, job_id: int) -> None:
    try:
        asyncio.run(mark_signal_analysis_started(job_id))
        saved = asyncio.run(ingest_manual_token(token_address))
        asyncio.run(run_analysis_pipeline_with_status())
        asyncio.run(mark_signal_analysis_finished(job_id, token_address))
        append_scan_step(
            "Whale Signal Auto Analysis",
            "done",
            f"Analyzed {token_address} from whale signal in run #{saved.get('run_id')}",
        )
    except Exception as exc:
        asyncio.run(mark_signal_analysis_failed(job_id, f"{exc}\n{traceback.format_exc()}"))
        append_scan_step("Whale Signal Auto Analysis", "failed", str(exc))


def start_scan_job() -> tuple[bool, dict]:
    with SCAN_LOCK:
        if SCAN_STATE["running"]:
            return False, dict(SCAN_STATE)

        SCAN_STATE.update(
            running=True,
            status="queued",
            stage="queued",
            message="Scan queued",
            started_at=utc_now_iso(),
            finished_at=None,
            error=None,
            steps=[],
        )

    thread = threading.Thread(target=scan_worker, daemon=True)
    thread.start()

    return True, get_scan_state()


def is_valid_solana_address(value: str) -> bool:
    if not value or not 32 <= len(value) <= 64:
        return False

    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return all(char in alphabet for char in value)


def start_manual_token_job(token_address: str) -> tuple[bool, dict]:
    token_address = token_address.strip()

    if not is_valid_solana_address(token_address):
        state = get_scan_state()
        state["error"] = "Invalid Solana token address"
        return False, state

    with SCAN_LOCK:
        if SCAN_STATE["running"]:
            return False, dict(SCAN_STATE)

        SCAN_STATE.update(
            running=True,
            status="queued",
            stage="queued",
            message=f"Manual token analysis queued for {token_address}",
            started_at=utc_now_iso(),
            finished_at=None,
            error=None,
            steps=[],
        )

    thread = threading.Thread(target=manual_token_worker, args=(token_address,), daemon=True)
    thread.start()

    return True, get_scan_state()


async def fetch_summary() -> dict:
    pool = await create_pool()

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
        await pool.close()


async def fetch_watchlist(status: str | None, limit: int) -> list[dict]:
    pool = await create_pool()

    try:
        where_conditions = ["LOWER(COALESCE(p.dex_id, '')) <> 'pumpfun'"]
        params = [limit]

        if status:
            where_conditions.append("latest_wd.final_watchlist_status = $2")
            params.append(status)

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
        await pool.close()


async def fetch_token_detail(run_id: int, token_id: int) -> dict:
    pool = await create_pool()

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
        await pool.close()


async def fetch_runs(limit: int) -> list[dict]:
    pool = await create_pool()

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
        await pool.close()


async def fetch_whale_radar(limit: int, wallet_address: str | None = None) -> dict:
    pool = await create_pool()
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
            live_signal_params = [limit]
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
        await pool.close()


async def fetch_wallet_detail(wallet_address: str) -> dict:
    pool = await create_pool()

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
        await pool.close()


async def store_whale_signal(payload: dict) -> dict:
    pool = await create_pool()

    try:
        return await save_live_whale_signal(pool, payload)
    finally:
        await pool.close()


async def store_whale_signal_payload(payload) -> dict:
    if isinstance(payload, list):
        saved = []
        for item in payload:
            if isinstance(item, dict):
                signal = await store_whale_signal(item)
                signal["auto_analysis"] = await maybe_queue_whale_signal_analysis(signal)
                saved.append(signal)
        return {"saved_count": len(saved), "signals": saved}
    if isinstance(payload, dict):
        signal = await store_whale_signal(payload)
        signal["auto_analysis"] = await maybe_queue_whale_signal_analysis(signal)
        return signal
    raise ValueError("Webhook payload must be a JSON object or array")


async def maybe_queue_whale_signal_analysis(signal: dict) -> dict:
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

    pool = await create_pool()
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

            thread = threading.Thread(
                target=whale_signal_token_worker,
                args=(token_address, row["id"]),
                daemon=True,
            )
            thread.start()

            return {"queued": True, "job_id": row["id"], "reason": "Queued from whale live signal"}
    finally:
        await pool.close()


async def run_whale_action(action: str) -> dict:
    pool = await create_pool()

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
        await pool.close()


def parse_limit(query: dict[str, list[str]], default: int = 50, maximum: int = 200) -> int:
    raw_value = query.get("limit", [str(default)])[0]

    try:
        value = int(raw_value)
    except ValueError:
        value = default

    return max(1, min(value, maximum))


class QuantRequestHandler(BaseHTTPRequestHandler):
    server_version = "QuantWatchlist/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_static_file(STATIC_DIR / "dashboard.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/token":
            self.send_static_file(STATIC_DIR / "token_detail.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/whale-radar":
            self.send_static_file(STATIC_DIR / "whale_radar.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/wallet":
            self.send_static_file(STATIC_DIR / "wallet_detail.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/api/health":
            self.send_json({"status": "ok"})
            return

        if parsed.path == "/api/summary":
            self.send_json(asyncio.run(fetch_summary()))
            return

        if parsed.path == "/api/watchlist":
            status = query.get("status", [None])[0]
            limit = parse_limit(query)
            self.send_json(asyncio.run(fetch_watchlist(status=status, limit=limit)))
            return

        if parsed.path == "/api/token-detail":
            try:
                run_id = int(query.get("run_id", [""])[0])
                token_id = int(query.get("token_id", [""])[0])
            except ValueError:
                self.send_json(
                    {"error": "run_id and token_id are required integers"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            self.send_json(asyncio.run(fetch_token_detail(run_id=run_id, token_id=token_id)))
            return

        if parsed.path == "/api/runs":
            limit = parse_limit(query, default=10, maximum=100)
            self.send_json(asyncio.run(fetch_runs(limit=limit)))
            return

        if parsed.path == "/api/whale-radar":
            limit = parse_limit(query, default=50, maximum=300)
            wallet = query.get("wallet", [None])[0]
            self.send_json(asyncio.run(fetch_whale_radar(limit=limit, wallet_address=wallet)))
            return

        if parsed.path == "/api/wallet-detail":
            wallet = str(query.get("wallet", [""])[0] or query.get("address", [""])[0]).strip()
            if not is_valid_solana_address(wallet):
                self.send_json({"error": "wallet is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            self.send_json(asyncio.run(fetch_wallet_detail(wallet)))
            return

        if parsed.path == "/api/scan/status":
            self.send_json(get_scan_state())
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/scan":
            started, state = start_scan_job()
            status = HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT
            self.send_json(state, status=status)
            return

        if parsed.path == "/api/analyze-token":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw_body)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                return

            token_address = str(payload.get("token_address") or "").strip()
            started, state = start_manual_token_job(token_address)
            if not started and state.get("error") == "Invalid Solana token address":
                self.send_json(state, status=HTTPStatus.BAD_REQUEST)
                return

            status = HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT
            self.send_json(state, status=status)
            return

        if parsed.path == "/api/whale-signal":
            expected_auth = os.getenv("WHALE_WEBHOOK_AUTH_HEADER") or os.getenv("HELIUS_WEBHOOK_AUTH_HEADER")
            if expected_auth and self.headers.get("Authorization") != expected_auth:
                self.send_json({"error": "Unauthorized webhook"}, status=HTTPStatus.UNAUTHORIZED)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw_body)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                saved = asyncio.run(store_whale_signal_payload(payload))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            self.send_json(saved, status=HTTPStatus.ACCEPTED)
            return

        if parsed.path in {
            "/api/whale-radar/audit",
            "/api/whale-radar/refresh-prices",
            "/api/whale-radar/sync-webhook",
            "/api/whale-radar/survival",
        }:
            action = parsed.path.rsplit("/", 1)[-1]
            try:
                result = asyncio.run(run_whale_action(action))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            self.send_json(result, status=HTTPStatus.ACCEPTED)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_static_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Static file not found")
            return

        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), QuantRequestHandler)
    print(f"Quant watchlist dashboard: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

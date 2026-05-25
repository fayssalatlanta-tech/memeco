"""
Background workers: full scan, manual token analysis, whale signal auto-analysis.

All workers are async coroutines that run on the FastAPI main event loop and
share the lifespan-managed asyncpg pool, DexScreenerClient, and HeliusClient.
The previous threaded design recreated those resources for every job.
"""

from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

import asyncpg

from app.dexscreener import DexScreenerClient
from app.helius import HeliusClient
from app.ingest_dexscreener import ingest_manual_token
from app.ingest_dexscreener import main as run_ingestion
from app.jobs.scan_state import (
    SCAN_LOCK,
    SCAN_STATE,
    append_scan_step,
    get_scan_state,
    update_scan_state,
    utc_now_iso,
)
from app.services.cluster_analysis_service import run_cluster_analysis_service
from app.services.contract_risk_service import run_contract_risk_service
from app.services.dev_wallet_audit_service import run_dev_wallet_audit_service
from app.services.dev_wallet_flow_service import run_dev_wallet_flow_service
from app.services.liquidity_filter_service import run_liquidity_filter_service
from app.services.market_filter_service import (
    get_early_dex_candidates,
    save_market_filter_results,
)
from app.services.wallet_analysis_service import run_wallet_analysis_service
from app.services.wallet_intelligence_service import run_wallet_intelligence_service
from app.services.wallet_manipulation_service import run_wallet_manipulation_service
from app.services.watchlist_decision_service import run_watchlist_decision_service

if TYPE_CHECKING:
    from fastapi import FastAPI


# ---- Solana address sanity check -----------------------------------------


def is_valid_solana_address(value: str) -> bool:
    """Tight check: Solana base58 pubkeys are 32-44 chars."""
    if not value or not 32 <= len(value) <= 44:
        return False
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return all(char in alphabet for char in value)


# ---- Pipeline orchestrator -----------------------------------------------


async def run_analysis_pipeline_with_status(
    pool: asyncpg.Pool,
    *,
    run_id: int | None = None,
    helius_client: HeliusClient | None = None,
) -> None:
    """Run every analysis stage against a specific ingestion run.

    Caller passes the long-lived ``pool`` and (optionally) the lifespan-managed
    ``helius_client``. Passing ``run_id`` makes the chain explicitly run-scoped
    instead of each service falling back to ``MAX(id) FROM ingestion_runs``.
    """
    update_scan_state(stage="market_filter", message="Running Market Filter")
    append_scan_step("Market Filter", "running")
    market_candidates = await get_early_dex_candidates(pool, run_id=run_id)
    market_results = await save_market_filter_results(pool, market_candidates)
    append_scan_step("Market Filter", "done", f"Saved {len(market_results)} results")

    update_scan_state(stage="contract_risk", message="Running Contract Risk")
    append_scan_step("Contract Risk", "running")
    contract_results = await run_contract_risk_service(pool, run_id=run_id)
    append_scan_step("Contract Risk", "done", f"Saved {len(contract_results)} results")

    update_scan_state(stage="liquidity_filter", message="Running Liquidity Filter")
    append_scan_step("Liquidity Filter", "running")
    liquidity_results = await run_liquidity_filter_service(pool, run_id=run_id)
    append_scan_step("Liquidity Filter", "done", f"Saved {len(liquidity_results)} results")

    update_scan_state(stage="wallet_analysis", message="Running Wallet Analysis")
    append_scan_step("Wallet Analysis", "running")
    wallet_results = await run_wallet_analysis_service(pool, run_id=run_id)
    append_scan_step("Wallet Analysis", "done", f"Saved {len(wallet_results)} results")

    update_scan_state(stage="cluster_analysis", message="Running Cluster Analysis")
    append_scan_step("Cluster Analysis", "running")
    cluster_results = await run_cluster_analysis_service(
        pool, run_id=run_id, helius_client=helius_client,
    )
    append_scan_step("Cluster Analysis", "done", f"Saved {len(cluster_results)} results")

    update_scan_state(stage="wallet_intelligence", message="Running Wallet Intelligence")
    append_scan_step("Wallet Intelligence", "running")
    intelligence_results = await run_wallet_intelligence_service(
        pool, run_id=run_id, helius_client=helius_client,
    )
    append_scan_step("Wallet Intelligence", "done", f"Saved {len(intelligence_results)} results")

    update_scan_state(stage="wallet_manipulation", message="Running Wallet Manipulation")
    append_scan_step("Wallet Manipulation", "running")
    manipulation_results = await run_wallet_manipulation_service(
        pool, run_id=run_id, helius_client=helius_client,
    )
    append_scan_step("Wallet Manipulation", "done", f"Saved {len(manipulation_results)} results")

    update_scan_state(stage="dev_wallet_audit", message="Running Dev Wallet Audit")
    append_scan_step("Dev Wallet Audit", "running")
    dev_audit_results = await run_dev_wallet_audit_service(
        pool, run_id=run_id, helius_client=helius_client,
    )
    append_scan_step("Dev Wallet Audit", "done", f"Saved {len(dev_audit_results)} results")

    update_scan_state(stage="dev_wallet_flow", message="Running Dev Wallet Flow")
    append_scan_step("Dev Wallet Flow", "running")
    dev_flow_results = await run_dev_wallet_flow_service(
        pool, run_id=run_id, helius_client=helius_client,
    )
    append_scan_step("Dev Wallet Flow", "done", f"Saved {len(dev_flow_results)} results")

    update_scan_state(stage="watchlist_decision", message="Running Watchlist Decision")
    append_scan_step("Watchlist Decision", "running")
    watchlist_results = await run_watchlist_decision_service(pool, run_id=run_id)
    append_scan_step("Watchlist Decision", "done", f"Saved {len(watchlist_results)} results")


# ---- Whale-signal job state writes ---------------------------------------


async def latest_decision_for_token(pool: asyncpg.Pool, token_address: str) -> dict | None:
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


async def mark_signal_analysis_started(pool: asyncpg.Pool, job_id: int) -> None:
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


async def mark_signal_analysis_finished(
    pool: asyncpg.Pool, job_id: int, token_address: str
) -> None:
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


async def mark_signal_analysis_failed(
    pool: asyncpg.Pool, job_id: int, error_message: str
) -> None:
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


# ---- Worker coroutines ---------------------------------------------------


async def scan_worker(
    pool: asyncpg.Pool,
    dexscreener_client: DexScreenerClient,
    helius_client: HeliusClient,
) -> None:
    """Run a full ingest + analysis pass on the main event loop."""
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
        run_id = await run_ingestion(pool=pool, client=dexscreener_client)
        append_scan_step("DexScreener Ingestion", "done", f"run #{run_id}")
        update_scan_state(message="Running analysis pipeline")
        await run_analysis_pipeline_with_status(
            pool, run_id=run_id, helius_client=helius_client,
        )
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


async def manual_token_worker(
    pool: asyncpg.Pool,
    dexscreener_client: DexScreenerClient,
    helius_client: HeliusClient,
    token_address: str,
) -> None:
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
        saved = await ingest_manual_token(
            token_address, pool=pool, client=dexscreener_client,
        )
        run_id = saved["run_id"]
        symbol = saved["token"].get("symbol") or token_address
        append_scan_step(
            "Manual Token Ingestion", "done", f"Saved {symbol} in run #{run_id}",
        )

        update_scan_state(message="Running analysis pipeline")
        await run_analysis_pipeline_with_status(
            pool, run_id=run_id, helius_client=helius_client,
        )
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


async def whale_signal_token_worker(
    pool: asyncpg.Pool,
    dexscreener_client: DexScreenerClient,
    helius_client: HeliusClient,
    token_address: str,
    job_id: int,
) -> None:
    """Run a token analysis triggered by a live whale signal.

    Coordinates with the same SCAN_LOCK as scan/manual_token jobs so an
    inbound webhook can't kick off a second analysis while one is already
    running. If the lock is held the job stays QUEUED and a future signal
    flush picks it up.
    """
    with SCAN_LOCK:
        if SCAN_STATE["running"]:
            return
        SCAN_STATE.update(
            running=True,
            status="running",
            stage="whale_signal_ingestion",
            message=f"Whale signal analysis for {token_address}",
            started_at=utc_now_iso(),
            finished_at=None,
            error=None,
            steps=[],
        )

    try:
        await mark_signal_analysis_started(pool, job_id)
        saved = await ingest_manual_token(
            token_address, pool=pool, client=dexscreener_client,
        )
        await run_analysis_pipeline_with_status(
            pool, run_id=saved["run_id"], helius_client=helius_client,
        )
        await mark_signal_analysis_finished(pool, job_id, token_address)
        append_scan_step(
            "Whale Signal Auto Analysis",
            "done",
            f"Analyzed {token_address} from whale signal in run #{saved.get('run_id')}",
        )
        update_scan_state(
            running=False,
            status="finished",
            stage="finished",
            message=f"Whale signal analysis finished for {token_address}",
            finished_at=utc_now_iso(),
            error=None,
        )
    except Exception as exc:
        await mark_signal_analysis_failed(
            pool, job_id, f"{exc}\n{traceback.format_exc()}",
        )
        append_scan_step("Whale Signal Auto Analysis", "failed", str(exc))
        update_scan_state(
            running=False,
            status="failed",
            stage="failed",
            message="Whale signal analysis failed",
            finished_at=utc_now_iso(),
            error=f"{exc}\n{traceback.format_exc()}",
        )


# ---- Entry points called from request handlers ---------------------------


def start_scan_job(app: "FastAPI") -> tuple[bool, dict]:
    """Schedule a full ingest+analysis scan as a task on the main event loop."""
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

    asyncio.create_task(
        scan_worker(
            app.state.pool,
            app.state.dexscreener_client,
            app.state.helius_client,
        )
    )
    return True, get_scan_state()


def start_manual_token_job(app: "FastAPI", token_address: str) -> tuple[bool, dict]:
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

    asyncio.create_task(
        manual_token_worker(
            app.state.pool,
            app.state.dexscreener_client,
            app.state.helius_client,
            token_address,
        )
    )
    return True, get_scan_state()

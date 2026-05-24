import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from helius import HeliusClient


def unix_to_datetime(value) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def find_funding_transfer(
    holder_address: str,
    transactions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = []

    for transaction in transactions:
        native_transfers = transaction.get("nativeTransfers") or []

        if not isinstance(native_transfers, list):
            continue

        for transfer in native_transfers:
            if not isinstance(transfer, dict):
                continue

            to_account = transfer.get("toUserAccount")
            from_account = transfer.get("fromUserAccount")
            amount = transfer.get("amount")

            if to_account != holder_address or not from_account:
                continue

            if from_account == holder_address:
                continue

            candidates.append(
                {
                    "holder_address": holder_address,
                    "funder_address": from_account,
                    "signature": transaction.get("signature"),
                    "amount_lamports": amount,
                    "timestamp": unix_to_datetime(transaction.get("timestamp")),
                    "raw_json": transaction,
                }
            )

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda item: item["timestamp"] or datetime.max.replace(tzinfo=timezone.utc),
    )


def classify_clusters(edges: list[dict[str, Any]], holder_count: int) -> dict[str, Any]:
    warnings = []

    if holder_count == 0:
        return {
            "cluster_status": "CLUSTER_UNKNOWN",
            "cluster_pass": False,
            "cluster_reason": "No holder data available for cluster analysis",
            "holder_count": 0,
            "funded_holder_count": 0,
            "shared_funder_count": 0,
            "largest_cluster_size": 0,
            "largest_cluster_funder": None,
            "warnings": ["NO_HOLDER_DATA"],
        }

    funded_edges = [edge for edge in edges if edge.get("funder_address")]

    clusters = defaultdict(list)
    for edge in funded_edges:
        clusters[edge["funder_address"]].append(edge["holder_address"])

    shared_clusters = {
        funder: holders
        for funder, holders in clusters.items()
        if len(holders) >= 2
    }

    largest_cluster_funder = None
    largest_cluster_size = 0

    if shared_clusters:
        largest_cluster_funder, largest_holders = max(
            shared_clusters.items(),
            key=lambda item: len(item[1]),
        )
        largest_cluster_size = len(largest_holders)

    if largest_cluster_size >= 5:
        warnings.append("SHARED_FUNDER_CLUSTER_5_PLUS")
    elif largest_cluster_size >= 3:
        warnings.append("SHARED_FUNDER_CLUSTER_3_PLUS")
    elif largest_cluster_size >= 2:
        warnings.append("SHARED_FUNDER_CLUSTER_2_PLUS")

    if holder_count > 0 and len(funded_edges) < max(2, holder_count // 3):
        warnings.append("LOW_FUNDING_VISIBILITY")

    if "SHARED_FUNDER_CLUSTER_5_PLUS" in warnings:
        status = "CLUSTER_DANGER"
        passed = False
        reason = "Multiple top holders share the same funding source"
    elif "SHARED_FUNDER_CLUSTER_3_PLUS" in warnings:
        status = "CLUSTER_WARNING"
        passed = True
        reason = "Some top holders share the same funding source"
    elif "LOW_FUNDING_VISIBILITY" in warnings:
        status = "CLUSTER_UNKNOWN"
        passed = False
        reason = "Not enough funding-source data to classify clusters"
    elif "SHARED_FUNDER_CLUSTER_2_PLUS" in warnings:
        status = "CLUSTER_WARNING"
        passed = True
        reason = "Two top holders share a funding source"
    else:
        status = "CLUSTER_PASS"
        passed = True
        reason = "No shared funding-source cluster detected"

    return {
        "cluster_status": status,
        "cluster_pass": passed,
        "cluster_reason": reason,
        "holder_count": holder_count,
        "funded_holder_count": len(funded_edges),
        "shared_funder_count": len(shared_clusters),
        "largest_cluster_size": largest_cluster_size,
        "largest_cluster_funder": largest_cluster_funder,
        "warnings": warnings,
    }


async def get_cluster_inputs(pool: asyncpg.Pool, holder_limit: int = 10) -> list[dict[str, Any]]:
    sql = """
    SELECT
        wa.run_id,
        wa.token_id,
        wa.pair_id,
        wa.created_at,
        t.symbol,
        t.address AS token_address,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'owner_address', th.owner_address,
                    'rank', th.rank,
                    'percent', th.percent
                )
                ORDER BY th.rank
            ) FILTER (WHERE th.owner_address IS NOT NULL),
            '[]'::jsonb
        ) AS holders
    FROM wallet_analysis_results wa
    JOIN tokens t
        ON t.id = wa.token_id
    LEFT JOIN token_holders th
        ON th.run_id = wa.run_id
       AND th.token_id = wa.token_id
       AND th.rank <= $1
    WHERE wa.run_id = (
        SELECT MAX(id)
        FROM ingestion_runs
    )
    GROUP BY
        wa.run_id,
        wa.token_id,
        wa.pair_id,
        wa.created_at,
        t.symbol,
        t.address
    ORDER BY wa.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, holder_limit)

    return [dict(row) for row in rows]


async def save_funding_edge(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    edge: dict[str, Any],
) -> None:
    sql = """
    INSERT INTO wallet_funding_edges (
        run_id,
        token_id,
        holder_address,
        funder_address,
        signature,
        amount_lamports,
        timestamp,
        source,
        raw_json
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, 'helius', $8::jsonb)
    ON CONFLICT (run_id, token_id, holder_address, source)
    DO UPDATE SET
        funder_address = EXCLUDED.funder_address,
        signature = EXCLUDED.signature,
        amount_lamports = EXCLUDED.amount_lamports,
        timestamp = EXCLUDED.timestamp,
        raw_json = EXCLUDED.raw_json,
        created_at = NOW();
    """

    async with pool.acquire() as conn:
        await conn.execute(
            sql,
            row["run_id"],
            row["token_id"],
            edge["holder_address"],
            edge.get("funder_address"),
            edge.get("signature"),
            edge.get("amount_lamports"),
            edge.get("timestamp"),
            json.dumps(edge.get("raw_json") or {}, default=str),
        )


async def save_cluster_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO cluster_analysis_results (
        run_id,
        token_id,
        pair_id,
        cluster_status,
        cluster_pass,
        cluster_reason,
        holder_count,
        funded_holder_count,
        shared_funder_count,
        largest_cluster_size,
        largest_cluster_funder,
        warnings,
        details
    )
    VALUES (
        $1, $2, $3,
        $4, $5, $6,
        $7, $8, $9,
        $10, $11,
        $12::jsonb, $13::jsonb
    )
    ON CONFLICT (run_id, token_id)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,
        cluster_status = EXCLUDED.cluster_status,
        cluster_pass = EXCLUDED.cluster_pass,
        cluster_reason = EXCLUDED.cluster_reason,
        holder_count = EXCLUDED.holder_count,
        funded_holder_count = EXCLUDED.funded_holder_count,
        shared_funder_count = EXCLUDED.shared_funder_count,
        largest_cluster_size = EXCLUDED.largest_cluster_size,
        largest_cluster_funder = EXCLUDED.largest_cluster_funder,
        warnings = EXCLUDED.warnings,
        details = EXCLUDED.details,
        created_at = NOW()
    RETURNING *;
    """

    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        "source": "helius",
    }

    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            sql,
            row["run_id"],
            row["token_id"],
            row["pair_id"],
            result["cluster_status"],
            result["cluster_pass"],
            result["cluster_reason"],
            result["holder_count"],
            result["funded_holder_count"],
            result["shared_funder_count"],
            result["largest_cluster_size"],
            result["largest_cluster_funder"],
            json.dumps(result["warnings"]),
            json.dumps(details),
        )

    return dict(saved)


async def run_cluster_analysis_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await get_cluster_inputs(pool)
    client = HeliusClient()

    results = []

    for row in rows:
        holders = row.get("holders") or []

        if isinstance(holders, str):
            holders = json.loads(holders)

        if not client.is_configured:
            result = {
                "cluster_status": "CLUSTER_UNKNOWN",
                "cluster_pass": False,
                "cluster_reason": "HELIUS_API_KEY is missing",
                "holder_count": len(holders),
                "funded_holder_count": 0,
                "shared_funder_count": 0,
                "largest_cluster_size": 0,
                "largest_cluster_funder": None,
                "warnings": ["HELIUS_NOT_CONFIGURED"],
            }
            saved = await save_cluster_result(pool, row, result)
            results.append(saved)
            continue

        edges = []

        for holder in holders:
            holder_address = holder.get("owner_address")

            if not holder_address:
                continue

            try:
                transactions = await client.get_address_transactions(
                    holder_address,
                    limit=30,
                )
                edge = find_funding_transfer(holder_address, transactions)
            except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as exc:
                edge = {
                    "holder_address": holder_address,
                    "funder_address": None,
                    "signature": None,
                    "amount_lamports": None,
                    "timestamp": None,
                    "raw_json": {"error": str(exc)},
                }

            if edge is None:
                edge = {
                    "holder_address": holder_address,
                    "funder_address": None,
                    "signature": None,
                    "amount_lamports": None,
                    "timestamp": None,
                    "raw_json": {"reason": "No inbound SOL transfer found"},
                }

            await save_funding_edge(pool, row, edge)
            edges.append(edge)

        result = classify_clusters(edges, holder_count=len(holders))
        saved = await save_cluster_result(pool, row, result)

        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")

        results.append(saved)

    return results

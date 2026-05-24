import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

try:
    from helius import HeliusClient
    from services.dev_wallet_audit_service import (
        extract_dev_wallet,
        normalize_json,
        safe_float,
        token_transfer_amount,
        token_transfer_mint,
    )
except ModuleNotFoundError:
    from app.helius import HeliusClient
    from app.services.dev_wallet_audit_service import (
        extract_dev_wallet,
        normalize_json,
        safe_float,
        token_transfer_amount,
        token_transfer_mint,
    )


MAX_DEPTH = 2
MAX_DIRECT_RECIPIENTS = 20
MAX_SECOND_DEGREE_RECIPIENTS = 20
MIN_RECEIVED_SUPPLY_PCT = 0.5
MAX_TX_PER_WALLET = 50
MAX_CONCURRENT_REQUESTS = 5
SPLITTER_RECIPIENT_COUNT = 10
PROXY_DUMP_RATIO = 0.65


def tx_datetime(timestamp: Any) -> datetime | None:
    if timestamp is None:
        return None

    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def transfer_wallets(transfer: dict[str, Any]) -> tuple[str | None, str | None]:
    return transfer.get("fromUserAccount"), transfer.get("toUserAccount")


def is_swap_tx(transaction: dict[str, Any]) -> bool:
    return str(transaction.get("type") or "").upper() == "SWAP"


def iter_token_transfers(transaction: dict[str, Any], token_address: str):
    transfers = transaction.get("tokenTransfers") or []
    if not isinstance(transfers, list):
        return

    for transfer in transfers:
        if not isinstance(transfer, dict):
            continue
        if token_transfer_mint(transfer) != token_address:
            continue
        yield transfer


def estimate_initial_dev_balance(
    dev_wallet: str,
    token_address: str,
    creator_balance: float | None,
    dev_transactions: list[dict[str, Any]],
) -> float:
    token_in = 0.0
    token_out = 0.0

    for transaction in dev_transactions:
        for transfer in iter_token_transfers(transaction, token_address):
            amount = token_transfer_amount(transfer)
            from_wallet, to_wallet = transfer_wallets(transfer)
            if to_wallet == dev_wallet:
                token_in += amount
            if from_wallet == dev_wallet:
                token_out += amount

    return max(token_in, token_out + safe_float(creator_balance))


def collect_transfer_edges(
    wallet_address: str,
    token_address: str,
    transactions: list[dict[str, Any]],
    degree: int,
) -> list[dict[str, Any]]:
    edges = []

    for transaction in transactions:
        tx_type = str(transaction.get("type") or "").upper()
        signature = transaction.get("signature")
        timestamp = tx_datetime(transaction.get("timestamp"))

        for transfer in iter_token_transfers(transaction, token_address):
            amount = token_transfer_amount(transfer)
            from_wallet, to_wallet = transfer_wallets(transfer)

            if amount <= 0 or from_wallet != wallet_address or not to_wallet or to_wallet == wallet_address:
                continue

            edges.append(
                {
                    "from_wallet": from_wallet,
                    "to_wallet": to_wallet,
                    "degree": degree,
                    "amount": round(amount, 6),
                    "edge_type": "SELL" if tx_type == "SWAP" else "TRANSFER",
                    "tx_type": tx_type,
                    "signature": signature,
                    "timestamp": timestamp,
                }
            )

    return edges


def aggregate_inbound_amount(edges: list[dict[str, Any]]) -> dict[str, float]:
    amounts: dict[str, float] = defaultdict(float)
    for edge in edges:
        if edge.get("edge_type") != "TRANSFER":
            continue
        amounts[edge["to_wallet"]] += safe_float(edge.get("amount"))
    return dict(amounts)


def top_recipients(amounts: dict[str, float], threshold_amount: float, limit: int) -> list[str]:
    return [
        wallet
        for wallet, amount in sorted(amounts.items(), key=lambda item: item[1], reverse=True)
        if amount >= threshold_amount
    ][:limit]


def analyze_dev_wallet_flow(
    dev_wallet: str | None,
    token_address: str,
    creator_balance: float | None,
    dev_transactions: list[dict[str, Any]],
    wallet_transactions: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if not dev_wallet:
        return {
            "flow_status": "DEV_FLOW_UNKNOWN",
            "flow_pass": False,
            "flow_reason": "Developer wallet is unknown",
            "shadow_dev_score": 0,
            "direct_recipient_count": 0,
            "tracked_wallet_count": 0,
            "proxy_dump_count": 0,
            "splitter_count": 0,
            "total_direct_amount": 0,
            "proxy_sold_amount": 0,
            "warnings": ["DEV_WALLET_UNKNOWN"],
            "edges": [],
            "details": {"labels": {}, "tracked_wallets": []},
        }

    estimated_initial = estimate_initial_dev_balance(
        dev_wallet=dev_wallet,
        token_address=token_address,
        creator_balance=creator_balance,
        dev_transactions=dev_transactions,
    )
    threshold_amount = estimated_initial * (MIN_RECEIVED_SUPPLY_PCT / 100) if estimated_initial > 0 else 0
    direct_edges = collect_transfer_edges(dev_wallet, token_address, dev_transactions, degree=1)
    direct_amounts = aggregate_inbound_amount(direct_edges)
    direct_wallets = top_recipients(direct_amounts, threshold_amount, MAX_DIRECT_RECIPIENTS)

    all_edges = [edge for edge in direct_edges if edge.get("to_wallet") in set(direct_wallets)]
    labels: dict[str, set[str]] = defaultdict(set)
    recipient_in_amount = dict(direct_amounts)
    proxy_sold_amount = 0.0
    splitter_wallets = set()
    proxy_dump_wallets = set()
    second_degree_candidates: dict[str, float] = defaultdict(float)

    for wallet in direct_wallets:
        labels[wallet].add("DEV_DIRECT_SHIELD")
        wallet_edges = collect_transfer_edges(
            wallet,
            token_address,
            wallet_transactions.get(wallet, []),
            degree=2,
        )
        transfer_edges = [edge for edge in wallet_edges if edge["edge_type"] == "TRANSFER"]
        sell_edges = [edge for edge in wallet_edges if edge["edge_type"] == "SELL"]
        distinct_transfer_recipients = {edge["to_wallet"] for edge in transfer_edges}

        if len(distinct_transfer_recipients) >= SPLITTER_RECIPIENT_COUNT:
            labels[wallet].add("DEV_SPLITTER_DETECTED")
            splitter_wallets.add(wallet)

        sold = sum(safe_float(edge["amount"]) for edge in sell_edges)
        inbound = recipient_in_amount.get(wallet, 0.0)
        if sold > 0 and (inbound <= 0 or sold / inbound >= PROXY_DUMP_RATIO):
            labels[wallet].add("DEV_PROXY_DUMP")
            proxy_dump_wallets.add(wallet)
            proxy_sold_amount += sold

        all_edges.extend(wallet_edges)

        for edge in transfer_edges:
            second_degree_candidates[edge["to_wallet"]] += safe_float(edge["amount"])
            recipient_in_amount[edge["to_wallet"]] = recipient_in_amount.get(edge["to_wallet"], 0.0) + safe_float(edge["amount"])

    second_degree_wallets = top_recipients(
        dict(second_degree_candidates),
        threshold_amount,
        MAX_SECOND_DEGREE_RECIPIENTS,
    )

    for wallet in second_degree_wallets:
        labels[wallet].add("DEV_SECOND_DEGREE_RECIPIENT")
        wallet_edges = collect_transfer_edges(
            wallet,
            token_address,
            wallet_transactions.get(wallet, []),
            degree=3,
        )
        sell_edges = [edge for edge in wallet_edges if edge["edge_type"] == "SELL"]
        sold = sum(safe_float(edge["amount"]) for edge in sell_edges)
        inbound = recipient_in_amount.get(wallet, 0.0)

        if sold > 0 and (inbound <= 0 or sold / inbound >= PROXY_DUMP_RATIO):
            labels[wallet].add("DEV_PROXY_DUMP")
            proxy_dump_wallets.add(wallet)
            proxy_sold_amount += sold

        all_edges.extend(wallet_edges)

    direct_total = sum(direct_amounts.get(wallet, 0.0) for wallet in direct_wallets)
    direct_pct = direct_total / estimated_initial * 100 if estimated_initial > 0 else 0
    shadow_score = 0.0
    warnings = []
    reasons = []

    if direct_pct >= 20:
        shadow_score += 25
        warnings.append("DEV_DISTRIBUTED_OVER_20_PERCENT")
        reasons.append(f"Developer distributed {round(direct_pct, 2)}% to tracked wallets")
    elif direct_pct >= 5:
        shadow_score += 12
        warnings.append("DEV_DISTRIBUTED_OVER_5_PERCENT")
        reasons.append(f"Developer distributed {round(direct_pct, 2)}% to tracked wallets")

    if splitter_wallets:
        shadow_score += min(50, len(splitter_wallets) * 50)
        warnings.append("DEV_SPLITTER_DETECTED")
        reasons.append(f"{len(splitter_wallets)} developer-linked splitter wallet(s)")

    if proxy_dump_wallets:
        shadow_score += min(50, len(proxy_dump_wallets) * 45)
        warnings.append("DEV_PROXY_DUMP")
        reasons.append(f"{len(proxy_dump_wallets)} developer-linked wallet(s) dumped")

    if direct_wallets and not proxy_dump_wallets and not splitter_wallets:
        warnings.append("DEV_DIRECT_SHIELD")
        reasons.append(f"{len(direct_wallets)} significant direct recipient wallet(s)")

    shadow_score = int(max(0, min(100, round(shadow_score))))

    if shadow_score >= 70:
        status = "DEV_FLOW_DANGER"
        passed = False
        reason = "; ".join(reasons) or "Dangerous developer flow detected"
    elif shadow_score >= 30:
        status = "DEV_FLOW_WARNING"
        passed = True
        reason = "; ".join(reasons) or "Developer-linked flow needs review"
    elif direct_wallets:
        status = "DEV_FLOW_PASS"
        passed = True
        reason = "Developer-linked recipient flow has no strong dump/split pattern"
    else:
        status = "DEV_FLOW_PASS"
        passed = True
        reason = "No significant developer recipient flow detected"

    return {
        "flow_status": status,
        "flow_pass": passed,
        "flow_reason": reason,
        "shadow_dev_score": shadow_score,
        "direct_recipient_count": len(direct_wallets),
        "tracked_wallet_count": len(set(direct_wallets + second_degree_wallets)),
        "proxy_dump_count": len(proxy_dump_wallets),
        "splitter_count": len(splitter_wallets),
        "total_direct_amount": round(direct_total, 6),
        "proxy_sold_amount": round(proxy_sold_amount, 6),
        "warnings": sorted(set(warnings)),
        "edges": all_edges,
        "details": {
            "estimated_initial_balance": round(estimated_initial, 6),
            "threshold_amount": round(threshold_amount, 6),
            "threshold_supply_pct": MIN_RECEIVED_SUPPLY_PCT,
            "max_depth": MAX_DEPTH,
            "max_direct_recipients": MAX_DIRECT_RECIPIENTS,
            "max_second_degree_recipients": MAX_SECOND_DEGREE_RECIPIENTS,
            "labels": {wallet: sorted(values) for wallet, values in labels.items()},
            "tracked_wallets": sorted(set(direct_wallets + second_degree_wallets)),
        },
    }


async def get_dev_flow_inputs(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        c.run_id,
        c.token_id,
        c.pair_id,
        t.symbol,
        t.address AS token_address,
        c.raw_json,
        c.raw_json->>'creator' AS dev_wallet_address,
        NULLIF(c.raw_json->>'creatorBalance', '')::numeric AS creator_balance
    FROM contract_risk_results c
    JOIN tokens t
        ON t.id = c.token_id
    WHERE c.run_id = (
        SELECT MAX(id)
        FROM ingestion_runs
    )
    ORDER BY c.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [dict(row) for row in rows]


async def fetch_transactions(client: HeliusClient, wallet: str) -> list[dict[str, Any]]:
    try:
        return await client.get_address_transactions(wallet, limit=MAX_TX_PER_WALLET)
    except (httpx.HTTPError, RuntimeError, json.JSONDecodeError):
        return []


async def fetch_wallet_transactions(
    client: HeliusClient,
    wallets: list[str],
) -> dict[str, list[dict[str, Any]]]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    results: dict[str, list[dict[str, Any]]] = {}

    async def fetch_one(wallet: str) -> None:
        async with semaphore:
            results[wallet] = await fetch_transactions(client, wallet)

    await asyncio.gather(*(fetch_one(wallet) for wallet in wallets))
    return results


async def save_dev_wallet_flow_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    result_sql = """
    INSERT INTO dev_wallet_flow_results (
        run_id,
        token_id,
        pair_id,
        dev_wallet_address,
        flow_status,
        flow_pass,
        flow_reason,
        shadow_dev_score,
        direct_recipient_count,
        tracked_wallet_count,
        proxy_dump_count,
        splitter_count,
        total_direct_amount,
        proxy_sold_amount,
        warnings,
        details
    )
    VALUES (
        $1, $2, $3, $4,
        $5, $6, $7, $8,
        $9, $10, $11, $12,
        $13, $14,
        $15::jsonb, $16::jsonb
    )
    ON CONFLICT (run_id, token_id)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,
        dev_wallet_address = EXCLUDED.dev_wallet_address,
        flow_status = EXCLUDED.flow_status,
        flow_pass = EXCLUDED.flow_pass,
        flow_reason = EXCLUDED.flow_reason,
        shadow_dev_score = EXCLUDED.shadow_dev_score,
        direct_recipient_count = EXCLUDED.direct_recipient_count,
        tracked_wallet_count = EXCLUDED.tracked_wallet_count,
        proxy_dump_count = EXCLUDED.proxy_dump_count,
        splitter_count = EXCLUDED.splitter_count,
        total_direct_amount = EXCLUDED.total_direct_amount,
        proxy_sold_amount = EXCLUDED.proxy_sold_amount,
        warnings = EXCLUDED.warnings,
        details = EXCLUDED.details,
        created_at = NOW()
    RETURNING *;
    """

    delete_edges_sql = """
    DELETE FROM dev_wallet_flow_edges
    WHERE run_id = $1
      AND token_id = $2;
    """

    insert_edge_sql = """
    INSERT INTO dev_wallet_flow_edges (
        run_id,
        token_id,
        pair_id,
        from_wallet,
        to_wallet,
        degree,
        amount,
        edge_type,
        tx_type,
        signature,
        timestamp
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);
    """

    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        **result["details"],
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            saved = await conn.fetchrow(
                result_sql,
                row["run_id"],
                row["token_id"],
                row["pair_id"],
                row.get("dev_wallet_address"),
                result["flow_status"],
                result["flow_pass"],
                result["flow_reason"],
                result["shadow_dev_score"],
                result["direct_recipient_count"],
                result["tracked_wallet_count"],
                result["proxy_dump_count"],
                result["splitter_count"],
                result["total_direct_amount"],
                result["proxy_sold_amount"],
                json.dumps(result["warnings"]),
                json.dumps(details, default=str),
            )

            await conn.execute(delete_edges_sql, row["run_id"], row["token_id"])

            for edge in result["edges"]:
                await conn.execute(
                    insert_edge_sql,
                    row["run_id"],
                    row["token_id"],
                    row["pair_id"],
                    edge["from_wallet"],
                    edge["to_wallet"],
                    edge["degree"],
                    edge["amount"],
                    edge["edge_type"],
                    edge.get("tx_type"),
                    edge.get("signature"),
                    edge.get("timestamp"),
                )

    return dict(saved)


async def run_dev_wallet_flow_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await get_dev_flow_inputs(pool)
    client = HeliusClient()
    results = []

    for row in rows:
        raw_json = normalize_json(row.get("raw_json"))
        dev_wallet = row.get("dev_wallet_address") or extract_dev_wallet(raw_json)
        row["dev_wallet_address"] = dev_wallet
        dev_transactions = await fetch_transactions(client, dev_wallet) if dev_wallet else []

        estimated_initial = estimate_initial_dev_balance(
            dev_wallet=dev_wallet,
            token_address=row["token_address"],
            creator_balance=safe_float(row.get("creator_balance")),
            dev_transactions=dev_transactions,
        ) if dev_wallet else 0
        threshold_amount = estimated_initial * (MIN_RECEIVED_SUPPLY_PCT / 100) if estimated_initial > 0 else 0
        direct_edges = collect_transfer_edges(dev_wallet, row["token_address"], dev_transactions, degree=1) if dev_wallet else []
        direct_wallets = top_recipients(
            aggregate_inbound_amount(direct_edges),
            threshold_amount,
            MAX_DIRECT_RECIPIENTS,
        )
        first_degree_transactions = await fetch_wallet_transactions(client, direct_wallets)

        second_degree_amounts: dict[str, float] = defaultdict(float)
        for wallet, transactions in first_degree_transactions.items():
            for edge in collect_transfer_edges(wallet, row["token_address"], transactions, degree=2):
                if edge["edge_type"] == "TRANSFER":
                    second_degree_amounts[edge["to_wallet"]] += safe_float(edge["amount"])

        second_degree_wallets = top_recipients(
            dict(second_degree_amounts),
            threshold_amount,
            MAX_SECOND_DEGREE_RECIPIENTS,
        )
        second_degree_transactions = await fetch_wallet_transactions(client, second_degree_wallets)
        wallet_transactions = {**first_degree_transactions, **second_degree_transactions}

        result = analyze_dev_wallet_flow(
            dev_wallet=dev_wallet,
            token_address=row["token_address"],
            creator_balance=safe_float(row.get("creator_balance")),
            dev_transactions=dev_transactions,
            wallet_transactions=wallet_transactions,
        )

        saved = await save_dev_wallet_flow_result(pool, row, result)
        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")
        results.append(saved)

    return results

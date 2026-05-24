import json
from typing import Any

import asyncpg
import httpx

try:
    from helius import HeliusClient
except ModuleNotFoundError:
    from app.helius import HeliusClient


def normalize_json(value) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    return {}


def safe_float(value) -> float:
    if value is None:
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def token_transfer_mint(transfer: dict[str, Any]) -> str | None:
    return (
        transfer.get("mint")
        or transfer.get("mintAddress")
        or transfer.get("tokenMint")
    )


def token_transfer_amount(transfer: dict[str, Any]) -> float:
    return safe_float(
        transfer.get("tokenAmount")
        or transfer.get("amount")
        or transfer.get("rawTokenAmount", {}).get("tokenAmount")
    )


def extract_dev_wallet(raw_json: dict[str, Any]) -> str | None:
    token = normalize_json(raw_json.get("token"))
    token_meta = normalize_json(raw_json.get("tokenMeta"))

    creator = (
        raw_json.get("creator")
        or raw_json.get("deployer")
        or raw_json.get("creatorAddress")
        or token.get("creator")
        or token.get("updateAuthority")
        or token_meta.get("creator")
        or token_meta.get("updateAuthority")
    )

    return creator if isinstance(creator, str) and creator else None


def analyze_dev_wallet_transactions(
    dev_wallet: str | None,
    token_address: str,
    creator_balance: float | None,
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    if not dev_wallet:
        return {
            "dev_audit_status": "DEV_UNKNOWN",
            "dev_audit_pass": False,
            "dev_audit_reason": "Developer wallet is unknown",
            "current_balance": creator_balance,
            "total_token_in": 0,
            "total_token_out": 0,
            "sold_token_amount": 0,
            "transferred_token_amount": 0,
            "sell_transaction_count": 0,
            "transfer_transaction_count": 0,
            "warnings": ["DEV_WALLET_UNKNOWN"],
            "details": {"recent_events": []},
        }

    total_token_in = 0.0
    sold_token_amount = 0.0
    transferred_token_amount = 0.0
    sell_transaction_count = 0
    transfer_transaction_count = 0
    recent_events = []

    for tx in transactions:
        token_transfers = tx.get("tokenTransfers") or []
        if not isinstance(token_transfers, list):
            continue

        tx_type = str(tx.get("type") or "").upper()
        signature = tx.get("signature")
        timestamp = tx.get("timestamp")

        for transfer in token_transfers:
            if not isinstance(transfer, dict):
                continue

            if token_transfer_mint(transfer) != token_address:
                continue

            amount = token_transfer_amount(transfer)
            from_account = transfer.get("fromUserAccount")
            to_account = transfer.get("toUserAccount")

            if to_account == dev_wallet:
                total_token_in += amount

            if from_account != dev_wallet or amount <= 0:
                continue

            is_swap = tx_type == "SWAP"
            if is_swap:
                sold_token_amount += amount
                sell_transaction_count += 1
                event_type = "SELL"
            else:
                transferred_token_amount += amount
                transfer_transaction_count += 1
                event_type = "TRANSFER_OUT"

            if len(recent_events) < 10:
                recent_events.append(
                    {
                        "type": event_type,
                        "amount": round(amount, 6),
                        "to": to_account,
                        "timestamp": timestamp,
                        "signature": signature,
                    }
                )

    total_token_out = sold_token_amount + transferred_token_amount
    current_balance = creator_balance
    warnings = []

    estimated_initial = max(total_token_in, total_token_out + safe_float(current_balance))
    sold_percent = None
    out_percent = None
    if estimated_initial > 0:
        sold_percent = sold_token_amount / estimated_initial * 100
        out_percent = total_token_out / estimated_initial * 100

    if sold_token_amount > 0:
        warnings.append("DEV_SOLD_TOKENS")

    if transferred_token_amount > 0:
        warnings.append("DEV_TRANSFERRED_TOKENS")

    if current_balance == 0 and (total_token_out > 0 or total_token_in > 0):
        warnings.append("DEV_BALANCE_ZERO")

    if sold_percent is not None and sold_percent >= 80:
        status = "DEV_SOLD_OUT"
        passed = False
        reason = "Developer appears to have sold most received tokens"
    elif sold_token_amount > 0:
        status = "DEV_SOLD_PARTIAL"
        passed = False
        reason = "Developer sold some tokens"
    elif transferred_token_amount > 0:
        status = "DEV_TRANSFERRED_TOKENS"
        passed = False
        reason = "Developer moved tokens to other wallets"
    elif current_balance == 0:
        status = "DEV_NO_BALANCE"
        passed = False
        reason = "Developer wallet currently has zero creator balance"
        warnings.append("DEV_BALANCE_ZERO")
    else:
        status = "DEV_HOLDING"
        passed = True
        reason = "No developer sell transaction detected in fetched history"

    return {
        "dev_audit_status": status,
        "dev_audit_pass": passed,
        "dev_audit_reason": reason,
        "current_balance": current_balance,
        "total_token_in": round(total_token_in, 6),
        "total_token_out": round(total_token_out, 6),
        "sold_token_amount": round(sold_token_amount, 6),
        "transferred_token_amount": round(transferred_token_amount, 6),
        "sell_transaction_count": sell_transaction_count,
        "transfer_transaction_count": transfer_transaction_count,
        "warnings": sorted(set(warnings)),
        "details": {
            "estimated_initial_balance": round(estimated_initial, 6),
            "sold_percent": round(sold_percent, 2) if sold_percent is not None else None,
            "out_percent": round(out_percent, 2) if out_percent is not None else None,
            "recent_events": recent_events,
            "history_limit": len(transactions),
        },
    }


async def get_dev_audit_inputs(pool: asyncpg.Pool) -> list[dict[str, Any]]:
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


async def save_dev_wallet_audit_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO dev_wallet_audit_results (
        run_id,
        token_id,
        pair_id,
        dev_wallet_address,
        dev_audit_status,
        dev_audit_pass,
        dev_audit_reason,
        current_balance,
        total_token_in,
        total_token_out,
        sold_token_amount,
        transferred_token_amount,
        sell_transaction_count,
        transfer_transaction_count,
        warnings,
        details
    )
    VALUES (
        $1, $2, $3, $4,
        $5, $6, $7,
        $8, $9, $10, $11, $12,
        $13, $14,
        $15::jsonb, $16::jsonb
    )
    ON CONFLICT (run_id, token_id)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,
        dev_wallet_address = EXCLUDED.dev_wallet_address,
        dev_audit_status = EXCLUDED.dev_audit_status,
        dev_audit_pass = EXCLUDED.dev_audit_pass,
        dev_audit_reason = EXCLUDED.dev_audit_reason,
        current_balance = EXCLUDED.current_balance,
        total_token_in = EXCLUDED.total_token_in,
        total_token_out = EXCLUDED.total_token_out,
        sold_token_amount = EXCLUDED.sold_token_amount,
        transferred_token_amount = EXCLUDED.transferred_token_amount,
        sell_transaction_count = EXCLUDED.sell_transaction_count,
        transfer_transaction_count = EXCLUDED.transfer_transaction_count,
        warnings = EXCLUDED.warnings,
        details = EXCLUDED.details,
        created_at = NOW()
    RETURNING *;
    """

    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        **result["details"],
    }

    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            sql,
            row["run_id"],
            row["token_id"],
            row["pair_id"],
            row.get("dev_wallet_address"),
            result["dev_audit_status"],
            result["dev_audit_pass"],
            result["dev_audit_reason"],
            result["current_balance"],
            result["total_token_in"],
            result["total_token_out"],
            result["sold_token_amount"],
            result["transferred_token_amount"],
            result["sell_transaction_count"],
            result["transfer_transaction_count"],
            json.dumps(result["warnings"]),
            json.dumps(details, default=str),
        )

    return dict(saved)


async def run_dev_wallet_audit_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await get_dev_audit_inputs(pool)
    client = HeliusClient()
    results = []

    for row in rows:
        raw_json = normalize_json(row.get("raw_json"))
        dev_wallet = row.get("dev_wallet_address") or extract_dev_wallet(raw_json)
        row["dev_wallet_address"] = dev_wallet

        try:
            transactions = (
                await client.get_address_transactions(dev_wallet, limit=100)
                if dev_wallet
                else []
            )
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError):
            transactions = []

        result = analyze_dev_wallet_transactions(
            dev_wallet=dev_wallet,
            token_address=row["token_address"],
            creator_balance=safe_float(row.get("creator_balance")),
            transactions=transactions,
        )

        saved = await save_dev_wallet_audit_result(pool, row, result)
        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")
        results.append(saved)

    return results

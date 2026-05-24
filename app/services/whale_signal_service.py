import json
from datetime import datetime, timezone
from typing import Any

import asyncpg


def unix_to_datetime(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def detect_signal_type(payload: dict[str, Any], wallet_address: str) -> str:
    token_transfers = payload.get("tokenTransfers") or []
    native_transfers = payload.get("nativeTransfers") or []

    token_in = any(transfer.get("toUserAccount") == wallet_address for transfer in token_transfers)
    token_out = any(transfer.get("fromUserAccount") == wallet_address for transfer in token_transfers)
    native_in = any(transfer.get("toUserAccount") == wallet_address for transfer in native_transfers)
    native_out = any(transfer.get("fromUserAccount") == wallet_address for transfer in native_transfers)

    if token_in and native_out:
        return "BUY"
    if token_out and native_in:
        return "SELL"
    if token_in:
        return "TOKEN_IN"
    if token_out:
        return "TOKEN_OUT"
    return "ACTIVITY"


def extract_signal_amount_sol(payload: dict[str, Any], wallet_address: str, signal_type: str) -> float | None:
    native_transfers = payload.get("nativeTransfers") or []
    amount = 0.0

    for transfer in native_transfers:
        if signal_type == "BUY" and transfer.get("fromUserAccount") == wallet_address:
            amount += float(transfer.get("amount") or 0) / 1_000_000_000
        if signal_type == "SELL" and transfer.get("toUserAccount") == wallet_address:
            amount += float(transfer.get("amount") or 0) / 1_000_000_000

    return amount or None


def extract_token_address(payload: dict[str, Any], wallet_address: str) -> str | None:
    for transfer in payload.get("tokenTransfers") or []:
        if wallet_address in {
            transfer.get("fromUserAccount"),
            transfer.get("toUserAccount"),
        }:
            return transfer.get("mint") or transfer.get("mintAddress") or transfer.get("tokenMint")
    return None


async def save_live_whale_signal(pool: asyncpg.Pool, payload: dict[str, Any]) -> dict[str, Any]:
    wallet_address = str(payload.get("wallet_address") or payload.get("account") or "").strip()
    if not wallet_address:
        accounts = payload.get("accountData") or []
        if accounts and isinstance(accounts[0], dict):
            wallet_address = str(accounts[0].get("account") or "").strip()

    if not wallet_address:
        raise ValueError("wallet_address is required")

    signal_type = str(payload.get("signal_type") or detect_signal_type(payload, wallet_address))
    token_address = payload.get("token_address") or extract_token_address(payload, wallet_address)
    amount_sol = payload.get("amount_sol")
    if amount_sol is None:
        amount_sol = extract_signal_amount_sol(payload, wallet_address, signal_type)

    signature = payload.get("signature")
    signal_at = unix_to_datetime(payload.get("timestamp")) or datetime.now(timezone.utc)

    sql = """
    INSERT INTO live_whale_signals (
        elite_wallet_id,
        wallet_address,
        token_address,
        token_symbol,
        signal_type,
        amount_sol,
        price_usd,
        signature,
        source,
        signal_at,
        raw_json
    )
    VALUES (
        (SELECT id FROM elite_wallets WHERE wallet_address = $1),
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb
    )
    ON CONFLICT (signature) DO UPDATE
    SET raw_json = EXCLUDED.raw_json,
        signal_at = EXCLUDED.signal_at
    RETURNING id, wallet_address, token_address, token_symbol, signal_type, amount_sol, signature, signal_at;
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            wallet_address,
            token_address,
            payload.get("token_symbol"),
            signal_type,
            float(amount_sol) if amount_sol is not None else None,
            float(payload["price_usd"]) if payload.get("price_usd") is not None else None,
            signature,
            payload.get("source") or "helius_webhook",
            signal_at,
            json.dumps(payload, default=str),
        )

    return dict(row)

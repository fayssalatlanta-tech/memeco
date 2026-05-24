from __future__ import annotations

import json
import os
from typing import Any

import asyncpg

try:
    from helius import HeliusClient
except ModuleNotFoundError:
    from app.helius import HeliusClient


WEBHOOK_PROVIDER = "helius"


def webhook_url_from_env() -> str | None:
    return os.getenv("WHALE_WEBHOOK_URL") or os.getenv("HELIUS_WHALE_WEBHOOK_URL")


def webhook_auth_header_from_env() -> str | None:
    return os.getenv("WHALE_WEBHOOK_AUTH_HEADER") or os.getenv("HELIUS_WEBHOOK_AUTH_HEADER")


def webhook_transaction_types_from_env() -> list[str]:
    raw = os.getenv("WHALE_WEBHOOK_TRANSACTION_TYPES", "SWAP")
    values = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return values or ["SWAP"]


async def fetch_elite_wallet_addresses(pool: asyncpg.Pool, limit: int = 100_000) -> list[str]:
    sql = """
    SELECT wallet_address
    FROM elite_wallets
    WHERE bot_flag = FALSE
      AND status <> 'EXCLUDED'
      AND label IN ('ELITE_SMART_MONEY', 'WATCHLIST_CANDIDATE', 'UNPROVEN')
    ORDER BY reliability_score DESC, total_profit_sol DESC
    LIMIT $1;
    """
    async with pool.acquire() as conn:
        return [row["wallet_address"] for row in await conn.fetch(sql, limit)]


async def fetch_latest_webhook_config(pool: asyncpg.Pool) -> dict[str, Any] | None:
    sql = """
    SELECT *
    FROM whale_webhook_configs
    WHERE provider = $1
    ORDER BY updated_at DESC, id DESC
    LIMIT 1;
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, WEBHOOK_PROVIDER)
    return dict(row) if row else None


async def save_webhook_config(
    pool: asyncpg.Pool,
    webhook_url: str,
    account_addresses: list[str],
    transaction_types: list[str],
    response: dict[str, Any] | None = None,
    status: str = "ACTIVE",
    last_error: str | None = None,
) -> dict[str, Any]:
    response = response or {}
    safe_response = dict(response)
    if "authHeader" in safe_response:
        safe_response["authHeader"] = "REDACTED"
    webhook_id = response.get("webhookID") or response.get("webhook_id")
    active = bool(response.get("active", status == "ACTIVE"))
    auth_header = "CONFIGURED" if webhook_auth_header_from_env() else None
    sql = """
    INSERT INTO whale_webhook_configs (
        provider, webhook_id, webhook_url, auth_header, transaction_types,
        account_addresses, active, status, last_error, raw_json, updated_at
    )
    VALUES (
        $1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10::jsonb, NOW()
    )
    ON CONFLICT (webhook_id) DO UPDATE
    SET webhook_url = EXCLUDED.webhook_url,
        auth_header = EXCLUDED.auth_header,
        transaction_types = EXCLUDED.transaction_types,
        account_addresses = EXCLUDED.account_addresses,
        active = EXCLUDED.active,
        status = EXCLUDED.status,
        last_error = EXCLUDED.last_error,
        raw_json = EXCLUDED.raw_json,
        updated_at = NOW()
    RETURNING *;
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            WEBHOOK_PROVIDER,
            webhook_id,
            webhook_url,
            auth_header,
            json.dumps(transaction_types),
            json.dumps(account_addresses),
            active,
            status,
            last_error,
            json.dumps(safe_response),
        )
    return dict(row)


async def sync_whale_webhook(pool: asyncpg.Pool) -> dict[str, Any]:
    webhook_url = webhook_url_from_env()
    if not webhook_url:
        raise RuntimeError(
            "WHALE_WEBHOOK_URL is missing. Helius requires a public HTTPS URL, not localhost."
        )
    if webhook_url.startswith("http://127.0.0.1") or webhook_url.startswith("http://localhost"):
        raise RuntimeError("Helius cannot send webhooks to localhost. Use ngrok or Cloudflare Tunnel.")

    account_addresses = await fetch_elite_wallet_addresses(pool)
    if not account_addresses:
        raise RuntimeError("No elite wallets found to watch yet.")

    transaction_types = webhook_transaction_types_from_env()
    auth_header = webhook_auth_header_from_env()
    client = HeliusClient()
    if not client.is_configured:
        raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

    latest_config = await fetch_latest_webhook_config(pool)
    webhook_id = (latest_config or {}).get("webhook_id")

    if webhook_id:
        response = await client.update_webhook(
            webhook_id=webhook_id,
            webhook_url=webhook_url,
            account_addresses=account_addresses,
            transaction_types=transaction_types,
            auth_header=auth_header,
        )
        action = "updated"
    else:
        response = await client.create_webhook(
            webhook_url=webhook_url,
            account_addresses=account_addresses,
            transaction_types=transaction_types,
            auth_header=auth_header,
        )
        action = "created"

    saved = await save_webhook_config(
        pool,
        webhook_url=webhook_url,
        account_addresses=account_addresses,
        transaction_types=transaction_types,
        response=response,
        status="ACTIVE",
    )

    return {
        "action": action,
        "watched_wallets": len(account_addresses),
        "transaction_types": transaction_types,
        "webhook": saved,
    }

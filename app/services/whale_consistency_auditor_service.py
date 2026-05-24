from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from app.dexscreener import DexScreenerClient, safe_float, safe_int
from app.helius import HeliusClient
from app.whale_scoring_logic import WhaleTrade, classify_elite_wallet, summarize_whale_trades
from app.services.whale_discovery_service import upsert_elite_wallet


LAMPORTS_PER_SOL = 1_000_000_000
AUDIT_SOURCE = "wallet_consistency_audit"


@dataclass(frozen=True)
class WhaleConsistencyConfig:
    wallet_limit: int = 50
    tx_limit: int = 50
    min_profit_sol: float = 0.0

    @classmethod
    def from_env(cls) -> "WhaleConsistencyConfig":
        return cls(
            wallet_limit=_bounded_int("WHALE_AUDIT_WALLET_LIMIT", 50, 1, 200),
            tx_limit=_bounded_int("WHALE_AUDIT_TX_LIMIT", 50, 20, 100),
            min_profit_sol=_bounded_float("WHALE_AUDIT_MIN_PROFIT_SOL", 0.0, -1_000.0, 1_000.0),
        )


@dataclass
class WalletTokenPosition:
    token_address: str
    token_symbol: str | None = None
    first_entry_at: datetime | None = None
    native_spent_sol: float = 0.0
    native_received_sol: float = 0.0
    token_in: float = 0.0
    token_out: float = 0.0
    tx_count: int = 0
    first_signature: str | None = None
    last_signature: str | None = None

    @property
    def net_token_amount(self) -> float:
        return self.token_in - self.token_out


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _dt_from_unix(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _native_spent(native_transfers: list[dict[str, Any]], wallet: str) -> float:
    return sum(
        safe_int(transfer.get("amount"))
        for transfer in native_transfers
        if transfer.get("fromUserAccount") == wallet
    ) / LAMPORTS_PER_SOL


def _native_received(native_transfers: list[dict[str, Any]], wallet: str) -> float:
    return sum(
        safe_int(transfer.get("amount"))
        for transfer in native_transfers
        if transfer.get("toUserAccount") == wallet
    ) / LAMPORTS_PER_SOL


def build_positions_from_transactions(
    wallet_address: str,
    transactions: list[dict[str, Any]],
) -> list[WalletTokenPosition]:
    positions: dict[str, WalletTokenPosition] = {}
    for tx in sorted(transactions, key=lambda item: safe_int(item.get("timestamp"))):
        signature = tx.get("signature")
        tx_at = _dt_from_unix(tx.get("timestamp"))
        token_transfers = tx.get("tokenTransfers") or []
        native_transfers = tx.get("nativeTransfers") or []
        spent = _native_spent(native_transfers, wallet_address)
        received = _native_received(native_transfers, wallet_address)

        for transfer in token_transfers:
            mint = transfer.get("mint") or transfer.get("mintAddress") or transfer.get("tokenMint")
            if not mint:
                continue
            amount = safe_float(transfer.get("tokenAmount"))
            if amount <= 0:
                continue

            position = positions.get(mint)
            if not position:
                position = WalletTokenPosition(
                    token_address=mint,
                    token_symbol=transfer.get("symbol"),
                    first_entry_at=tx_at,
                    first_signature=signature,
                )
                positions[mint] = position

            if transfer.get("toUserAccount") == wallet_address:
                position.token_in += amount
                position.native_spent_sol += spent
                if not position.first_entry_at:
                    position.first_entry_at = tx_at
                if not position.first_signature:
                    position.first_signature = signature

            if transfer.get("fromUserAccount") == wallet_address:
                position.token_out += amount
                position.native_received_sol += received

            position.tx_count += 1
            position.last_signature = signature

    return list(positions.values())


def positions_to_trades(
    positions: list[WalletTokenPosition],
    price_by_token: dict[str, dict[str, Any]],
) -> list[tuple[WalletTokenPosition, WhaleTrade]]:
    trades = []
    for position in positions:
        if position.native_spent_sol <= 0:
            continue

        pair = price_by_token.get(position.token_address) or {}
        current_price_native = safe_float(pair.get("priceNative"))
        current_value_sol = max(0.0, position.net_token_amount) * current_price_native
        pnl_sol = position.native_received_sol + current_value_sol - position.native_spent_sol
        roi_percent = (pnl_sol / position.native_spent_sol) * 100 if position.native_spent_sol else None

        trades.append(
            (
                position,
                WhaleTrade(
                    amount_sol=position.native_spent_sol,
                    pnl_sol=pnl_sol,
                    roi_percent=roi_percent,
                    minutes_after_launch=None,
                    tx_per_minute=0.0,
                ),
            )
        )
    return trades


async def fetch_audit_wallets(pool: asyncpg.Pool, limit: int) -> list[str]:
    sql = """
    SELECT wallet_address
    FROM elite_wallets
    WHERE bot_flag = FALSE
      AND status <> 'EXCLUDED'
    ORDER BY reliability_score DESC, total_profit_sol DESC
    LIMIT $1;
    """
    async with pool.acquire() as conn:
        return [row["wallet_address"] for row in await conn.fetch(sql, limit)]


async def fetch_prices_for_positions(
    client: DexScreenerClient,
    positions: list[WalletTokenPosition],
) -> dict[str, dict[str, Any]]:
    token_addresses = list({position.token_address for position in positions})
    prices: dict[str, dict[str, Any]] = {}
    for idx in range(0, len(token_addresses), 30):
        pairs = await client.get_tokens("solana", token_addresses[idx : idx + 30])
        for pair in pairs:
            base_address = (pair.get("baseToken") or {}).get("address")
            if base_address and base_address not in prices:
                prices[base_address] = pair
    return prices


async def upsert_audit_performance(
    conn: asyncpg.Connection,
    elite_wallet_id: int,
    wallet_address: str,
    position: WalletTokenPosition,
    trade: WhaleTrade,
    pair: dict[str, Any] | None,
) -> None:
    base_token = (pair or {}).get("baseToken") or {}
    raw_json = {
        "first_signature": position.first_signature,
        "last_signature": position.last_signature,
        "token_in": position.token_in,
        "token_out": position.token_out,
        "net_token_amount": position.net_token_amount,
        "current_price_native": (pair or {}).get("priceNative"),
        "current_price_usd": (pair or {}).get("priceUsd"),
    }
    current_price_native = safe_float((pair or {}).get("priceNative"))
    current_price_usd = safe_float((pair or {}).get("priceUsd"))
    current_value_sol = max(0.0, position.net_token_amount) * current_price_native

    sql = """
    INSERT INTO whale_performance_tracking (
        elite_wallet_id, wallet_address, token_address, token_symbol, entry_at,
        native_spent_sol, native_received_sol, pnl_sol, roi_percent,
        trade_status, source, raw_json, current_price_usd, current_price_native,
        current_value_sol, current_unrealized_pnl_sol, price_refreshed_at
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9,
        $10, $11, $12::jsonb, $13, $14, $15, $16, NOW()
    )
    ON CONFLICT (wallet_address, token_address, source) DO UPDATE
    SET elite_wallet_id = EXCLUDED.elite_wallet_id,
        token_symbol = EXCLUDED.token_symbol,
        entry_at = EXCLUDED.entry_at,
        native_spent_sol = EXCLUDED.native_spent_sol,
        native_received_sol = EXCLUDED.native_received_sol,
        pnl_sol = EXCLUDED.pnl_sol,
        roi_percent = EXCLUDED.roi_percent,
        trade_status = EXCLUDED.trade_status,
        raw_json = EXCLUDED.raw_json,
        current_price_usd = EXCLUDED.current_price_usd,
        current_price_native = EXCLUDED.current_price_native,
        current_value_sol = EXCLUDED.current_value_sol,
        current_unrealized_pnl_sol = EXCLUDED.current_unrealized_pnl_sol,
        price_refreshed_at = NOW();
    """
    await conn.execute(
        sql,
        elite_wallet_id,
        wallet_address,
        position.token_address,
        base_token.get("symbol") or position.token_symbol,
        position.first_entry_at,
        _decimal_or_none(trade.amount_sol),
        _decimal_or_none(position.native_received_sol),
        _decimal_or_none(trade.pnl_sol),
        _decimal_or_none(trade.roi_percent),
        "AUDITED_PROFITABLE" if (trade.pnl_sol or 0) > 0 else "AUDITED_LOSS",
        AUDIT_SOURCE,
        json.dumps(raw_json),
        _decimal_or_none(current_price_usd) if current_price_usd else None,
        _decimal_or_none(current_price_native) if current_price_native else None,
        _decimal_or_none(current_value_sol),
        _decimal_or_none(trade.pnl_sol),
    )


async def audit_wallet(
    pool: asyncpg.Pool,
    helius: HeliusClient,
    dex_client: DexScreenerClient,
    wallet_address: str,
    config: WhaleConsistencyConfig,
) -> dict[str, Any]:
    transactions = await helius.get_address_transactions(wallet_address, limit=config.tx_limit)
    positions = build_positions_from_transactions(wallet_address, transactions)
    prices = await fetch_prices_for_positions(dex_client, positions)
    trade_pairs = positions_to_trades(positions, prices)
    trades = [trade for _, trade in trade_pairs]
    summary = summarize_whale_trades(trades)
    label = classify_elite_wallet(summary)

    async with pool.acquire() as conn:
        async with conn.transaction():
            elite_wallet_id = await upsert_elite_wallet(
                conn,
                wallet_address,
                summary,
                label,
                source=AUDIT_SOURCE,
            )
            for position, trade in trade_pairs:
                if (trade.pnl_sol or 0) < config.min_profit_sol:
                    continue
                await upsert_audit_performance(
                    conn,
                    elite_wallet_id,
                    wallet_address,
                    position,
                    trade,
                    prices.get(position.token_address),
                )

    return {
        "wallet_address": wallet_address,
        "transactions_checked": len(transactions),
        "positions_found": len(positions),
        "trades_scored": len(trades),
        "label": label,
        **summary,
    }


async def run_whale_consistency_audit(
    pool: asyncpg.Pool,
    config: WhaleConsistencyConfig | None = None,
) -> dict[str, Any]:
    config = config or WhaleConsistencyConfig.from_env()
    helius = HeliusClient()
    if not helius.is_configured:
        raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

    dex_client = DexScreenerClient()
    wallets = await fetch_audit_wallets(pool, config.wallet_limit)
    results = []
    for wallet_address in wallets:
        results.append(await audit_wallet(pool, helius, dex_client, wallet_address, config))

    return {
        "wallets_found": len(wallets),
        "wallets_audited": len(results),
        "elite_wallets": sum(1 for item in results if item["label"] == "ELITE_SMART_MONEY"),
        "config": config.__dict__,
        "results": results,
    }

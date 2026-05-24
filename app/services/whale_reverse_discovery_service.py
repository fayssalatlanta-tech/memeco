from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from app.dexscreener import (
    DexScreenerClient,
    dedupe_latest_candidates,
    safe_float,
    safe_int,
    select_preferred_pair,
)
from app.helius import HeliusClient
from app.whale_scoring_logic import WhaleTrade, classify_elite_wallet, summarize_whale_trades
from app.services.whale_discovery_service import upsert_elite_wallet


LAMPORTS_PER_SOL = 1_000_000_000
REVERSE_DISCOVERY_SOURCE = "reverse_profit_discovery"


@dataclass(frozen=True)
class WhaleReverseDiscoveryConfig:
    target_limit: int = 10
    candidate_pool_limit: int = 30
    signature_limit: int = 180
    early_buyer_limit: int = 50
    min_profit_sol: float = 10.0
    max_target_age_hours: int = 24

    @classmethod
    def from_env(cls) -> "WhaleReverseDiscoveryConfig":
        return cls(
            target_limit=_bounded_int("WHALE_TOP_GAINER_LIMIT", 10, 1, 30),
            candidate_pool_limit=_bounded_int("WHALE_TOP_GAINER_CANDIDATE_POOL", 30, 5, 120),
            signature_limit=_bounded_int("WHALE_SIGNATURE_LIMIT", 180, 25, 500),
            early_buyer_limit=_bounded_int("WHALE_EARLY_BUYER_LIMIT", 50, 10, 100),
            min_profit_sol=_bounded_float("WHALE_MIN_PROFIT_SOL", 10.0, 0.1, 1_000.0),
            max_target_age_hours=_bounded_int("WHALE_TOP_GAINER_MAX_AGE_HOURS", 24, 1, 168),
        )


@dataclass
class DexGainerTarget:
    token_id: int | None
    pair_id: int | None
    chain: str
    token_address: str
    token_symbol: str | None
    pair_address: str
    price_native: float
    price_usd: float | None
    price_change_24h_percent: float
    volume_24h_usd: float
    liquidity_usd: float
    pair_created_at: datetime | None
    raw_json: dict[str, Any]


@dataclass
class EarlyBuyerPosition:
    wallet_address: str
    first_entry_at: datetime | None
    first_signature: str | None
    minutes_after_launch: float | None
    native_spent_sol: float = 0.0
    native_received_sol: float = 0.0
    token_in: float = 0.0
    token_out: float = 0.0
    tx_count: int = 0

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


def _dt_from_ms(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _dt_from_unix(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds() / 60)


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def target_from_pair(
    pair: dict[str, Any],
    token_id: int | None = None,
    pair_id: int | None = None,
) -> DexGainerTarget | None:
    if not pair.get("pairAddress"):
        return None

    base_token = pair.get("baseToken") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}
    price_change = pair.get("priceChange") or {}
    token_address = base_token.get("address")
    if not token_address:
        return None

    return DexGainerTarget(
        token_id=token_id,
        pair_id=pair_id,
        chain=pair.get("chainId") or "solana",
        token_address=token_address,
        token_symbol=base_token.get("symbol"),
        pair_address=pair["pairAddress"],
        price_native=safe_float(pair.get("priceNative")),
        price_usd=safe_float(pair.get("priceUsd")) or None,
        price_change_24h_percent=safe_float(price_change.get("h24")),
        volume_24h_usd=safe_float(volume.get("h24")),
        liquidity_usd=safe_float(liquidity.get("usd")),
        pair_created_at=_dt_from_ms(pair.get("pairCreatedAt")),
        raw_json=pair,
    )


async def fetch_recent_token_candidates(
    pool: asyncpg.Pool,
    limit: int,
    max_age_hours: int,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        t.id AS token_id,
        t.address AS token_address,
        p.id AS pair_id,
        p.pair_address
    FROM tokens t
    JOIN token_pairs p
        ON p.token_id = t.id
    WHERE t.chain = 'solana'
      AND p.pair_address IS NOT NULL
      AND p.dex_id IS DISTINCT FROM 'pumpfun'
      AND p.pair_created_at >= NOW() - make_interval(hours => $2::int)
    ORDER BY p.pair_created_at DESC NULLS LAST
    LIMIT $1;
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, limit, max_age_hours)
    return [dict(row) for row in rows]


async def fetch_dexscreener_top_gainer_targets(
    pool: asyncpg.Pool,
    client: DexScreenerClient,
    config: WhaleReverseDiscoveryConfig,
) -> list[DexGainerTarget]:
    candidates = await fetch_recent_token_candidates(
        pool,
        limit=config.candidate_pool_limit,
        max_age_hours=config.max_target_age_hours,
    )
    by_token = {row["token_address"]: row for row in candidates}

    refreshed_pairs: list[dict[str, Any]] = []
    token_addresses = list(by_token)
    for idx in range(0, len(token_addresses), 30):
        refreshed_pairs.extend(await client.get_tokens("solana", token_addresses[idx : idx + 30]))

    targets: list[DexGainerTarget] = []
    grouped_pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in refreshed_pairs:
        base_address = ((pair.get("baseToken") or {}).get("address"))
        if base_address:
            grouped_pairs[base_address].append(pair)

    for token_address, pairs in grouped_pairs.items():
        selected_pair = select_preferred_pair(pairs, "solana")
        if not selected_pair:
            continue
        candidate = by_token.get(token_address, {})
        target = target_from_pair(
            selected_pair,
            token_id=candidate.get("token_id"),
            pair_id=candidate.get("pair_id"),
        )
        if target and target.price_change_24h_percent > 0:
            targets.append(target)

    targets = sorted(
        targets,
        key=lambda item: (
            item.price_change_24h_percent,
            item.volume_24h_usd,
            item.liquidity_usd,
        ),
        reverse=True,
    )

    if len(targets) < config.target_limit:
        live_targets = await fetch_live_dexscreener_candidate_targets(client, config)
        existing_pairs = {target.pair_address for target in targets}
        targets.extend(
            target for target in live_targets if target.pair_address not in existing_pairs
        )

    return sorted(
        targets,
        key=lambda item: (
            item.price_change_24h_percent,
            item.volume_24h_usd,
            item.liquidity_usd,
        ),
        reverse=True,
    )[: config.target_limit]


async def fetch_live_dexscreener_candidate_targets(
    client: DexScreenerClient,
    config: WhaleReverseDiscoveryConfig,
) -> list[DexGainerTarget]:
    profiles = await client.get_latest_profiles()
    community_takeovers = await client.get_latest_community_takeovers()
    latest_ads = await client.get_latest_ads()
    latest_boosts = await client.get_latest_boosted_tokens()
    top_boosts = await client.get_top_boosted_tokens()

    candidates = dedupe_latest_candidates(
        [
            ("profile", profiles),
            ("community_takeover", community_takeovers),
            ("ad", latest_ads),
            ("boost_latest", latest_boosts),
            ("boost_top", top_boosts),
        ],
        chain_id="solana",
    )

    targets = []
    for candidate in candidates[: config.candidate_pool_limit]:
        pair = await client.get_preferred_token_pair("solana", candidate["tokenAddress"])
        if not pair:
            continue
        target = target_from_pair(pair)
        if target and target.price_change_24h_percent > 0:
            targets.append(target)

    return sorted(
        targets,
        key=lambda item: (
            item.price_change_24h_percent,
            item.volume_24h_usd,
            item.liquidity_usd,
        ),
        reverse=True,
    )


def extract_early_buyer_positions(
    target: DexGainerTarget,
    transactions: list[dict[str, Any]],
    early_buyer_limit: int,
) -> list[EarlyBuyerPosition]:
    positions: dict[str, EarlyBuyerPosition] = {}
    sorted_transactions = sorted(transactions, key=lambda tx: safe_int(tx.get("timestamp")))

    for tx in sorted_transactions:
        signature = tx.get("signature")
        tx_time = _dt_from_unix(tx.get("timestamp"))
        token_transfers = tx.get("tokenTransfers") or []
        native_transfers = tx.get("nativeTransfers") or []

        for transfer in token_transfers:
            if transfer.get("mint") != target.token_address:
                continue

            amount = safe_float(transfer.get("tokenAmount"))
            if amount <= 0:
                continue

            buyer = transfer.get("toUserAccount")
            seller = transfer.get("fromUserAccount")

            if buyer:
                position = positions.get(buyer)
                if not position and len(positions) < early_buyer_limit:
                    position = EarlyBuyerPosition(
                        wallet_address=buyer,
                        first_entry_at=tx_time,
                        first_signature=signature,
                        minutes_after_launch=_minutes_between(target.pair_created_at, tx_time),
                    )
                    positions[buyer] = position
                if position:
                    position.token_in += amount
                    position.native_spent_sol += native_spent_by_wallet(native_transfers, buyer)
                    position.tx_count += 1

            if seller and seller in positions:
                positions[seller].token_out += amount
                positions[seller].native_received_sol += native_received_by_wallet(native_transfers, seller)
                positions[seller].tx_count += 1

    return list(positions.values())[:early_buyer_limit]


def native_spent_by_wallet(native_transfers: list[dict[str, Any]], wallet: str) -> float:
    lamports = sum(
        safe_int(transfer.get("amount"))
        for transfer in native_transfers
        if transfer.get("fromUserAccount") == wallet
    )
    return lamports / LAMPORTS_PER_SOL


def native_received_by_wallet(native_transfers: list[dict[str, Any]], wallet: str) -> float:
    lamports = sum(
        safe_int(transfer.get("amount"))
        for transfer in native_transfers
        if transfer.get("toUserAccount") == wallet
    )
    return lamports / LAMPORTS_PER_SOL


def position_to_trade(position: EarlyBuyerPosition, target: DexGainerTarget) -> WhaleTrade | None:
    if position.native_spent_sol <= 0:
        return None

    unrealized_value_sol = max(0.0, position.net_token_amount) * target.price_native
    pnl_sol = position.native_received_sol + unrealized_value_sol - position.native_spent_sol
    roi_percent = (pnl_sol / position.native_spent_sol) * 100 if position.native_spent_sol else None
    tx_per_minute = 0.0
    if position.minutes_after_launch and position.minutes_after_launch > 0:
        tx_per_minute = position.tx_count / max(1.0, position.minutes_after_launch)

    return WhaleTrade(
        amount_sol=position.native_spent_sol,
        pnl_sol=pnl_sol,
        roi_percent=roi_percent,
        minutes_after_launch=position.minutes_after_launch,
        tx_per_minute=tx_per_minute,
    )


async def fetch_pair_transactions(
    helius: HeliusClient,
    pair_address: str,
    signature_limit: int,
    launch_at: datetime | None = None,
) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []
    before = None
    launch_ts = int(launch_at.timestamp()) if launch_at else None

    while len(signatures) < signature_limit:
        page = await helius.get_signatures_for_address(
            pair_address,
            limit=min(100, signature_limit - len(signatures)),
            before=before,
        )
        if not page:
            break
        signatures.extend(page)
        before = page[-1].get("signature")

        oldest_block_time = page[-1].get("blockTime")
        if launch_ts and oldest_block_time and oldest_block_time <= launch_ts:
            break
        if len(page) < 100:
            break

    signature_values = [
        item.get("signature")
        for item in reversed(signatures)
        if item.get("signature") and not item.get("err")
    ]
    transactions: list[dict[str, Any]] = []
    for idx in range(0, len(signature_values), 100):
        transactions.extend(await helius.get_enhanced_transactions(signature_values[idx : idx + 100]))
    return transactions


async def upsert_whale_discovery_target(
    conn: asyncpg.Connection,
    target: DexGainerTarget,
    status: str,
    buyers_checked: int,
    profitable_buyers: int,
    promoted_wallets: int,
) -> int:
    sql = """
    INSERT INTO whale_discovery_targets (
        token_id, pair_id, chain, token_address, token_symbol, pair_address,
        price_native, price_usd, price_change_24h_percent, volume_24h_usd,
        liquidity_usd, pair_created_at, source, status, buyers_checked,
        profitable_buyers, promoted_wallets, raw_json, last_analyzed_at
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
        $11, $12, 'dexscreener_recent_gainers', $13, $14,
        $15, $16, $17::jsonb, NOW()
    )
    ON CONFLICT (pair_address, source) DO UPDATE
    SET token_id = EXCLUDED.token_id,
        pair_id = EXCLUDED.pair_id,
        token_symbol = EXCLUDED.token_symbol,
        price_native = EXCLUDED.price_native,
        price_usd = EXCLUDED.price_usd,
        price_change_24h_percent = EXCLUDED.price_change_24h_percent,
        volume_24h_usd = EXCLUDED.volume_24h_usd,
        liquidity_usd = EXCLUDED.liquidity_usd,
        pair_created_at = EXCLUDED.pair_created_at,
        status = EXCLUDED.status,
        buyers_checked = EXCLUDED.buyers_checked,
        profitable_buyers = EXCLUDED.profitable_buyers,
        promoted_wallets = EXCLUDED.promoted_wallets,
        raw_json = EXCLUDED.raw_json,
        last_analyzed_at = NOW()
    RETURNING id;
    """
    return await conn.fetchval(
        sql,
        target.token_id,
        target.pair_id,
        target.chain,
        target.token_address,
        target.token_symbol,
        target.pair_address,
        _decimal_or_none(target.price_native),
        _decimal_or_none(target.price_usd),
        _decimal_or_none(target.price_change_24h_percent),
        _decimal_or_none(target.volume_24h_usd),
        _decimal_or_none(target.liquidity_usd),
        target.pair_created_at,
        status,
        buyers_checked,
        profitable_buyers,
        promoted_wallets,
        json.dumps(target.raw_json),
    )


async def upsert_reverse_performance_row(
    conn: asyncpg.Connection,
    elite_wallet_id: int,
    target: DexGainerTarget,
    position: EarlyBuyerPosition,
    trade: WhaleTrade,
) -> None:
    sql = """
    INSERT INTO whale_performance_tracking (
        elite_wallet_id, wallet_address, token_id, pair_id, token_address,
        token_symbol, entry_at, minutes_after_launch, native_spent_sol,
        native_received_sol, pnl_sol, roi_percent, trade_status, source, raw_json
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8,
        $9, $10, $11, $12, $13, $14, $15::jsonb
    )
    ON CONFLICT (wallet_address, token_address, source) DO UPDATE
    SET elite_wallet_id = EXCLUDED.elite_wallet_id,
        token_id = EXCLUDED.token_id,
        pair_id = EXCLUDED.pair_id,
        token_symbol = EXCLUDED.token_symbol,
        entry_at = EXCLUDED.entry_at,
        minutes_after_launch = EXCLUDED.minutes_after_launch,
        native_spent_sol = EXCLUDED.native_spent_sol,
        native_received_sol = EXCLUDED.native_received_sol,
        pnl_sol = EXCLUDED.pnl_sol,
        roi_percent = EXCLUDED.roi_percent,
        trade_status = EXCLUDED.trade_status,
        raw_json = EXCLUDED.raw_json;
    """
    trade_status = "PROFITABLE_EARLY_BUYER" if (trade.pnl_sol or 0) > 0 else "EARLY_BUYER"
    raw_json = {
        "first_signature": position.first_signature,
        "token_in": position.token_in,
        "token_out": position.token_out,
        "net_token_amount": position.net_token_amount,
        "price_native": target.price_native,
        "price_change_24h_percent": target.price_change_24h_percent,
    }
    await conn.execute(
        sql,
        elite_wallet_id,
        position.wallet_address,
        target.token_id,
        target.pair_id,
        target.token_address,
        target.token_symbol,
        position.first_entry_at,
        trade.minutes_after_launch,
        _decimal_or_none(trade.amount_sol),
        _decimal_or_none(position.native_received_sol),
        _decimal_or_none(trade.pnl_sol),
        _decimal_or_none(trade.roi_percent),
        trade_status,
        REVERSE_DISCOVERY_SOURCE,
        json.dumps(raw_json),
    )


async def analyze_target_early_buyers(
    pool: asyncpg.Pool,
    helius: HeliusClient,
    target: DexGainerTarget,
    config: WhaleReverseDiscoveryConfig,
) -> dict[str, Any]:
    transactions = await fetch_pair_transactions(
        helius,
        pair_address=target.pair_address,
        signature_limit=config.signature_limit,
        launch_at=target.pair_created_at,
    )
    positions = extract_early_buyer_positions(
        target,
        transactions=transactions,
        early_buyer_limit=config.early_buyer_limit,
    )

    promoted = []
    profitable_count = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for position in positions:
                trade = position_to_trade(position, target)
                if not trade:
                    continue
                if (trade.pnl_sol or 0) > 0:
                    profitable_count += 1
                if (trade.pnl_sol or 0) < config.min_profit_sol:
                    continue

                existing_rows = await conn.fetch(
                    """
                    SELECT native_spent_sol, pnl_sol, roi_percent, minutes_after_launch, raw_json
                    FROM whale_performance_tracking
                    WHERE wallet_address = $1;
                    """,
                    position.wallet_address,
                )
                trades = [
                    WhaleTrade(
                        amount_sol=float(row["native_spent_sol"] or 0),
                        pnl_sol=float(row["pnl_sol"]) if row["pnl_sol"] is not None else None,
                        roi_percent=float(row["roi_percent"]) if row["roi_percent"] is not None else None,
                        minutes_after_launch=(
                            float(row["minutes_after_launch"])
                            if row["minutes_after_launch"] is not None
                            else None
                        ),
                    )
                    for row in existing_rows
                ]
                trades.append(trade)
                summary = summarize_whale_trades(trades)
                label = classify_elite_wallet(summary)
                elite_wallet_id = await upsert_elite_wallet(
                    conn,
                    position.wallet_address,
                    summary,
                    label,
                    source=REVERSE_DISCOVERY_SOURCE,
                )
                await upsert_reverse_performance_row(conn, elite_wallet_id, target, position, trade)
                promoted.append(
                    {
                        "wallet_address": position.wallet_address,
                        "pnl_sol": round(trade.pnl_sol or 0, 6),
                        "roi_percent": round(trade.roi_percent or 0, 2),
                        "label": label,
                        "reliability_score": summary["reliability_score"],
                    }
                )

            await upsert_whale_discovery_target(
                conn,
                target,
                status="ANALYZED",
                buyers_checked=len(positions),
                profitable_buyers=profitable_count,
                promoted_wallets=len(promoted),
            )

    return {
        "token_address": target.token_address,
        "token_symbol": target.token_symbol,
        "pair_address": target.pair_address,
        "price_change_24h_percent": target.price_change_24h_percent,
        "buyers_checked": len(positions),
        "profitable_buyers": profitable_count,
        "promoted_wallets": len(promoted),
        "promoted": promoted,
    }


async def run_reverse_profit_discovery(
    pool: asyncpg.Pool,
    config: WhaleReverseDiscoveryConfig | None = None,
) -> dict[str, Any]:
    config = config or WhaleReverseDiscoveryConfig.from_env()
    dex_client = DexScreenerClient()
    helius = HeliusClient()
    if not helius.is_configured:
        raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

    targets = await fetch_dexscreener_top_gainer_targets(pool, dex_client, config)
    results = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            for target in targets:
                await upsert_whale_discovery_target(
                    conn,
                    target,
                    status="DISCOVERED",
                    buyers_checked=0,
                    profitable_buyers=0,
                    promoted_wallets=0,
                )

    for target in targets:
        results.append(await analyze_target_early_buyers(pool, helius, target, config))

    return {
        "targets_found": len(targets),
        "targets_analyzed": len(results),
        "promoted_wallets": sum(item["promoted_wallets"] for item in results),
        "config": config.__dict__,
        "results": results,
    }

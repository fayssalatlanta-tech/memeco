from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

import asyncpg

RUG_ROI_THRESHOLD = -90.0
SURVIVAL_MIN_RATE = 80.0
LADDERING_MIN_SELL_COUNT = 2


@dataclass(frozen=True)
class SurvivalTrade:
    wallet_address: str
    token_address: str | None
    token_symbol: str | None
    native_spent_sol: float
    native_received_sol: float
    pnl_sol: float | None
    roi_percent: float | None
    entry_at: Any = None
    exit_at: Any = None
    raw_json: dict[str, Any] | None = None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def parse_json(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def is_rugged_trade(trade: SurvivalTrade) -> bool:
    roi = trade.roi_percent
    if roi is None and trade.native_spent_sol > 0 and trade.pnl_sol is not None:
        roi = (trade.pnl_sol / trade.native_spent_sol) * 100
    if roi is not None and roi <= RUG_ROI_THRESHOLD:
        return True
    if trade.native_spent_sol > 0:
        current_value = safe_float((trade.raw_json or {}).get("current_value_sol"))
        if current_value > 0 and current_value <= trade.native_spent_sol * 0.10:
            return True
    return False


def classify_whale_style(avg_hold_minutes: float | None) -> str:
    if avg_hold_minutes is None:
        return "UNKNOWN"
    if avg_hold_minutes < 5:
        return "SCALPER_SNIPER"
    if avg_hold_minutes < 60:
        return "DAY_TRADER"
    return "SWING_WHALE"


def classify_exit_style(trades: list[SurvivalTrade]) -> tuple[str, float]:
    sell_counts = []
    fully_exited = 0

    for trade in trades:
        raw_json = trade.raw_json or {}
        token_in = safe_float(raw_json.get("token_in"))
        token_out = safe_float(raw_json.get("token_out"))
        sell_count = 1 if trade.native_received_sol > 0 or token_out > 0 else 0
        if token_out > 0 and token_in > 0 and token_out < token_in:
            sell_count = 2
        if token_in > 0 and token_out >= token_in * 0.95:
            fully_exited += 1
        sell_counts.append(sell_count)

    if not sell_counts:
        return "HOLDER", 0.0

    laddered = sum(1 for count in sell_counts if count >= LADDERING_MIN_SELL_COUNT)
    laddering_score = round((laddered / len(sell_counts)) * 100, 2)

    if laddering_score >= 50:
        return "LADDERING_OUT", laddering_score
    if fully_exited >= max(1, len(trades) // 2):
        return "SELL_ALL_AT_ONCE", laddering_score
    return "MIXED_EXIT", laddering_score


def average_hold_minutes(trades: list[SurvivalTrade]) -> float | None:
    values = []
    for trade in trades:
        if trade.entry_at and trade.exit_at:
            values.append(max(0.0, (trade.exit_at - trade.entry_at).total_seconds() / 60))
    return round(mean(values), 2) if values else None


def favorite_symbols(trades: list[SurvivalTrade], limit: int = 5) -> list[str]:
    counter = Counter(
        symbol for symbol in (trade.token_symbol for trade in trades) if symbol
    )
    return [symbol for symbol, _ in counter.most_common(limit)]


def build_survival_profile(
    wallet_address: str,
    trades: list[SurvivalTrade],
    dev_shadow_flag: bool = False,
    dev_shadow_reason: str | None = None,
) -> dict[str, Any]:
    total = len(trades)
    rugged = sum(1 for trade in trades if is_rugged_trade(trade))
    survived = max(0, total - rugged)
    survival_rate = round((survived / total) * 100, 2) if total else 0.0
    avg_hold = average_hold_minutes(trades)
    whale_style = classify_whale_style(avg_hold)
    exit_style, laddering_score = classify_exit_style(trades)
    warning_flags = []

    if total < 5:
        warning_flags.append("INSUFFICIENT_SURVIVAL_DATA")
    if survival_rate < SURVIVAL_MIN_RATE:
        warning_flags.append("LOW_SURVIVAL_RATE")
    if dev_shadow_flag:
        warning_flags.append("DEV_SHADOW_LINK")

    if dev_shadow_flag:
        security_level = "INSIDER_RISK"
    elif total < 5:
        security_level = "UNPROVEN"
    elif survival_rate < SURVIVAL_MIN_RATE:
        security_level = "RISKY"
    else:
        security_level = "SAFE_TO_WATCH"

    return {
        "wallet_address": wallet_address,
        "survival_rate_percent": survival_rate,
        "rugged_trade_count": rugged,
        "survived_trade_count": survived,
        "total_trades_checked": total,
        "avg_hold_minutes": avg_hold,
        "whale_style": whale_style,
        "exit_style": exit_style,
        "laddering_score": laddering_score,
        "dev_shadow_flag": dev_shadow_flag,
        "dev_shadow_reason": dev_shadow_reason,
        "security_level": security_level,
        "warning_flags": warning_flags,
        "favorite_token_symbols": favorite_symbols(trades),
        "details": {
            "rug_roi_threshold": RUG_ROI_THRESHOLD,
            "survival_min_rate": SURVIVAL_MIN_RATE,
            "sampled_trade_count": total,
        },
    }


async def fetch_survival_trades(pool: asyncpg.Pool) -> dict[str, list[SurvivalTrade]]:
    sql = """
    SELECT
        wallet_address,
        token_address,
        token_symbol,
        native_spent_sol,
        native_received_sol,
        COALESCE(current_unrealized_pnl_sol, pnl_sol) AS pnl_sol,
        roi_percent,
        entry_at,
        exit_at,
        raw_json
    FROM whale_performance_tracking
    WHERE wallet_address IS NOT NULL
      AND native_spent_sol > 0
    ORDER BY wallet_address, created_at DESC;
    """
    grouped: dict[str, list[SurvivalTrade]] = defaultdict(list)
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    for row in rows:
        raw_json = parse_json(row["raw_json"], {})
        if row["pnl_sol"] is not None:
            raw_json["current_value_sol"] = safe_float(row["native_received_sol"]) + safe_float(row["pnl_sol"])
        trade = SurvivalTrade(
            wallet_address=row["wallet_address"],
            token_address=row["token_address"],
            token_symbol=row["token_symbol"],
            native_spent_sol=safe_float(row["native_spent_sol"]),
            native_received_sol=safe_float(row["native_received_sol"]),
            pnl_sol=safe_float(row["pnl_sol"]) if row["pnl_sol"] is not None else None,
            roi_percent=safe_float(row["roi_percent"]) if row["roi_percent"] is not None else None,
            entry_at=row["entry_at"],
            exit_at=row["exit_at"],
            raw_json=raw_json,
        )
        grouped[trade.wallet_address].append(trade)

    return grouped


async def upsert_survival_profile(
    conn: asyncpg.Connection,
    profile: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO whale_survival_profiles (
        elite_wallet_id,
        wallet_address,
        survival_rate_percent,
        rugged_trade_count,
        survived_trade_count,
        total_trades_checked,
        avg_hold_minutes,
        whale_style,
        exit_style,
        laddering_score,
        dev_shadow_flag,
        dev_shadow_reason,
        security_level,
        warning_flags,
        favorite_token_symbols,
        details,
        updated_at
    )
    VALUES (
        (SELECT id FROM elite_wallets WHERE wallet_address = $1),
        $1, $2, $3, $4, $5, $6, $7, $8, $9,
        $10, $11, $12, $13::jsonb, $14::jsonb, $15::jsonb, NOW()
    )
    ON CONFLICT (wallet_address) DO UPDATE
    SET elite_wallet_id = EXCLUDED.elite_wallet_id,
        survival_rate_percent = EXCLUDED.survival_rate_percent,
        rugged_trade_count = EXCLUDED.rugged_trade_count,
        survived_trade_count = EXCLUDED.survived_trade_count,
        total_trades_checked = EXCLUDED.total_trades_checked,
        avg_hold_minutes = EXCLUDED.avg_hold_minutes,
        whale_style = EXCLUDED.whale_style,
        exit_style = EXCLUDED.exit_style,
        laddering_score = EXCLUDED.laddering_score,
        dev_shadow_flag = EXCLUDED.dev_shadow_flag,
        dev_shadow_reason = EXCLUDED.dev_shadow_reason,
        security_level = EXCLUDED.security_level,
        warning_flags = EXCLUDED.warning_flags,
        favorite_token_symbols = EXCLUDED.favorite_token_symbols,
        details = EXCLUDED.details,
        updated_at = NOW()
    RETURNING *;
    """
    row = await conn.fetchrow(
        sql,
        profile["wallet_address"],
        profile["survival_rate_percent"],
        profile["rugged_trade_count"],
        profile["survived_trade_count"],
        profile["total_trades_checked"],
        profile["avg_hold_minutes"],
        profile["whale_style"],
        profile["exit_style"],
        profile["laddering_score"],
        profile["dev_shadow_flag"],
        profile["dev_shadow_reason"],
        profile["security_level"],
        json.dumps(profile["warning_flags"]),
        json.dumps(profile["favorite_token_symbols"]),
        json.dumps(profile["details"]),
    )
    return dict(row)


async def run_whale_survival_service(pool: asyncpg.Pool) -> dict[str, Any]:
    grouped = await fetch_survival_trades(pool)
    saved = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            for wallet_address, trades in grouped.items():
                profile = build_survival_profile(wallet_address, trades)
                saved.append(await upsert_survival_profile(conn, profile))

    return {
        "wallets_profiled": len(saved),
        "safe_to_watch": sum(1 for row in saved if row["security_level"] == "SAFE_TO_WATCH"),
        "risky": sum(1 for row in saved if row["security_level"] == "RISKY"),
        "insider_risk": sum(1 for row in saved if row["security_level"] == "INSIDER_RISK"),
        "unproven": sum(1 for row in saved if row["security_level"] == "UNPROVEN"),
    }

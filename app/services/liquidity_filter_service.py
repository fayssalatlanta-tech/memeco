import json
from typing import Any

import asyncpg


SYSTEM_ADDRESS = "11111111111111111111111111111111"


def safe_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


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


def extract_lp_lock_summary(raw_json: dict[str, Any] | None, token_address: str | None = None) -> dict[str, Any]:
    report = normalize_json(raw_json)
    markets = report.get("markets")

    if not isinstance(markets, list) or not markets:
        return {
            "lp_lock_status": "LP_LOCK_UNKNOWN",
            "lp_locked_pct": None,
            "lp_locked_usd": None,
            "lp_unlocked": None,
            "lp_source": "rugcheck",
            "lp_reason": "RugCheck did not return market LP lock data",
        }

    best_market = None
    best_liquidity = -1.0

    for market in markets:
        if not isinstance(market, dict):
            continue

        lp = market.get("lp")
        if not isinstance(lp, dict):
            continue

        if token_address:
            base_mint = lp.get("baseMint") or market.get("mintA")
            quote_mint = lp.get("quoteMint") or market.get("mintB")
            if token_address not in {base_mint, quote_mint}:
                continue

        liquidity_usd = safe_float(lp.get("baseUSD")) or 0
        liquidity_usd += safe_float(lp.get("quoteUSD")) or 0

        if liquidity_usd > best_liquidity:
            best_liquidity = liquidity_usd
            best_market = market

    if not best_market:
        return {
            "lp_lock_status": "LP_LOCK_UNKNOWN",
            "lp_locked_pct": None,
            "lp_locked_usd": None,
            "lp_unlocked": None,
            "lp_source": "rugcheck",
            "lp_reason": "No matching market LP data found",
        }

    lp = best_market.get("lp") or {}
    locked_pct = safe_float(lp.get("lpLockedPct"))
    locked_usd = safe_float(lp.get("lpLockedUSD"))
    unlocked = safe_float(lp.get("lpUnlocked"))
    total_supply = safe_float(lp.get("lpTotalSupply"))
    current_supply = safe_float(lp.get("lpCurrentSupply"))
    lp_mint = lp.get("lpMint") or best_market.get("mintLP")

    if locked_pct is None and total_supply and total_supply > 0:
        locked = safe_float(lp.get("lpLocked")) or 0
        locked_pct = locked / total_supply * 100

    if locked_pct is not None and locked_pct >= 95:
        status = "LP_LOCKED"
        reason = f"LP is {round(locked_pct, 2)}% locked"
    elif lp_mint == SYSTEM_ADDRESS or current_supply == 0:
        status = "LP_BURNED_OR_NON_WITHDRAWABLE"
        reason = "LP mint/current supply suggests non-withdrawable or burned LP"
    elif locked_pct is not None and locked_pct >= 70:
        status = "LP_MOSTLY_LOCKED"
        reason = f"LP is {round(locked_pct, 2)}% locked"
    elif locked_pct is not None and locked_pct >= 50:
        status = "LP_PARTIALLY_LOCKED"
        reason = f"Only {round(locked_pct, 2)}% of LP is locked"
    elif locked_pct is not None:
        status = "LP_UNLOCKED"
        reason = f"Only {round(locked_pct, 2)}% of LP is locked"
    else:
        status = "LP_LOCK_UNKNOWN"
        reason = "LP lock percentage is unknown"

    return {
        "lp_lock_status": status,
        "lp_locked_pct": round(locked_pct, 2) if locked_pct is not None else None,
        "lp_locked_usd": round(locked_usd, 2) if locked_usd is not None else None,
        "lp_unlocked": round(unlocked, 6) if unlocked is not None else None,
        "lp_source": "rugcheck",
        "lp_reason": reason,
        "lp_market_type": best_market.get("marketType"),
        "lp_market": best_market.get("pubkey"),
        "lp_mint": lp_mint,
    }


def classify_liquidity_trap(
    liquidity: float | None,
    mcap_to_liquidity_ratio: float | None,
    volume_to_liquidity_ratio: float | None,
    lp_lock_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lp_lock_summary = lp_lock_summary or {
        "lp_lock_status": "LP_LOCK_UNKNOWN",
        "lp_reason": "LP lock data was not provided",
    }

    if liquidity is None or liquidity <= 0:
        return {
            "liquidity_trap_status": "LIQUIDITY_TRAP_UNKNOWN",
            "liquidity_trap_score": 100,
            "liquidity_trap_reason": "Liquidity is missing, so trap risk cannot be cleared",
            "liquidity_trap_warnings": ["LIQUIDITY_MISSING"],
            "liquidity_trap_components": {
                "depth": 40,
                "mcap_ratio": 0,
                "volume_ratio": 0,
                "lp_lock": 20,
            },
            "lp_lock": lp_lock_summary,
        }

    warnings = []
    reasons = []

    depth_points = 0.0
    if liquidity < 3000:
        depth_points = 35.0
        warnings.append("TRAP_VERY_LOW_LIQUIDITY")
        reasons.append("Liquidity is very low")
    elif liquidity < 10000:
        depth_points = 22.0
        warnings.append("TRAP_LOW_LIQUIDITY")
        reasons.append("Liquidity is low")
    elif liquidity < 25000:
        depth_points = 10.0

    mcap_points = 0.0
    if mcap_to_liquidity_ratio is not None:
        if mcap_to_liquidity_ratio > 20:
            mcap_points = 35.0
            warnings.append("TRAP_EXTREME_MCAP_TO_LIQUIDITY")
            reasons.append("Market cap is extremely high compared to liquidity")
        elif mcap_to_liquidity_ratio > 10:
            mcap_points = 24.0
            warnings.append("TRAP_HIGH_MCAP_TO_LIQUIDITY")
            reasons.append("Market cap is high compared to liquidity")
        elif mcap_to_liquidity_ratio > 5:
            mcap_points = 12.0

    volume_points = 0.0
    if volume_to_liquidity_ratio is not None:
        if volume_to_liquidity_ratio > 20:
            volume_points = 20.0
            warnings.append("TRAP_EXTREME_VOLUME_TO_LIQUIDITY")
            reasons.append("Trading volume is extreme compared to liquidity")
        elif volume_to_liquidity_ratio > 10:
            volume_points = 12.0
            warnings.append("TRAP_HIGH_VOLUME_TO_LIQUIDITY")
            reasons.append("Trading volume is high compared to liquidity")

    lp_lock_points = 0.0
    lp_status = lp_lock_summary.get("lp_lock_status")
    if lp_status in {"LP_LOCKED", "LP_BURNED_OR_NON_WITHDRAWABLE"}:
        lp_lock_points = 0.0
        reasons.append(lp_lock_summary.get("lp_reason") or "LP appears locked")
    elif lp_status == "LP_MOSTLY_LOCKED":
        lp_lock_points = 4.0
        reasons.append(lp_lock_summary.get("lp_reason") or "LP is mostly locked")
    elif lp_status == "LP_PARTIALLY_LOCKED":
        lp_lock_points = 10.0
        warnings.append("LP_PARTIALLY_LOCKED")
        reasons.append(lp_lock_summary.get("lp_reason") or "LP is only partially locked")
    elif lp_status == "LP_UNLOCKED":
        lp_lock_points = 22.0
        warnings.append("LP_UNLOCKED")
        reasons.append(lp_lock_summary.get("lp_reason") or "LP is unlocked")
    else:
        lp_lock_points = 10.0
        warnings.append("LP_LOCK_STATUS_UNKNOWN")
        reasons.append(lp_lock_summary.get("lp_reason") or "LP lock status is unknown")

    score = clamp_score(depth_points + mcap_points + volume_points + lp_lock_points)

    if score >= 75:
        status = "LIQUIDITY_TRAP_CRITICAL"
    elif score >= 50:
        status = "LIQUIDITY_TRAP_HIGH"
    elif score >= 25:
        status = "LIQUIDITY_TRAP_MEDIUM"
    else:
        status = "LIQUIDITY_TRAP_LOW"

    reason = "; ".join(reasons) if reasons else "No strong liquidity trap pattern detected"

    return {
        "liquidity_trap_status": status,
        "liquidity_trap_score": score,
        "liquidity_trap_reason": reason,
        "liquidity_trap_warnings": warnings,
        "liquidity_trap_components": {
            "depth": round(depth_points, 2),
            "mcap_ratio": round(mcap_points, 2),
            "volume_ratio": round(volume_points, 2),
            "lp_lock": round(lp_lock_points, 2),
        },
        "lp_lock": lp_lock_summary,
    }


def classify_liquidity(row: dict[str, Any]) -> dict[str, Any]:
    liquidity = safe_float(row.get("liquidity_usd"))
    market_cap = safe_float(row.get("market_cap_usd"))
    volume_1h = safe_float(row.get("volume_1h_usd"))
    lp_lock_summary = extract_lp_lock_summary(
        row.get("contract_raw_json"),
        row.get("token_address"),
    )

    warnings = []

    if liquidity is None or liquidity <= 0:
        trap = classify_liquidity_trap(liquidity, None, None, lp_lock_summary)
        return {
            "liquidity_status": "LIQUIDITY_UNKNOWN",
            "liquidity_pass": False,
            "liquidity_reason": "Liquidity is missing or zero",
            "mcap_to_liquidity_ratio": None,
            "volume_to_liquidity_ratio": None,
            "warnings": ["LIQUIDITY_UNKNOWN"],
            **trap,
        }

    mcap_to_liquidity_ratio = None
    if market_cap is not None and liquidity > 0:
        mcap_to_liquidity_ratio = market_cap / liquidity

    volume_to_liquidity_ratio = None
    if volume_1h is not None and liquidity > 0:
        volume_to_liquidity_ratio = volume_1h / liquidity

    if liquidity < 3000:
        warnings.append("VERY_LOW_LIQUIDITY")

    elif liquidity < 10000:
        warnings.append("LOW_LIQUIDITY")

    if mcap_to_liquidity_ratio is not None and mcap_to_liquidity_ratio > 20:
        warnings.append("EXTREME_MCAP_TO_LIQUIDITY")

    elif mcap_to_liquidity_ratio is not None and mcap_to_liquidity_ratio > 10:
        warnings.append("HIGH_MCAP_TO_LIQUIDITY")

    if volume_to_liquidity_ratio is not None and volume_to_liquidity_ratio > 20:
        warnings.append("EXTREME_VOLUME_TO_LIQUIDITY")

    elif volume_to_liquidity_ratio is not None and volume_to_liquidity_ratio > 10:
        warnings.append("HIGH_VOLUME_TO_LIQUIDITY")

    trap = classify_liquidity_trap(
        liquidity=liquidity,
        mcap_to_liquidity_ratio=mcap_to_liquidity_ratio,
        volume_to_liquidity_ratio=volume_to_liquidity_ratio,
        lp_lock_summary=lp_lock_summary,
    )
    if trap["liquidity_trap_status"] in {
        "LIQUIDITY_TRAP_MEDIUM",
        "LIQUIDITY_TRAP_HIGH",
        "LIQUIDITY_TRAP_CRITICAL",
    }:
        warnings.extend(trap["liquidity_trap_warnings"])

    if (
        "VERY_LOW_LIQUIDITY" in warnings
        or "EXTREME_MCAP_TO_LIQUIDITY" in warnings
        or trap["liquidity_trap_status"] == "LIQUIDITY_TRAP_CRITICAL"
    ):
        status = "LIQUIDITY_DANGER"
        passed = False
        reason = "Liquidity is too weak or market cap is too high versus liquidity"

    elif warnings or trap["liquidity_trap_status"] in {"LIQUIDITY_TRAP_HIGH", "LIQUIDITY_TRAP_MEDIUM"}:
        status = "LIQUIDITY_WARNING"
        passed = True
        reason = "Liquidity exists but has trap warnings"

    elif liquidity >= 25000:
        status = "LIQUIDITY_STRONG"
        passed = True
        reason = "Liquidity looks strong"

    elif liquidity >= 10000:
        status = "LIQUIDITY_MODERATE"
        passed = True
        reason = "Liquidity looks acceptable"

    else:
        status = "LIQUIDITY_WEAK"
        passed = True
        reason = "Liquidity is weak but not critical"

    return {
        "liquidity_status": status,
        "liquidity_pass": passed,
        "liquidity_reason": reason,
        "mcap_to_liquidity_ratio": round(mcap_to_liquidity_ratio, 4) if mcap_to_liquidity_ratio is not None else None,
        "volume_to_liquidity_ratio": round(volume_to_liquidity_ratio, 4) if volume_to_liquidity_ratio is not None else None,
        "warnings": warnings,
        **trap,
    }


async def get_liquidity_inputs(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        m.run_id,
        m.token_id,
        m.pair_id,

        t.symbol,
        t.address AS token_address,

        latest_price.liquidity_usd,
        latest_price.market_cap_usd,
        latest_price.volume_1h_usd,
        c.raw_json AS contract_raw_json

    FROM market_filter_results m
    JOIN tokens t
        ON t.id = m.token_id

    LEFT JOIN LATERAL (
        SELECT *
        FROM token_prices tp
        WHERE tp.pair_id = m.pair_id
        ORDER BY tp.time DESC
        LIMIT 1
    ) latest_price ON TRUE

    LEFT JOIN contract_risk_results c
        ON c.run_id = m.run_id
       AND c.token_id = m.token_id

    WHERE m.market_filter_status IN ('MARKET_PASS', 'MARKET_PASS_HIGH_RISK')
      AND m.run_id = (
          SELECT MAX(id)
          FROM ingestion_runs
      )
    ORDER BY m.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [dict(row) for row in rows]


async def save_liquidity_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO liquidity_filter_results (
        run_id,
        token_id,
        pair_id,

        liquidity_status,
        liquidity_pass,
        liquidity_reason,

        liquidity_usd,
        market_cap_usd,
        volume_1h_usd,

        mcap_to_liquidity_ratio,
        volume_to_liquidity_ratio,

        warnings,
        details
    )
    VALUES (
        $1, $2, $3,
        $4, $5, $6,
        $7, $8, $9,
        $10, $11,
        $12::jsonb,
        $13::jsonb
    )
    ON CONFLICT (run_id, token_id, pair_id)
    DO UPDATE SET
        liquidity_status = EXCLUDED.liquidity_status,
        liquidity_pass = EXCLUDED.liquidity_pass,
        liquidity_reason = EXCLUDED.liquidity_reason,

        liquidity_usd = EXCLUDED.liquidity_usd,
        market_cap_usd = EXCLUDED.market_cap_usd,
        volume_1h_usd = EXCLUDED.volume_1h_usd,

        mcap_to_liquidity_ratio = EXCLUDED.mcap_to_liquidity_ratio,
        volume_to_liquidity_ratio = EXCLUDED.volume_to_liquidity_ratio,

        warnings = EXCLUDED.warnings,
        details = EXCLUDED.details,
        created_at = NOW()

    RETURNING *;
    """

    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        "liquidity_trap_status": result["liquidity_trap_status"],
        "liquidity_trap_score": result["liquidity_trap_score"],
        "liquidity_trap_reason": result["liquidity_trap_reason"],
        "liquidity_trap_warnings": result["liquidity_trap_warnings"],
        "liquidity_trap_components": result["liquidity_trap_components"],
        "lp_lock": result["lp_lock"],
    }

    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            sql,
            row["run_id"],
            row["token_id"],
            row["pair_id"],

            result["liquidity_status"],
            result["liquidity_pass"],
            result["liquidity_reason"],

            row.get("liquidity_usd"),
            row.get("market_cap_usd"),
            row.get("volume_1h_usd"),

            result["mcap_to_liquidity_ratio"],
            result["volume_to_liquidity_ratio"],

            json.dumps(result["warnings"]),
            json.dumps(details),
        )

    return dict(saved)


async def run_liquidity_filter_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await get_liquidity_inputs(pool)

    results = []

    for row in rows:
        result = classify_liquidity(row)
        saved = await save_liquidity_result(pool, row, result)

        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")

        results.append(saved)

    return results

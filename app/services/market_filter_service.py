import json
from datetime import datetime, timezone
from typing import Any

import asyncpg

ALLOWED_READINESS_STATUSES = {
    "READY_FOR_ANALYSIS",
    "PARTIAL_BUT_PASS",
}


def safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_json(value) -> dict:
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


def classify_pair_age(pair_created_at: datetime | None) -> dict[str, Any]:
    if pair_created_at is None:
        return {
            "pair_age_minutes": None,
            "early_category": "UNKNOWN_AGE",
            "passes_early_dex_filter": False,
            "reason": "pair_created_at is missing",
        }

    now = datetime.now(timezone.utc)

    if pair_created_at.tzinfo is None:
        pair_created_at = pair_created_at.replace(tzinfo=timezone.utc)

    age_minutes = (now - pair_created_at).total_seconds() / 60

    if age_minutes < 0:
        return {
            "pair_age_minutes": round(age_minutes, 2),
            "early_category": "INVALID_FUTURE_DATE",
            "passes_early_dex_filter": False,
            "reason": "pair_created_at is in the future",
        }

    if age_minutes < 5:
        category = "ULTRA_EARLY_MONITOR"
        passes = True
        reason = "Very new pair; monitor carefully"
    elif age_minutes < 30:
        category = "EARLY_CAPTURE"
        passes = True
        reason = "Strong early Dex capture window"
    elif age_minutes < 120:
        category = "EARLY_MOMENTUM"
        passes = True
        reason = "Still in early momentum window"
    elif age_minutes < 360:
        category = "STILL_EARLY"
        passes = True
        reason = "Still early enough for Dex Early Capture"
    elif age_minutes < 1440:
        category = "LATE_EARLY"
        passes = True
        reason = "Less than 24h old, but no longer fresh"
    else:
        category = "NOT_EARLY"
        passes = False
        reason = "Pair is older than 24h"

    return {
        "pair_age_minutes": round(age_minutes, 2),
        "early_category": category,
        "passes_early_dex_filter": passes,
        "reason": reason,
    }


def classify_dump_risk(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    يحمي النظام من العملات التي دخلت Dex حديثًا لكنها بدأت dump أو sell pressure.
    """

    if not candidate.get("passes_early_dex_filter"):
        return {
            "price_change_5m": None,
            "price_change_1h": None,
            "buy_ratio_5m": None,
            "buy_ratio_1h": None,
            "dump_risk_category": "SKIP_NOT_EARLY",
            "passes_anti_dump_filter": False,
            "dump_reason": "Pair is not early",
        }

    price_change = normalize_json(candidate.get("price_change"))

    price_change_5m = safe_float(price_change.get("m5"))
    price_change_1h = safe_float(price_change.get("h1"))

    buys_5m = safe_int(candidate.get("buys_5m"))
    sells_5m = safe_int(candidate.get("sells_5m"))
    buys_1h = safe_int(candidate.get("buys_1h"))
    sells_1h = safe_int(candidate.get("sells_1h"))

    total_txns_5m = buys_5m + sells_5m
    total_txns_1h = buys_1h + sells_1h

    buy_ratio_5m = buys_5m / total_txns_5m if total_txns_5m > 0 else None
    buy_ratio_1h = buys_1h / total_txns_1h if total_txns_1h > 0 else None

    if price_change_5m is not None and price_change_5m <= -20:
        return {
            "price_change_5m": price_change_5m,
            "price_change_1h": price_change_1h,
            "buy_ratio_5m": round(buy_ratio_5m, 4) if buy_ratio_5m is not None else None,
            "buy_ratio_1h": round(buy_ratio_1h, 4) if buy_ratio_1h is not None else None,
            "dump_risk_category": "EARLY_DUMP_RISK",
            "passes_anti_dump_filter": False,
            "dump_reason": "Price dropped more than 20% in 5m",
        }

    if price_change_1h is not None and price_change_1h <= -40:
        return {
            "price_change_5m": price_change_5m,
            "price_change_1h": price_change_1h,
            "buy_ratio_5m": round(buy_ratio_5m, 4) if buy_ratio_5m is not None else None,
            "buy_ratio_1h": round(buy_ratio_1h, 4) if buy_ratio_1h is not None else None,
            "dump_risk_category": "HARD_1H_DUMP",
            "passes_anti_dump_filter": False,
            "dump_reason": "Price dropped more than 40% in 1h",
        }

    if (
        price_change_1h is not None
        and price_change_5m is not None
        and price_change_1h >= 100
        and price_change_5m <= -15
    ):
        return {
            "price_change_5m": price_change_5m,
            "price_change_1h": price_change_1h,
            "buy_ratio_5m": round(buy_ratio_5m, 4) if buy_ratio_5m is not None else None,
            "buy_ratio_1h": round(buy_ratio_1h, 4) if buy_ratio_1h is not None else None,
            "dump_risk_category": "POST_PUMP_DUMP",
            "passes_anti_dump_filter": False,
            "dump_reason": "Strong 1h pump but sharp 5m dump",
        }

    if buy_ratio_5m is not None and buy_ratio_5m < 0.35 and total_txns_5m >= 10:
        return {
            "price_change_5m": price_change_5m,
            "price_change_1h": price_change_1h,
            "buy_ratio_5m": round(buy_ratio_5m, 4),
            "buy_ratio_1h": round(buy_ratio_1h, 4) if buy_ratio_1h is not None else None,
            "dump_risk_category": "SELL_PRESSURE_5M",
            "passes_anti_dump_filter": False,
            "dump_reason": "Strong sell pressure in last 5m",
        }

    if buy_ratio_1h is not None and buy_ratio_1h < 0.40 and total_txns_1h >= 50:
        return {
            "price_change_5m": price_change_5m,
            "price_change_1h": price_change_1h,
            "buy_ratio_5m": round(buy_ratio_5m, 4) if buy_ratio_5m is not None else None,
            "buy_ratio_1h": round(buy_ratio_1h, 4),
            "dump_risk_category": "SELL_PRESSURE_1H",
            "passes_anti_dump_filter": False,
            "dump_reason": "Sell pressure dominates 1h activity",
        }

    return {
        "price_change_5m": price_change_5m,
        "price_change_1h": price_change_1h,
        "buy_ratio_5m": round(buy_ratio_5m, 4) if buy_ratio_5m is not None else None,
        "buy_ratio_1h": round(buy_ratio_1h, 4) if buy_ratio_1h is not None else None,
        "dump_risk_category": "NO_EARLY_DUMP_SIGNAL",
        "passes_anti_dump_filter": True,
        "dump_reason": "No strong early dump signal detected",
    }


def classify_market_activity(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    فلتر نشاط السوق حسب عمر العملة.
    لا نستعمل volume_1h وحده لعملة عمرها 5 دقائق.
    """

    if not candidate.get("passes_early_dex_filter"):
        return {
            "activity_window": None,
            "activity_volume_usd": None,
            "activity_txns": None,
            "activity_buy_ratio": None,
            "volume_to_mcap_ratio": None,
            "activity_category": "SKIP_NOT_EARLY",
            "passes_market_activity_filter": False,
            "activity_reason": "Pair is not early",
        }

    if not candidate.get("passes_anti_dump_filter"):
        return {
            "activity_window": None,
            "activity_volume_usd": None,
            "activity_txns": None,
            "activity_buy_ratio": None,
            "volume_to_mcap_ratio": None,
            "activity_category": "BLOCKED_BY_DUMP_RISK",
            "passes_market_activity_filter": False,
            "activity_reason": candidate.get("dump_reason"),
        }

    age_minutes = safe_float(candidate.get("pair_age_minutes"))
    market_cap = safe_float(candidate.get("market_cap_usd"))

    if age_minutes is None:
        return {
            "activity_window": None,
            "activity_volume_usd": None,
            "activity_txns": None,
            "activity_buy_ratio": None,
            "volume_to_mcap_ratio": None,
            "activity_category": "UNKNOWN_AGE",
            "passes_market_activity_filter": False,
            "activity_reason": "Cannot classify activity without pair age",
        }

    if age_minutes < 5:
        volume_5m = safe_float(candidate.get("volume_5m_usd"))
        buys_5m = safe_int(candidate.get("buys_5m"))
        sells_5m = safe_int(candidate.get("sells_5m"))
        total_txns_5m = buys_5m + sells_5m

        buy_ratio_5m = buys_5m / total_txns_5m if total_txns_5m > 0 else None

        volume_to_mcap_ratio = None
        if volume_5m is not None and market_cap is not None and market_cap > 0:
            volume_to_mcap_ratio = volume_5m / market_cap

        return {
            "activity_window": "5m",
            "activity_volume_usd": volume_5m,
            "activity_txns": total_txns_5m,
            "activity_buy_ratio": round(buy_ratio_5m, 4) if buy_ratio_5m is not None else None,
            "volume_to_mcap_ratio": round(volume_to_mcap_ratio, 4) if volume_to_mcap_ratio is not None else None,
            "activity_category": "MONITOR_ONLY_ULTRA_EARLY",
            "passes_market_activity_filter": False,
            "activity_reason": "Less than 5 minutes old; monitor only",
        }

    if age_minutes < 30:
        activity_window = "5m"
        activity_volume = safe_float(candidate.get("volume_5m_usd"))
        buys = safe_int(candidate.get("buys_5m"))
        sells = safe_int(candidate.get("sells_5m"))

        strong_volume_threshold = 5000
        strong_txns_threshold = 50
        moderate_volume_threshold = 1000
        moderate_txns_threshold = 15

    else:
        activity_window = "1h"
        activity_volume = safe_float(candidate.get("volume_1h_usd"))
        buys = safe_int(candidate.get("buys_1h"))
        sells = safe_int(candidate.get("sells_1h"))

        strong_volume_threshold = 50000
        strong_txns_threshold = 200
        moderate_volume_threshold = 10000
        moderate_txns_threshold = 50

    total_txns = buys + sells

    if activity_volume is None or market_cap is None:
        return {
            "activity_window": activity_window,
            "activity_volume_usd": activity_volume,
            "activity_txns": total_txns,
            "activity_buy_ratio": None,
            "volume_to_mcap_ratio": None,
            "activity_category": "INSUFFICIENT_DATA",
            "passes_market_activity_filter": False,
            "activity_reason": "Missing activity volume or market cap",
        }

    if total_txns == 0:
        return {
            "activity_window": activity_window,
            "activity_volume_usd": activity_volume,
            "activity_txns": 0,
            "activity_buy_ratio": None,
            "volume_to_mcap_ratio": None,
            "activity_category": "NO_TXNS",
            "passes_market_activity_filter": False,
            "activity_reason": f"No transactions in {activity_window}",
        }

    buy_ratio = buys / total_txns

    volume_to_mcap_ratio = None
    if market_cap > 0:
        volume_to_mcap_ratio = activity_volume / market_cap

    if (
        activity_volume >= strong_volume_threshold
        and total_txns >= strong_txns_threshold
        and buy_ratio >= 0.50
    ):
        category = "STRONG_ACTIVITY"
        passes = True
        reason = f"Strong {activity_window} activity with acceptable buy pressure"

    elif (
        activity_volume >= moderate_volume_threshold
        and total_txns >= moderate_txns_threshold
        and buy_ratio >= 0.45
    ):
        category = "MODERATE_ACTIVITY"
        passes = True
        reason = f"Moderate {activity_window} activity"

    elif buy_ratio < 0.40 and total_txns >= moderate_txns_threshold:
        category = "SELL_PRESSURE_ACTIVITY"
        passes = False
        reason = f"Activity exists, but sell pressure is high in {activity_window}"

    else:
        category = "WEAK_ACTIVITY"
        passes = False
        reason = f"{activity_window} market activity is still weak"

    return {
        "activity_window": activity_window,
        "activity_volume_usd": activity_volume,
        "activity_txns": total_txns,
        "activity_buy_ratio": round(buy_ratio, 4),
        "volume_to_mcap_ratio": round(volume_to_mcap_ratio, 4) if volume_to_mcap_ratio is not None else None,
        "activity_category": category,
        "passes_market_activity_filter": passes,
        "activity_reason": reason,
    }

def classify_market_warnings(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Add market warnings without blocking the token.

    These warnings do not mean reject.
    They only tell us the candidate is risky and needs caution.
    """

    warnings = []

    price_change_1h = safe_float(candidate.get("price_change_1h"))
    price_change_5m = safe_float(candidate.get("price_change_5m"))
    volume_to_mcap_ratio = safe_float(candidate.get("volume_to_mcap_ratio"))
    market_cap = safe_float(candidate.get("market_cap_usd"))
    liquidity = safe_float(candidate.get("liquidity_usd"))

    if price_change_1h is not None and price_change_1h <= -20:
        warnings.append("1H_PRICE_WEAKNESS")

    if price_change_5m is not None and price_change_5m <= -10:
        warnings.append("5M_SHORT_TERM_WEAKNESS")

    if volume_to_mcap_ratio is not None and volume_to_mcap_ratio > 10:
        warnings.append("EXTREME_VOLUME_TO_MCAP")

    if volume_to_mcap_ratio is not None and volume_to_mcap_ratio > 20:
        warnings.append("VERY_EXTREME_VOLUME_TO_MCAP")

    if liquidity is None:
        warnings.append("LIQUIDITY_UNKNOWN")

    elif liquidity < 5000:
        warnings.append("LOW_LIQUIDITY")

    if market_cap is not None and market_cap < 5000:
        warnings.append("MICRO_MARKET_CAP")

    if not candidate.get("passes_market_activity_filter"):
        warnings.append("DID_NOT_PASS_ACTIVITY_FILTER")

    dump_risk_category = candidate.get("dump_risk_category")

    if not candidate.get("passes_anti_dump_filter") and dump_risk_category != "SKIP_NOT_EARLY":
        warnings.append("BLOCKED_BY_DUMP_RISK")
    if not candidate.get("passes_early_dex_filter"):
        warnings.append("NOT_EARLY_DEX_ENTRY")

    if len(warnings) == 0:
        warning_level = "LOW"
    elif len(warnings) <= 2:
        warning_level = "MEDIUM"
    elif len(warnings) <= 4:
        warning_level = "HIGH"
    else:
        warning_level = "VERY_HIGH"

    return {
        "market_warnings": warnings,
        "market_warning_level": warning_level,
    }

def classify_market_filter_status(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Final status for market_filter_service only.

    This is NOT a buy signal.
    This only says whether the token passes the market filter stage.
    """

    if not candidate.get("passes_early_dex_filter"):
        return {
            "market_filter_status": "MARKET_REJECT_NOT_EARLY",
            "market_filter_pass": False,
            "market_filter_reason": "Token is not a recent Dex entry",
        }

    dump_risk_category = candidate.get("dump_risk_category")

    if (
        not candidate.get("passes_anti_dump_filter")
        and dump_risk_category != "SKIP_NOT_EARLY"
    ):
        return {
            "market_filter_status": "MARKET_REJECT_DUMP_RISK",
            "market_filter_pass": False,
            "market_filter_reason": candidate.get("dump_reason"),
        }

    if not candidate.get("passes_market_activity_filter"):
        return {
            "market_filter_status": "MARKET_REJECT_WEAK_ACTIVITY",
            "market_filter_pass": False,
            "market_filter_reason": candidate.get("activity_reason"),
        }

    warning_level = candidate.get("market_warning_level")

    if warning_level in {"HIGH", "VERY_HIGH"}:
        return {
            "market_filter_status": "MARKET_PASS_HIGH_RISK",
            "market_filter_pass": True,
            "market_filter_reason": "Passed market filter, but risk warnings are high",
        }

    return {
        "market_filter_status": "MARKET_PASS",
        "market_filter_pass": True,
        "market_filter_reason": "Passed early market filter",
    }
async def get_early_dex_candidates(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        r.run_id,
        r.token_id,
        r.pair_id,
        r.symbol,
        r.name,
        r.chain,
        r.token_address,
        r.pair_address,
        r.data_readiness_status,

        p.pair_created_at,

        latest_price.time AS price_time,
        latest_price.price_usd,
        latest_price.liquidity_usd,
        latest_price.volume_5m_usd,
        latest_price.volume_1h_usd,
        latest_price.volume_6h_usd,
        latest_price.volume_24h_usd,
        latest_price.buys_5m,
        latest_price.sells_5m,
        latest_price.buys_1h,
        latest_price.sells_1h,
        latest_price.market_cap_usd,
        latest_price.fdv_usd,

        latest_raw.price_change

    FROM latest_token_data_readiness r
    JOIN token_pairs p
        ON p.id = r.pair_id

    LEFT JOIN LATERAL (
        SELECT *
        FROM token_prices tp
        WHERE tp.pair_id = r.pair_id
        ORDER BY tp.time DESC
        LIMIT 1
    ) latest_price ON TRUE

    LEFT JOIN LATERAL (
        SELECT
            ras.raw_json->'priceChange' AS price_change
        FROM raw_api_snapshots ras
        WHERE ras.pair_address = r.pair_address
          AND ras.endpoint = '/token-pairs/v1/solana/{tokenAddress}'
        ORDER BY ras.created_at DESC
        LIMIT 1
    ) latest_raw ON TRUE

    WHERE r.data_readiness_status = ANY($1::text[])
    ORDER BY p.pair_created_at DESC NULLS LAST;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, list(ALLOWED_READINESS_STATUSES))

    candidates = []

    for row in rows:
        item = dict(row)

        item.update(classify_pair_age(item.get("pair_created_at")))
        item.update(classify_dump_risk(item))
        item.update(classify_market_activity(item))
        item.update(classify_market_warnings(item))
        item.update(classify_market_filter_status(item))

        candidates.append(item)

    return candidates


async def print_early_dex_candidates(pool: asyncpg.Pool) -> None:
    candidates = await get_early_dex_candidates(pool)

    if not candidates:
        print("No early dex candidates found.")
        return

    print("\nEarly Dex Candidates")
    print("-" * 180)
async def save_market_filter_result(
    pool: asyncpg.Pool,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Save one market filter result to PostgreSQL.
    """

    sql = """
    INSERT INTO market_filter_results (
        run_id,
        token_id,
        pair_id,

        market_filter_status,
        market_filter_pass,
        market_filter_reason,

        data_readiness_status,

        early_category,
        passes_early_dex_filter,

        dump_risk_category,
        passes_anti_dump_filter,

        activity_category,
        passes_market_activity_filter,

        market_warning_level,
        market_warnings,

        details
    )
    VALUES (
        $1, $2, $3,
        $4, $5, $6,
        $7,
        $8, $9,
        $10, $11,
        $12, $13,
        $14, $15::jsonb,
        $16::jsonb
    )
    ON CONFLICT (run_id, token_id, pair_id)
    DO UPDATE SET
        market_filter_status = EXCLUDED.market_filter_status,
        market_filter_pass = EXCLUDED.market_filter_pass,
        market_filter_reason = EXCLUDED.market_filter_reason,

        data_readiness_status = EXCLUDED.data_readiness_status,

        early_category = EXCLUDED.early_category,
        passes_early_dex_filter = EXCLUDED.passes_early_dex_filter,

        dump_risk_category = EXCLUDED.dump_risk_category,
        passes_anti_dump_filter = EXCLUDED.passes_anti_dump_filter,

        activity_category = EXCLUDED.activity_category,
        passes_market_activity_filter = EXCLUDED.passes_market_activity_filter,

        market_warning_level = EXCLUDED.market_warning_level,
        market_warnings = EXCLUDED.market_warnings,

        details = EXCLUDED.details,
        created_at = NOW()

    RETURNING *;
    """

    details = {
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "chain": candidate.get("chain"),
        "token_address": candidate.get("token_address"),
        "pair_address": candidate.get("pair_address"),

        "pair_age_minutes": candidate.get("pair_age_minutes"),
        "price_usd": str(candidate.get("price_usd")),
        "liquidity_usd": str(candidate.get("liquidity_usd")),
        "market_cap_usd": str(candidate.get("market_cap_usd")),
        "fdv_usd": str(candidate.get("fdv_usd")),

        "activity_window": candidate.get("activity_window"),
        "activity_volume_usd": str(candidate.get("activity_volume_usd")),
        "activity_txns": candidate.get("activity_txns"),
        "activity_buy_ratio": candidate.get("activity_buy_ratio"),

        "price_change_5m": candidate.get("price_change_5m"),
        "price_change_1h": candidate.get("price_change_1h"),
        "volume_to_mcap_ratio": candidate.get("volume_to_mcap_ratio"),

        "dump_reason": candidate.get("dump_reason"),
        "activity_reason": candidate.get("activity_reason"),
    }

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            candidate["run_id"],
            candidate["token_id"],
            candidate["pair_id"],

            candidate["market_filter_status"],
            candidate["market_filter_pass"],
            candidate["market_filter_reason"],

            candidate["data_readiness_status"],

            candidate["early_category"],
            candidate["passes_early_dex_filter"],

            candidate["dump_risk_category"],
            candidate["passes_anti_dump_filter"],

            candidate["activity_category"],
            candidate["passes_market_activity_filter"],

            candidate["market_warning_level"],
            json.dumps(candidate["market_warnings"]),

            json.dumps(details),
        )

    return dict(row)


async def save_market_filter_results(
    pool: asyncpg.Pool,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Save all market filter results.
    """

    saved_results = []

    for candidate in candidates:
        saved = await save_market_filter_result(pool, candidate)
        saved_results.append(saved)

    return saved_results
    for c in candidates:
        print(

            f"symbol={c['symbol']} | "
            f"status={c['data_readiness_status']} | "
            f"age_min={c['pair_age_minutes']} | "
            f"early={c['early_category']} | "
            f"early_pass={c['passes_early_dex_filter']} | "
            f"dump={c['dump_risk_category']} | "
            f"anti_dump_pass={c['passes_anti_dump_filter']} | "
            f"activity={c['activity_category']} | "
            f"activity_pass={c['passes_market_activity_filter']} | "
            f"activity_window={c['activity_window']} | "
            f"activity_volume={c['activity_volume_usd']} | "
            f"activity_txns={c['activity_txns']} | "
            f"activity_buy_ratio={c['activity_buy_ratio']} | "
            f"pc5m={c['price_change_5m']} | "
            f"pc1h={c['price_change_1h']} | "
            f"vol_mcap={c['volume_to_mcap_ratio']} | "
            f"mcap={c['market_cap_usd']} | "
            f"vol_1h={c['volume_1h_usd']} | "
            f"liquidity={c['liquidity_usd']} | "
            f"warning_level={c['market_warning_level']} | "
            f"warnings={c['market_warnings']} | "
            f"market_status={c['market_filter_status']} | "
            f"market_pass={c['market_filter_pass']} | "
            f"market_reason={c['market_filter_reason']}"
        )

import json
from typing import Any

import asyncpg


EXCLUDED_HOLDER_OWNERS = {
    "11111111111111111111111111111111",
}


def safe_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def extract_top_holders(raw_json: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    holders = raw_json.get("topHolders") or raw_json.get("holders") or []

    if not isinstance(holders, list):
        return []

    extracted = []

    for holder in holders:
        if not isinstance(holder, dict):
            continue

        owner = holder.get("owner") or holder.get("address")

        if not owner or owner in EXCLUDED_HOLDER_OWNERS:
            continue

        amount = safe_float(
            holder.get("uiAmount")
            or holder.get("amount")
            or holder.get("balance")
        )

        percent = safe_float(
            holder.get("pct")
            or holder.get("percentage")
            or holder.get("percent")
        )

        if amount == 0 and percent is None:
            continue

        extracted.append(
            {
                "owner_address": owner,
                "amount": amount,
                "percent": percent,
                "raw_json": holder,
            }
        )

        if len(extracted) >= limit:
            break

    return extracted


def classify_wallet_distribution(holders: list[dict[str, Any]]) -> dict[str, Any]:
    warnings = []

    if not holders:
        return {
            "wallet_status": "WALLET_UNKNOWN",
            "wallet_pass": False,
            "wallet_reason": "Holder data is unavailable",
            "top_holder_percent": None,
            "top10_holders_percent": None,
            "top20_holders_percent": None,
            "holder_count": 0,
            "warnings": ["HOLDER_DATA_UNKNOWN"],
        }

    percents = [
        holder["percent"]
        for holder in holders
        if holder.get("percent") is not None
    ]

    if not percents:
        return {
            "wallet_status": "WALLET_UNKNOWN",
            "wallet_pass": False,
            "wallet_reason": "Holder percentages are unavailable",
            "top_holder_percent": None,
            "top10_holders_percent": None,
            "top20_holders_percent": None,
            "holder_count": len(holders),
            "warnings": ["HOLDER_PERCENTAGES_UNKNOWN"],
        }

    top_holder_percent = round(max(percents), 4)
    top10_holders_percent = round(min(sum(percents[:10]), 100.0), 4)
    top20_holders_percent = round(min(sum(percents[:20]), 100.0), 4)

    if top_holder_percent >= 20:
        warnings.append("TOP_HOLDER_OVER_20_PERCENT")

    if top10_holders_percent >= 50:
        warnings.append("TOP10_HOLDERS_OVER_50_PERCENT")
    elif top10_holders_percent >= 30:
        warnings.append("TOP10_HOLDERS_OVER_30_PERCENT")

    if top20_holders_percent >= 70:
        warnings.append("TOP20_HOLDERS_OVER_70_PERCENT")

    if (
        "TOP_HOLDER_OVER_20_PERCENT" in warnings
        or "TOP10_HOLDERS_OVER_50_PERCENT" in warnings
        or "TOP20_HOLDERS_OVER_70_PERCENT" in warnings
    ):
        status = "WALLET_DANGER"
        passed = False
        reason = "Holder distribution is highly concentrated"
    elif warnings:
        status = "WALLET_WARNING"
        passed = True
        reason = "Holder distribution has concentration warnings"
    else:
        status = "WALLET_PASS"
        passed = True
        reason = "Holder distribution looks acceptable"

    return {
        "wallet_status": status,
        "wallet_pass": passed,
        "wallet_reason": reason,
        "top_holder_percent": top_holder_percent,
        "top10_holders_percent": top10_holders_percent,
        "top20_holders_percent": top20_holders_percent,
        "holder_count": len(holders),
        "warnings": warnings,
    }


async def get_wallet_analysis_inputs(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        c.run_id,
        c.token_id,
        c.pair_id,
        c.raw_json,
        t.symbol,
        t.address AS token_address
    FROM contract_risk_results c
    JOIN tokens t
        ON t.id = c.token_id
    WHERE c.contract_risk_status IS NOT NULL
      AND c.run_id = (
          SELECT MAX(id)
          FROM ingestion_runs
      )
    ORDER BY c.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [dict(row) for row in rows]


async def save_token_holders(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    holders: list[dict[str, Any]],
) -> None:
    sql = """
    INSERT INTO token_holders (
        run_id,
        token_id,
        pair_id,
        owner_address,
        rank,
        amount,
        percent,
        source,
        raw_json
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, 'rugcheck', $8::jsonb)
    ON CONFLICT (run_id, token_id, owner_address, source)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,
        rank = EXCLUDED.rank,
        amount = EXCLUDED.amount,
        percent = EXCLUDED.percent,
        raw_json = EXCLUDED.raw_json,
        created_at = NOW();
    """

    async with pool.acquire() as conn:
        for index, holder in enumerate(holders, start=1):
            await conn.execute(
                sql,
                row["run_id"],
                row["token_id"],
                row["pair_id"],
                holder["owner_address"],
                index,
                holder.get("amount"),
                holder.get("percent"),
                json.dumps(holder.get("raw_json") or {}, default=str),
            )


async def save_wallet_analysis_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
    holders: list[dict[str, Any]],
) -> dict[str, Any]:
    sql = """
    INSERT INTO wallet_analysis_results (
        run_id,
        token_id,
        pair_id,
        wallet_status,
        wallet_pass,
        wallet_reason,
        top_holder_percent,
        top10_holders_percent,
        top20_holders_percent,
        holder_count,
        warnings,
        details
    )
    VALUES (
        $1, $2, $3,
        $4, $5, $6,
        $7, $8, $9,
        $10, $11::jsonb, $12::jsonb
    )
    ON CONFLICT (run_id, token_id)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,
        wallet_status = EXCLUDED.wallet_status,
        wallet_pass = EXCLUDED.wallet_pass,
        wallet_reason = EXCLUDED.wallet_reason,
        top_holder_percent = EXCLUDED.top_holder_percent,
        top10_holders_percent = EXCLUDED.top10_holders_percent,
        top20_holders_percent = EXCLUDED.top20_holders_percent,
        holder_count = EXCLUDED.holder_count,
        warnings = EXCLUDED.warnings,
        details = EXCLUDED.details,
        created_at = NOW()
    RETURNING *;
    """

    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        "source": "rugcheck",
        "holder_sample_size": len(holders),
    }

    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            sql,
            row["run_id"],
            row["token_id"],
            row["pair_id"],
            result["wallet_status"],
            result["wallet_pass"],
            result["wallet_reason"],
            result["top_holder_percent"],
            result["top10_holders_percent"],
            result["top20_holders_percent"],
            result["holder_count"],
            json.dumps(result["warnings"]),
            json.dumps(details),
        )

    return dict(saved)


async def run_wallet_analysis_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await get_wallet_analysis_inputs(pool)

    results = []

    for row in rows:
        raw_json = normalize_json(row.get("raw_json"))
        holders = extract_top_holders(raw_json)

        await save_token_holders(pool, row, holders)

        result = classify_wallet_distribution(holders)
        saved = await save_wallet_analysis_result(pool, row, result, holders)

        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")

        results.append(saved)

    return results

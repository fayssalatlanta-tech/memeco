import json
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv


load_dotenv()


RUGCHECK_BASE_URL = "https://api.rugcheck.xyz"

ALLOWED_MARKET_STATUSES = {
    "MARKET_PASS",
    "MARKET_PASS_HIGH_RISK",
}


EXCLUDED_HOLDER_OWNERS = {
    "11111111111111111111111111111111",
}


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


def safe_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rugcheck_has_no_data(report: dict[str, Any]) -> bool:
    """
    Detect cases where RugCheck returns a page/report but does not have real token data yet.
    Example: supply=0, holders=0, marketCap=0, top holders empty.
    """

    token_meta = normalize_json(report.get("tokenMeta"))
    token_info = normalize_json(report.get("token"))

    supply = safe_float(
        report.get("supply")
        or token_meta.get("supply")
        or token_info.get("supply")
    )

    market_cap = safe_float(
        report.get("marketCap")
        or report.get("market_cap")
        or token_meta.get("marketCap")
        or token_info.get("marketCap")
    )

    holders_count = safe_float(
        report.get("holders")
        or report.get("holderCount")
        or report.get("holdersCount")
        or token_meta.get("holders")
        or token_info.get("holders")
    )

    top_holders = report.get("topHolders") or []

    no_supply = supply is not None and supply == 0
    no_market_cap = market_cap is not None and market_cap == 0
    no_holders = holders_count is not None and holders_count == 0
    no_top_holders = isinstance(top_holders, list) and len(top_holders) == 0

    if no_supply and no_market_cap and no_holders:
        return True

    if no_supply and no_top_holders:
        return True

    return False


def extract_rugcheck_summary(report: dict[str, Any]) -> dict[str, Any]:
    if rugcheck_has_no_data(report):
        return {
            "contract_risk_status": "CONTRACT_UNKNOWN",
            "contract_risk_pass": False,
            "contract_risk_reason": "RugCheck returned incomplete/no token data",
            "risk_score": safe_float(report.get("score")),
            "risk_level": "UNKNOWN",
            "mint_authority_status": "UNKNOWN",
            "freeze_authority_status": "UNKNOWN",
            "top_holders_percent": None,
            "dev_wallet_percent": None,
            "warnings": [
                {
                    "name": "RUGCHECK_NO_DATA",
                    "level": "UNKNOWN",
                }
            ],
            "details": {
                "critical_flags": [],
                "no_data": True,
            },
        }

    warnings = []

    risk_score = safe_float(
        report.get("score")
        or report.get("riskScore")
        or report.get("risk_score")
    )

    risk_level = (
        report.get("riskLevel")
        or report.get("risk_level")
        or report.get("scoreLabel")
        or report.get("status")
    )

    risks = report.get("risks") or report.get("warnings") or []

    if isinstance(risks, list):
        for risk in risks:
            if isinstance(risk, dict):
                name = (
                    risk.get("name")
                    or risk.get("title")
                    or risk.get("description")
                )

                level = risk.get("level") or risk.get("severity")

                if name:
                    warnings.append(
                        {
                            "name": name,
                            "level": level,
                        }
                    )

            elif isinstance(risk, str):
                warnings.append(
                    {
                        "name": risk,
                        "level": None,
                    }
                )

    token_meta = normalize_json(report.get("tokenMeta"))
    token_info = normalize_json(report.get("token"))

    top_holders = report.get("topHolders") or report.get("holders") or []

    mint_authority = (
        report.get("mintAuthority")
        or token_meta.get("mintAuthority")
        or token_info.get("mintAuthority")
    )

    freeze_authority = (
        report.get("freezeAuthority")
        or token_meta.get("freezeAuthority")
        or token_info.get("freezeAuthority")
    )

    mint_authority_status = "REVOKED" if not mint_authority else "ENABLED"
    freeze_authority_status = "REVOKED" if not freeze_authority else "ENABLED"

    top_holders_percent = None

    if isinstance(top_holders, list):
        total_pct = 0.0
        count = 0

        for holder in top_holders:
            if not isinstance(holder, dict):
                continue

            owner = holder.get("owner")

            if owner in EXCLUDED_HOLDER_OWNERS:
                continue

            ui_amount = safe_float(holder.get("uiAmount"))

            if ui_amount == 0:
                continue

            pct = safe_float(
                holder.get("pct")
                or holder.get("percentage")
                or holder.get("percent")
            )

            if pct is None:
                continue

            total_pct += pct
            count += 1

            if count >= 10:
                break

        if count > 0:
            top_holders_percent = round(min(total_pct, 100.0), 2)

    critical_flags = []

    if mint_authority_status == "ENABLED":
        critical_flags.append("MINT_AUTHORITY_ENABLED")

    if freeze_authority_status == "ENABLED":
        critical_flags.append("FREEZE_AUTHORITY_ENABLED")

    if top_holders_percent is not None and top_holders_percent >= 50:
        critical_flags.append("TOP_HOLDERS_CONCENTRATED")

    for warning in warnings:
        level = str(warning.get("level") or "").lower()
        name = str(warning.get("name") or "").lower()

        if level in {"danger", "critical", "high"}:
            critical_flags.append(warning.get("name"))

        if "freeze" in name or "mint" in name or "rug" in name:
            critical_flags.append(warning.get("name"))

    if critical_flags:
        contract_risk_status = "CONTRACT_DANGER"
        contract_risk_pass = False
        reason = "Critical contract or holder risk detected"

    elif warnings:
        contract_risk_status = "CONTRACT_WARNING"
        contract_risk_pass = True
        reason = "Warnings detected, review required"

    else:
        contract_risk_status = "CONTRACT_PASS"
        contract_risk_pass = True
        reason = "No critical RugCheck risks detected"

    return {
        "contract_risk_status": contract_risk_status,
        "contract_risk_pass": contract_risk_pass,
        "contract_risk_reason": reason,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "mint_authority_status": mint_authority_status,
        "freeze_authority_status": freeze_authority_status,
        "top_holders_percent": top_holders_percent,
        "dev_wallet_percent": None,
        "warnings": warnings,
        "details": {
            "critical_flags": critical_flags,
            "no_data": False,
        },
    }


async def fetch_rugcheck_report(token_address: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    url = f"{RUGCHECK_BASE_URL}/v1/tokens/{token_address}/report"

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def get_market_pass_candidates(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        m.run_id,
        m.token_id,
        m.pair_id,
        m.market_filter_status,
        m.market_filter_pass,
        t.chain,
        t.address AS token_address,
        t.symbol,
        t.name
    FROM market_filter_results m
    JOIN tokens t
        ON t.id = m.token_id
    WHERE m.market_filter_status = ANY($1::text[])
      AND m.run_id = (
          SELECT MAX(id)
          FROM ingestion_runs
      )
    ORDER BY m.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, list(ALLOWED_MARKET_STATUSES))

    return [dict(row) for row in rows]


async def save_contract_risk_result(
    pool: asyncpg.Pool,
    candidate: dict[str, Any],
    summary: dict[str, Any],
    raw_json: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO contract_risk_results (
        run_id,
        token_id,
        pair_id,
        source,

        contract_risk_status,
        contract_risk_pass,
        contract_risk_reason,

        risk_score,
        risk_level,

        mint_authority_status,
        freeze_authority_status,

        top_holders_percent,
        dev_wallet_percent,

        warnings,
        details,
        raw_json
    )
    VALUES (
        $1, $2, $3, 'rugcheck',
        $4, $5, $6,
        $7, $8,
        $9, $10,
        $11, $12,
        $13::jsonb, $14::jsonb, $15::jsonb
    )
    ON CONFLICT (run_id, token_id, source)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,

        contract_risk_status = EXCLUDED.contract_risk_status,
        contract_risk_pass = EXCLUDED.contract_risk_pass,
        contract_risk_reason = EXCLUDED.contract_risk_reason,

        risk_score = EXCLUDED.risk_score,
        risk_level = EXCLUDED.risk_level,

        mint_authority_status = EXCLUDED.mint_authority_status,
        freeze_authority_status = EXCLUDED.freeze_authority_status,

        top_holders_percent = EXCLUDED.top_holders_percent,
        dev_wallet_percent = EXCLUDED.dev_wallet_percent,

        warnings = EXCLUDED.warnings,
        details = EXCLUDED.details,
        raw_json = EXCLUDED.raw_json,
        created_at = NOW()
    RETURNING *;
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            candidate["run_id"],
            candidate["token_id"],
            candidate["pair_id"],

            summary["contract_risk_status"],
            summary["contract_risk_pass"],
            summary["contract_risk_reason"],

            summary["risk_score"],
            summary["risk_level"],

            summary["mint_authority_status"],
            summary["freeze_authority_status"],

            summary["top_holders_percent"],
            summary["dev_wallet_percent"],

            json.dumps(summary["warnings"]),
            json.dumps(summary["details"]),
            json.dumps(raw_json),
        )

    return dict(row)


async def run_contract_risk_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    candidates = await get_market_pass_candidates(pool)

    results = []

    for candidate in candidates:
        try:
            raw_report = await fetch_rugcheck_report(candidate["token_address"])
            summary = extract_rugcheck_summary(raw_report)

        except Exception as e:
            raw_report = {
                "error": str(e),
                "token_address": candidate["token_address"],
            }

            summary = {
                "contract_risk_status": "CONTRACT_UNKNOWN",
                "contract_risk_pass": False,
                "contract_risk_reason": f"RugCheck request failed: {e}",
                "risk_score": None,
                "risk_level": None,
                "mint_authority_status": "UNKNOWN",
                "freeze_authority_status": "UNKNOWN",
                "top_holders_percent": None,
                "dev_wallet_percent": None,
                "warnings": [
                    {
                        "name": "RUGCHECK_REQUEST_FAILED",
                        "level": "UNKNOWN",
                    }
                ],
                "details": {
                    "error": str(e),
                    "no_data": False,
                },
            }

        saved = await save_contract_risk_result(
            pool=pool,
            candidate=candidate,
            summary=summary,
            raw_json=raw_report,
        )

        saved["symbol"] = candidate.get("symbol")
        saved["token_address"] = candidate.get("token_address")

        results.append(saved)

    return results




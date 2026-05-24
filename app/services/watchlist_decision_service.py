import json
from typing import Any

import asyncpg

try:
    from services.liquidity_filter_service import classify_liquidity_trap
except ModuleNotFoundError:
    from app.services.liquidity_filter_service import classify_liquidity_trap

def normalize_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    return []


def normalize_dict(value):
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


def as_number(value, default=0):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_wallet_intelligence(summary: dict[str, Any]) -> dict[str, Any]:
    snipers = as_number(summary.get("snipers"))
    fresh_wallets = as_number(summary.get("fresh_wallets"))
    whales = as_number(summary.get("whales"))
    dumpers = as_number(summary.get("dumpers"))
    dev_related = as_number(summary.get("dev_related"))
    bots = as_number(summary.get("bots"))
    smart_wallets = as_number(summary.get("smart_wallets"))
    avg_wallet_score = as_number(summary.get("avg_wallet_score"), default=None)

    danger_reasons = []
    warning_reasons = []

    if fresh_wallets >= 2:
        danger_reasons.append("Multiple top holders use fresh wallets")

    if fresh_wallets >= 1 and (snipers >= 1 or dev_related >= 1):
        danger_reasons.append("Fresh wallet overlaps with sniper or dev-related activity")

    if dev_related >= 2:
        danger_reasons.append("Multiple top holders look dev-related")

    if dev_related >= 1 and (dumpers >= 1 or bots >= 1 or snipers >= 1):
        danger_reasons.append("Dev-related wallet also overlaps with sniper/dumper/bot activity")

    if bots >= 3:
        danger_reasons.append("Many top holders look automated")

    if dumpers >= 4:
        danger_reasons.append("Many top holders are dumping")

    if snipers >= 5 and dumpers >= 2:
        danger_reasons.append("Many sniper wallets are also selling")

    if avg_wallet_score is not None and avg_wallet_score <= -6:
        danger_reasons.append("Average wallet score is very negative")

    if fresh_wallets >= 1:
        warning_reasons.append("At least one top holder wallet is fresh")

    if snipers >= 2:
        warning_reasons.append("Several top holders entered in the first minute")

    if whales >= 2:
        warning_reasons.append("Several top holders are whales")

    if dumpers >= 1:
        warning_reasons.append("Some top holders already sold a large share")

    if bots >= 1:
        warning_reasons.append("Some top holders look automated")

    if avg_wallet_score is not None and avg_wallet_score <= -3:
        warning_reasons.append("Average wallet score is negative")

    if danger_reasons:
        return {
            "status": "INTELLIGENCE_DANGER",
            "pass": False,
            "reasons": danger_reasons,
        }

    if warning_reasons:
        return {
            "status": "INTELLIGENCE_WARNING",
            "pass": True,
            "reasons": warning_reasons,
        }

    if smart_wallets > 0:
        return {
            "status": "INTELLIGENCE_PASS",
            "pass": True,
            "reasons": ["Smart wallet signal detected"],
        }

    return {
        "status": "INTELLIGENCE_NEUTRAL",
        "pass": True,
        "reasons": [],
    }


def calculate_insider_probability(row: dict[str, Any]) -> dict[str, Any]:
    intelligence_summary = normalize_dict(row.get("intelligence_summary"))

    top_holder = as_number(row.get("top_holder_percent"))
    top10 = as_number(row.get("top10_holders_percent"))
    largest_cluster = as_number(row.get("largest_cluster_size"))
    manipulation_score = as_number(row.get("manipulation_score"))
    snipers = as_number(intelligence_summary.get("snipers"))
    fresh_wallets = as_number(intelligence_summary.get("fresh_wallets"))
    dev_status = row.get("dev_audit_status") or ""
    dev_flow_status = row.get("dev_flow_status") or ""
    shadow_dev_score = as_number(row.get("shadow_dev_score"))

    cluster_status = row.get("cluster_status") or ""
    manipulation_status = row.get("manipulation_status") or ""

    score = 0.0
    reasons = []

    cluster_points = min(30.0, largest_cluster * 4.0)
    if cluster_status == "CLUSTER_DANGER":
        cluster_points = max(cluster_points, 24.0)
    elif cluster_status == "CLUSTER_WARNING":
        cluster_points = max(cluster_points, 14.0)
    if cluster_points:
        reasons.append(f"Shared funding cluster size {int(largest_cluster)}")
    score += cluster_points

    manipulation_points = min(30.0, manipulation_score * 3.0)
    if manipulation_status == "MANIPULATION_DANGER":
        manipulation_points = max(manipulation_points, 24.0)
    elif manipulation_status == "MANIPULATION_WARNING":
        manipulation_points = max(manipulation_points, 14.0)
    if manipulation_points:
        reasons.append(f"Manipulation score {round(manipulation_score)}/10")
    score += manipulation_points

    sniper_points = min(20.0, snipers * 4.0)
    if snipers:
        reasons.append(f"{int(snipers)} sniper wallet(s)")
    score += sniper_points

    fresh_wallet_points = 0.0
    if fresh_wallets >= 3:
        fresh_wallet_points = 30.0
    elif fresh_wallets >= 2:
        fresh_wallet_points = 24.0
    elif fresh_wallets >= 1:
        fresh_wallet_points = 15.0

    if fresh_wallets:
        reasons.append(f"{int(fresh_wallets)} fresh top-holder wallet(s)")
    score += fresh_wallet_points

    dev_points = 0.0
    if dev_status == "DEV_SOLD_OUT":
        dev_points = 25.0
        reasons.append("Developer sold out")
    elif dev_status == "DEV_SOLD_PARTIAL":
        dev_points = 18.0
        reasons.append("Developer sold tokens")
    elif dev_status == "DEV_TRANSFERRED_TOKENS":
        dev_points = 14.0
        reasons.append("Developer transferred tokens")
    elif dev_status == "DEV_NO_BALANCE":
        dev_points = 10.0
        reasons.append("Developer wallet has zero balance")
    score += dev_points

    dev_flow_points = min(35.0, shadow_dev_score * 0.35)
    if dev_flow_status == "DEV_FLOW_DANGER":
        dev_flow_points = max(dev_flow_points, 30.0)
    elif dev_flow_status == "DEV_FLOW_WARNING":
        dev_flow_points = max(dev_flow_points, 14.0)
    if shadow_dev_score:
        reasons.append(f"Shadow Dev Score {round(shadow_dev_score)}/100")
    score += dev_flow_points

    holder_points = 0.0
    if top10 >= 80:
        holder_points += 16.0
        reasons.append("Top 10 holders over 80%")
    elif top10 >= 60:
        holder_points += 12.0
        reasons.append("Top 10 holders over 60%")
    elif top10 >= 40:
        holder_points += 8.0
        reasons.append("Top 10 holders over 40%")
    elif top10 >= 30:
        holder_points += 5.0
        reasons.append("Top 10 holders over 30%")

    if top_holder >= 25:
        holder_points += 4.0
        reasons.append("Top holder over 25%")
    elif top_holder >= 15:
        holder_points += 2.0
        reasons.append("Top holder over 15%")

    score += min(20.0, holder_points)

    probability = int(max(0, min(100, round(score))))
    if probability >= 75:
        level = "CRITICAL"
    elif probability >= 50:
        level = "HIGH"
    elif probability >= 25:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "score": probability,
        "level": level,
        "reasons": reasons,
        "components": {
            "cluster": round(cluster_points, 2),
            "manipulation": round(manipulation_points, 2),
            "snipers": round(sniper_points, 2),
            "fresh_wallets": round(fresh_wallet_points, 2),
            "dev_audit": round(dev_points, 2),
            "dev_flow": round(dev_flow_points, 2),
            "top_holders": round(min(20.0, holder_points), 2),
        },
    }


def classify_watchlist_decision(row: dict[str, Any]) -> dict[str, Any]:
    market_pass = row.get("market_filter_pass")
    market_status = row.get("market_filter_status")

    contract_status = row.get("contract_risk_status")
    contract_pass = row.get("contract_risk_pass")

    liquidity_status = row.get("liquidity_status")
    liquidity_pass = row.get("liquidity_pass")

    wallet_status = row.get("wallet_status")
    wallet_pass = row.get("wallet_pass")

    cluster_status = row.get("cluster_status")
    cluster_pass = row.get("cluster_pass")

    manipulation_status = row.get("manipulation_status")
    manipulation_pass = row.get("manipulation_pass")
    manipulation_reason = row.get("manipulation_reason")
    dev_audit_status = row.get("dev_audit_status")
    dev_audit_reason = row.get("dev_audit_reason")
    dev_flow_status = row.get("dev_flow_status")
    dev_flow_pass = row.get("dev_flow_pass")
    dev_flow_reason = row.get("dev_flow_reason")

    intelligence_summary = normalize_dict(row.get("intelligence_summary"))
    intelligence = classify_wallet_intelligence(intelligence_summary)

    # -----------------------------
    # MARKET FILTER
    # -----------------------------

    if market_pass is False:
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_MARKET",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Rejected by market filter",
        }

    # -----------------------------
    # CONTRACT RISK
    # -----------------------------

    if contract_status is None:
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_SECURITY_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Waiting for contract risk data",
        }

    if contract_status == "CONTRACT_UNKNOWN":
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_SECURITY_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Contract risk data is unknown",
        }

    if contract_pass is False:
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_CONTRACT_RISK",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Rejected by contract risk filter",
        }

    # -----------------------------
    # LIQUIDITY FILTER
    # -----------------------------

    if liquidity_status is None:
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_LIQUIDITY",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Waiting for liquidity analysis",
        }

    if liquidity_status == "LIQUIDITY_UNKNOWN":
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_LIQUIDITY",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Liquidity data is unknown",
        }

    if liquidity_status == "LIQUIDITY_DANGER":
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_LIQUIDITY",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Rejected by liquidity filter",
        }

    # -----------------------------
    # WALLET ANALYSIS
    # -----------------------------

    if wallet_status is None:
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_WALLET_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Waiting for wallet analysis",
        }

    if wallet_status == "WALLET_UNKNOWN":
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_WALLET_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Wallet holder data is unknown",
        }

    if wallet_status == "WALLET_DANGER":
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_WALLET_RISK",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Rejected by wallet concentration filter",
        }

    # -----------------------------
    # CLUSTER ANALYSIS
    # -----------------------------

    if cluster_status is None:
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_CLUSTER_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Waiting for cluster analysis",
        }

    if cluster_status == "CLUSTER_UNKNOWN":
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_CLUSTER_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Cluster funding-source data is unknown",
        }

    if cluster_status == "CLUSTER_DANGER":
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_CLUSTER_RISK",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Rejected by shared funding-source cluster",
        }

    # -----------------------------
    # WALLET MANIPULATION
    # -----------------------------

    if manipulation_status is None:
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_MANIPULATION_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Waiting for wallet manipulation analysis",
        }

    if manipulation_status == "MANIPULATION_UNKNOWN":
        return {
            "final_watchlist_status": "WATCHLIST_WAIT_MANIPULATION_DATA",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "Wallet manipulation data is unknown",
        }

    if manipulation_pass is False:
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_WALLET_MANIPULATION",
            "final_watchlist_pass": False,
            "final_watchlist_reason": manipulation_reason or "Rejected by wallet manipulation analysis",
        }

    # -----------------------------
    # DEV WALLET AUDIT
    # -----------------------------

    if dev_audit_status in {"DEV_SOLD_OUT", "DEV_SOLD_PARTIAL"}:
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_DEV_WALLET",
            "final_watchlist_pass": False,
            "final_watchlist_reason": dev_audit_reason or "Developer wallet sold tokens",
        }

    if dev_flow_pass is False or dev_flow_status == "DEV_FLOW_DANGER":
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_DEV_FLOW",
            "final_watchlist_pass": False,
            "final_watchlist_reason": dev_flow_reason or "Developer-linked proxy wallets dumped or split tokens",
        }

    # -----------------------------
    # WALLET INTELLIGENCE
    # -----------------------------

    if intelligence["status"] == "INTELLIGENCE_DANGER":
        return {
            "final_watchlist_status": "WATCHLIST_REJECT_WALLET_INTELLIGENCE",
            "final_watchlist_pass": False,
            "final_watchlist_reason": "; ".join(intelligence["reasons"]),
        }

    # -----------------------------
    # FINAL PASS
    # -----------------------------

    if (
        market_status == "MARKET_PASS_HIGH_RISK"
        or liquidity_status == "LIQUIDITY_WEAK"
        or liquidity_status == "LIQUIDITY_WARNING"
        or wallet_status == "WALLET_WARNING"
        or cluster_status == "CLUSTER_WARNING"
        or manipulation_status == "MANIPULATION_WARNING"
        or dev_audit_status in {"DEV_TRANSFERRED_TOKENS", "DEV_NO_BALANCE"}
        or dev_flow_status == "DEV_FLOW_WARNING"
        or intelligence["status"] == "INTELLIGENCE_WARNING"
    ):
        reason = "Passed, but risk level is elevated"

        if manipulation_status == "MANIPULATION_WARNING":
            reason = manipulation_reason or reason

        if dev_audit_status in {"DEV_TRANSFERRED_TOKENS", "DEV_NO_BALANCE"}:
            reason = dev_audit_reason or reason

        if dev_flow_status == "DEV_FLOW_WARNING":
            reason = dev_flow_reason or reason

        if intelligence["status"] == "INTELLIGENCE_WARNING":
            reason = "; ".join(intelligence["reasons"])

        return {
            "final_watchlist_status": "WATCHLIST_PASS_HIGH_RISK",
            "final_watchlist_pass": True,
            "final_watchlist_reason": reason,
        }

    if (
        market_status == "MARKET_PASS"
        and contract_pass is True
        and liquidity_pass is True
        and wallet_pass is True
        and cluster_pass is True
        and manipulation_pass is True
    ):
        return {
            "final_watchlist_status": "WATCHLIST_PASS",
            "final_watchlist_pass": True,
            "final_watchlist_reason": "Passed all current filters",
        }

    return {
        "final_watchlist_status": "WATCHLIST_REVIEW",
        "final_watchlist_pass": False,
        "final_watchlist_reason": "Needs manual review",
    }


async def get_watchlist_inputs(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    sql = """
    SELECT
        m.run_id,
        m.token_id,
        m.pair_id,

        t.symbol,
        t.name,
        t.address AS token_address,

        -- MARKET
        m.market_filter_status,
        m.market_filter_pass,
        m.market_filter_reason,
        m.market_warning_level,
        m.market_warnings,

        -- CONTRACT
        c.contract_risk_status,
        c.contract_risk_pass,
        c.contract_risk_reason,
        c.risk_score,
        c.top_holders_percent,
        c.warnings AS contract_warnings,

        -- LIQUIDITY
        l.liquidity_status,
        l.liquidity_pass,
        l.liquidity_reason,
        l.liquidity_usd,
        l.market_cap_usd,
        l.volume_1h_usd,
        l.mcap_to_liquidity_ratio,
        l.volume_to_liquidity_ratio,
        l.warnings AS liquidity_warnings,
        l.details AS liquidity_details,

        -- WALLET
        w.wallet_status,
        w.wallet_pass,
        w.wallet_reason,
        w.top_holder_percent,
        w.top10_holders_percent,
        w.top20_holders_percent,
        w.warnings AS wallet_warnings,

        -- CLUSTER
        cl.cluster_status,
        cl.cluster_pass,
        cl.cluster_reason,
        cl.largest_cluster_size,
        cl.largest_cluster_funder,
        cl.warnings AS cluster_warnings,

        -- WALLET MANIPULATION
        wm.manipulation_status,
        wm.manipulation_pass,
        wm.manipulation_reason,
        wm.manipulation_score,
        wm.warnings AS manipulation_warnings,

        -- DEV WALLET AUDIT
        da.dev_wallet_address,
        da.dev_audit_status,
        da.dev_audit_pass,
        da.dev_audit_reason,
        da.current_balance AS dev_current_balance,
        da.total_token_in AS dev_total_token_in,
        da.total_token_out AS dev_total_token_out,
        da.sold_token_amount AS dev_sold_token_amount,
        da.transferred_token_amount AS dev_transferred_token_amount,
        da.sell_transaction_count AS dev_sell_transaction_count,
        da.transfer_transaction_count AS dev_transfer_transaction_count,
        da.warnings AS dev_audit_warnings,
        da.details AS dev_audit_details,

        -- DEV WALLET FLOW
        df.flow_status AS dev_flow_status,
        df.flow_pass AS dev_flow_pass,
        df.flow_reason AS dev_flow_reason,
        df.shadow_dev_score,
        df.direct_recipient_count AS dev_direct_recipient_count,
        df.tracked_wallet_count AS dev_flow_tracked_wallet_count,
        df.proxy_dump_count AS dev_proxy_dump_count,
        df.splitter_count AS dev_splitter_count,
        df.total_direct_amount AS dev_flow_total_direct_amount,
        df.proxy_sold_amount AS dev_proxy_sold_amount,
        df.warnings AS dev_flow_warnings,
        df.details AS dev_flow_details,

        -- WALLET INTELLIGENCE
        COALESCE(wi.intelligence_summary, '{}'::jsonb) AS intelligence_summary

    FROM market_filter_results m

    JOIN tokens t
        ON t.id = m.token_id

    LEFT JOIN contract_risk_results c
        ON c.token_id = m.token_id
       AND c.run_id = m.run_id

    LEFT JOIN liquidity_filter_results l
        ON l.token_id = m.token_id
       AND l.run_id = m.run_id
       AND l.pair_id = m.pair_id

    LEFT JOIN wallet_analysis_results w
        ON w.token_id = m.token_id
       AND w.run_id = m.run_id

    LEFT JOIN cluster_analysis_results cl
        ON cl.token_id = m.token_id
       AND cl.run_id = m.run_id

    LEFT JOIN wallet_manipulation_results wm
        ON wm.token_id = m.token_id
       AND wm.run_id = m.run_id

    LEFT JOIN dev_wallet_audit_results da
        ON da.token_id = m.token_id
       AND da.run_id = m.run_id

    LEFT JOIN dev_wallet_flow_results df
        ON df.token_id = m.token_id
       AND df.run_id = m.run_id

    LEFT JOIN LATERAL (
        SELECT
            jsonb_build_object(
                'smart_wallets', COUNT(*) FILTER (WHERE labels ? 'SMART_WALLET'),
                'fresh_wallets', COUNT(*) FILTER (WHERE labels ? 'FRESH_WALLET'),
                'snipers', COUNT(*) FILTER (WHERE labels ? 'SNIPER'),
                'whales', COUNT(*) FILTER (WHERE labels ? 'WHALE'),
                'dumpers', COUNT(*) FILTER (WHERE labels ? 'DUMPER'),
                'dev_related', COUNT(*) FILTER (WHERE labels ? 'DEV_RELATED'),
                'bots', COUNT(*) FILTER (WHERE labels ? 'BOT'),
                'unknown', COUNT(*) FILTER (WHERE labels ? 'UNKNOWN'),
                'avg_wallet_score', ROUND(AVG(wallet_score), 2)
            ) AS intelligence_summary
        FROM wallet_intelligence_results wi
        WHERE wi.token_id = m.token_id
          AND wi.run_id = m.run_id
    ) wi ON TRUE

    ORDER BY m.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [dict(row) for row in rows]


async def save_watchlist_decision(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO watchlist_decisions (
        run_id,
        token_id,
        pair_id,

        market_filter_status,
        market_filter_pass,
        market_warning_level,

        contract_risk_status,
        contract_risk_pass,
        risk_score,
        top_holders_percent,
        wallet_status,
        wallet_pass,
        top_holder_percent,
        top10_holders_percent,
        cluster_status,
        cluster_pass,
        largest_cluster_size,
        largest_cluster_funder,
        manipulation_status,
        manipulation_pass,
        manipulation_score,

        final_watchlist_status,
        final_watchlist_pass,
        final_watchlist_reason,
        intelligence_summary,

        details
    )
    VALUES (
        $1, $2, $3,
        $4, $5, $6,
        $7, $8, $9, $10,
        $11, $12, $13, $14,
        $15, $16, $17, $18,
        $19, $20, $21,
        $22, $23, $24,
        $25::jsonb,
        $26::jsonb
    )
    ON CONFLICT (run_id, token_id)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,

        market_filter_status = EXCLUDED.market_filter_status,
        market_filter_pass = EXCLUDED.market_filter_pass,
        market_warning_level = EXCLUDED.market_warning_level,

        contract_risk_status = EXCLUDED.contract_risk_status,
        contract_risk_pass = EXCLUDED.contract_risk_pass,
        risk_score = EXCLUDED.risk_score,
        top_holders_percent = EXCLUDED.top_holders_percent,
        wallet_status = EXCLUDED.wallet_status,
        wallet_pass = EXCLUDED.wallet_pass,
        top_holder_percent = EXCLUDED.top_holder_percent,
        top10_holders_percent = EXCLUDED.top10_holders_percent,
        cluster_status = EXCLUDED.cluster_status,
        cluster_pass = EXCLUDED.cluster_pass,
        largest_cluster_size = EXCLUDED.largest_cluster_size,
        largest_cluster_funder = EXCLUDED.largest_cluster_funder,
        manipulation_status = EXCLUDED.manipulation_status,
        manipulation_pass = EXCLUDED.manipulation_pass,
        manipulation_score = EXCLUDED.manipulation_score,

        final_watchlist_status = EXCLUDED.final_watchlist_status,
        final_watchlist_pass = EXCLUDED.final_watchlist_pass,
        final_watchlist_reason = EXCLUDED.final_watchlist_reason,
        intelligence_summary = EXCLUDED.intelligence_summary,

        details = EXCLUDED.details,
        created_at = NOW()

    RETURNING *;
    """

    market_warnings = normalize_list(row.get("market_warnings"))
    contract_warnings = normalize_list(row.get("contract_warnings"))
    liquidity_warnings = normalize_list(row.get("liquidity_warnings"))
    liquidity_details = normalize_dict(row.get("liquidity_details"))
    if "liquidity_trap_score" not in liquidity_details:
        liquidity_details.update(
            classify_liquidity_trap(
                liquidity=as_number(row.get("liquidity_usd"), default=None),
                mcap_to_liquidity_ratio=as_number(row.get("mcap_to_liquidity_ratio"), default=None),
                volume_to_liquidity_ratio=as_number(row.get("volume_to_liquidity_ratio"), default=None),
            )
        )
    wallet_warnings = normalize_list(row.get("wallet_warnings"))
    cluster_warnings = normalize_list(row.get("cluster_warnings"))
    manipulation_warnings = normalize_list(row.get("manipulation_warnings"))
    dev_audit_warnings = normalize_list(row.get("dev_audit_warnings"))
    dev_audit_details = normalize_dict(row.get("dev_audit_details"))
    dev_flow_warnings = normalize_list(row.get("dev_flow_warnings"))
    dev_flow_details = normalize_dict(row.get("dev_flow_details"))
    intelligence_summary = normalize_dict(row.get("intelligence_summary"))
    intelligence = classify_wallet_intelligence(intelligence_summary)
    insider_probability = calculate_insider_probability(row)

    high_risk_reasons = []

    if isinstance(market_warnings, list):
        high_risk_reasons.extend(market_warnings)

    if isinstance(contract_warnings, list):
        for warning in contract_warnings:
            if isinstance(warning, dict):
                name = warning.get("name")
                if name:
                    high_risk_reasons.append(name)
            elif isinstance(warning, str):
                high_risk_reasons.append(warning)

    if isinstance(liquidity_warnings, list):
        high_risk_reasons.extend(liquidity_warnings)

    if isinstance(wallet_warnings, list):
        high_risk_reasons.extend(wallet_warnings)

    if isinstance(cluster_warnings, list):
        high_risk_reasons.extend(cluster_warnings)

    if isinstance(manipulation_warnings, list):
        high_risk_reasons.extend(manipulation_warnings)

    if isinstance(dev_audit_warnings, list):
        high_risk_reasons.extend(dev_audit_warnings)

    if isinstance(dev_flow_warnings, list):
        high_risk_reasons.extend(dev_flow_warnings)

    high_risk_reasons.extend(intelligence.get("reasons") or [])

    details = {
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "token_address": row.get("token_address"),

        "market_filter_reason": row.get("market_filter_reason"),
        "contract_risk_reason": row.get("contract_risk_reason"),

        "market_warnings": market_warnings,
        "contract_warnings": contract_warnings,
        "liquidity_warnings": liquidity_warnings,
        "wallet_warnings": wallet_warnings,
        "cluster_warnings": cluster_warnings,

        "high_risk_reasons": high_risk_reasons,

        "liquidity_status": row.get("liquidity_status"),
        "liquidity_reason": row.get("liquidity_reason"),
        "liquidity_trap_status": liquidity_details.get("liquidity_trap_status"),
        "liquidity_trap_score": liquidity_details.get("liquidity_trap_score"),
        "liquidity_trap_reason": liquidity_details.get("liquidity_trap_reason"),
        "liquidity_trap_warnings": liquidity_details.get("liquidity_trap_warnings", []),
        "liquidity_trap_components": liquidity_details.get("liquidity_trap_components", {}),
        "lp_lock": liquidity_details.get("lp_lock", {}),

        "liquidity_usd": row.get("liquidity_usd"),
        "market_cap_usd": row.get("market_cap_usd"),
        "volume_1h_usd": row.get("volume_1h_usd"),

        "mcap_to_liquidity_ratio": row.get("mcap_to_liquidity_ratio"),
        "volume_to_liquidity_ratio": row.get("volume_to_liquidity_ratio"),

        "wallet_status": row.get("wallet_status"),
        "wallet_reason": row.get("wallet_reason"),
        "top_holder_percent": row.get("top_holder_percent"),
        "top10_holders_percent": row.get("top10_holders_percent"),
        "top20_holders_percent": row.get("top20_holders_percent"),

        "cluster_status": row.get("cluster_status"),
        "cluster_reason": row.get("cluster_reason"),
        "largest_cluster_size": row.get("largest_cluster_size"),
        "largest_cluster_funder": row.get("largest_cluster_funder"),

        "manipulation_status": row.get("manipulation_status"),
        "manipulation_reason": row.get("manipulation_reason"),
        "manipulation_score": row.get("manipulation_score"),
        "manipulation_warnings": manipulation_warnings,

        "dev_wallet_address": row.get("dev_wallet_address"),
        "dev_audit_status": row.get("dev_audit_status"),
        "dev_audit_pass": row.get("dev_audit_pass"),
        "dev_audit_reason": row.get("dev_audit_reason"),
        "dev_current_balance": row.get("dev_current_balance"),
        "dev_total_token_in": row.get("dev_total_token_in"),
        "dev_total_token_out": row.get("dev_total_token_out"),
        "dev_sold_token_amount": row.get("dev_sold_token_amount"),
        "dev_transferred_token_amount": row.get("dev_transferred_token_amount"),
        "dev_sell_transaction_count": row.get("dev_sell_transaction_count"),
        "dev_transfer_transaction_count": row.get("dev_transfer_transaction_count"),
        "dev_audit_warnings": dev_audit_warnings,
        "dev_audit_details": dev_audit_details,

        "dev_flow_status": row.get("dev_flow_status"),
        "dev_flow_pass": row.get("dev_flow_pass"),
        "dev_flow_reason": row.get("dev_flow_reason"),
        "shadow_dev_score": row.get("shadow_dev_score"),
        "dev_direct_recipient_count": row.get("dev_direct_recipient_count"),
        "dev_flow_tracked_wallet_count": row.get("dev_flow_tracked_wallet_count"),
        "dev_proxy_dump_count": row.get("dev_proxy_dump_count"),
        "dev_splitter_count": row.get("dev_splitter_count"),
        "dev_flow_total_direct_amount": row.get("dev_flow_total_direct_amount"),
        "dev_proxy_sold_amount": row.get("dev_proxy_sold_amount"),
        "dev_flow_warnings": dev_flow_warnings,
        "dev_flow_details": dev_flow_details,

        "intelligence_status": intelligence.get("status"),
        "intelligence_reasons": intelligence.get("reasons"),
        "intelligence_summary": intelligence_summary,

        "insider_probability_score": insider_probability["score"],
        "insider_probability_level": insider_probability["level"],
        "insider_probability_reasons": insider_probability["reasons"],
        "insider_probability_components": insider_probability["components"],
    }

    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            sql,
            row["run_id"],
            row["token_id"],
            row["pair_id"],

            row["market_filter_status"],
            row["market_filter_pass"],
            row["market_warning_level"],

            row["contract_risk_status"],
            row["contract_risk_pass"],
            row["risk_score"],
            row["top_holders_percent"],

            row["wallet_status"],
            row["wallet_pass"],
            row["top_holder_percent"],
            row["top10_holders_percent"],

            row["cluster_status"],
            row["cluster_pass"],
            row["largest_cluster_size"],
            row["largest_cluster_funder"],

            row.get("manipulation_status"),
            row.get("manipulation_pass"),
            row.get("manipulation_score"),

            decision["final_watchlist_status"],
            decision["final_watchlist_pass"],
            decision["final_watchlist_reason"],

            json.dumps(intelligence_summary, default=str),
            json.dumps(details, default=str),
        )

    return dict(saved)


async def run_watchlist_decision_service(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await get_watchlist_inputs(pool)

    results = []

    for row in rows:
        decision = classify_watchlist_decision(row)

        saved = await save_watchlist_decision(
            pool=pool,
            row=row,
            decision=decision,
        )

        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")

        saved["liquidity_status"] = row.get("liquidity_status")
        saved["liquidity_pass"] = row.get("liquidity_pass")
        saved["wallet_status"] = row.get("wallet_status")
        saved["wallet_pass"] = row.get("wallet_pass")
        saved["cluster_status"] = row.get("cluster_status")
        saved["cluster_pass"] = row.get("cluster_pass")

        results.append(saved)

    return results

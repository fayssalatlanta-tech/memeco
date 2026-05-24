import json
from decimal import Decimal

import asyncpg

from validation import require_keys


VALID_RISK_LEVELS = {"PASS", "INFO", "WARNING", "DANGER", "UNKNOWN"}

MIN_LIQUIDITY_USD = Decimal("5000")
MIN_VOLUME_5M_USD = Decimal("1000")


async def insert_risk_check(
    pool: asyncpg.Pool,
    token_id: int,
    pair_id: int | None,
    run_id: int | None,
    check_category: str,
    check_name: str,
    risk_level: str,
    score: float | None = None,
    details: dict | None = None,
) -> dict:
    """
    Insert one risk check result for a token/pair.
    """

    risk_data = {
        "token_id": token_id,
        "check_category": check_category,
        "check_name": check_name,
        "risk_level": risk_level,
    }

    require_keys(
        risk_data,
        ["token_id", "check_category", "check_name", "risk_level"],
        context="risk_check",
    )

    if risk_level not in VALID_RISK_LEVELS:
        raise ValueError(
            f"Invalid risk_level: {risk_level}. "
            f"Allowed values: {sorted(VALID_RISK_LEVELS)}"
        )

    sql = """
    INSERT INTO risk_checks (
        token_id,
        pair_id,
        run_id,
        check_category,
        check_name,
        risk_level,
        score,
        details
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
    RETURNING
        id,
        token_id,
        pair_id,
        run_id,
        check_category,
        check_name,
        risk_level,
        score,
        details,
        created_at;
    """

    json_details = json.dumps(details) if details is not None else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql,
            token_id,
            pair_id,
            run_id,
            check_category,
            check_name,
            risk_level,
            score,
            json_details,
        )

    return dict(row)


async def add_basic_risk_checks(
    pool: asyncpg.Pool,
    token_id: int,
    pair_id: int,
    run_id: int,
    token_address: str,
    pair_address: str,
    price_usd,
    liquidity_usd,
    volume_5m_usd,
    volume_1h_usd,
    market_cap_usd,
    fdv_usd,
    pair_created_at,
    txns,
    price_change,
) -> None:
    """
    Basic first-stage risk checks using DexScreener market data.
    """

    # Price check
    if price_usd is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="market",
            check_name="missing_price",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return priceUsd",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="market",
            check_name="price_available",
            risk_level="PASS",
            score=0,
            details={"price_usd": str(price_usd)},
        )

    # Liquidity check
    if liquidity_usd is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="liquidity",
            check_name="missing_liquidity",
            risk_level="UNKNOWN",
            score=60,
            details={
                "reason": "DexScreener did not return liquidity.usd",
                "min_required_usd": str(MIN_LIQUIDITY_USD),
            },
        )
    elif liquidity_usd < MIN_LIQUIDITY_USD:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="liquidity",
            check_name="low_liquidity",
            risk_level="DANGER",
            score=90,
            details={
                "liquidity_usd": str(liquidity_usd),
                "min_required_usd": str(MIN_LIQUIDITY_USD),
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="liquidity",
            check_name="liquidity_ok",
            risk_level="PASS",
            score=10,
            details={
                "liquidity_usd": str(liquidity_usd),
                "min_required_usd": str(MIN_LIQUIDITY_USD),
            },
        )

    # 5m volume check
    if volume_5m_usd is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="market",
            check_name="missing_volume_5m",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return volume.m5",
                "min_required_usd": str(MIN_VOLUME_5M_USD),
            },
        )
    elif volume_5m_usd < MIN_VOLUME_5M_USD:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="market",
            check_name="low_volume_5m",
            risk_level="WARNING",
            score=60,
            details={
                "volume_5m_usd": str(volume_5m_usd),
                "min_required_usd": str(MIN_VOLUME_5M_USD),
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="market",
            check_name="volume_5m_ok",
            risk_level="PASS",
            score=10,
            details={
                "volume_5m_usd": str(volume_5m_usd),
                "min_required_usd": str(MIN_VOLUME_5M_USD),
            },
        )
            # 1h volume data quality check
    if volume_1h_usd is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="missing_volume_1h",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return volume.h1",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="volume_1h_available",
            risk_level="PASS",
            score=0,
            details={"volume_1h_usd": str(volume_1h_usd)},
        )

    # Market cap data quality check
    if market_cap_usd is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="missing_market_cap",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return marketCap",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="market_cap_available",
            risk_level="PASS",
            score=0,
            details={"market_cap_usd": str(market_cap_usd)},
        )

    # FDV data quality check
    if fdv_usd is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="missing_fdv",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return fdv",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="fdv_available",
            risk_level="PASS",
            score=0,
            details={"fdv_usd": str(fdv_usd)},
        )

    # Pair created at data quality check
    if pair_created_at is None:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="missing_pair_created_at",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return pairCreatedAt",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="pair_created_at_available",
            risk_level="PASS",
            score=0,
            details={"pair_created_at": str(pair_created_at)},
        )

    # TXNS data quality check
    if not txns:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="missing_txns",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return txns",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="txns_available",
            risk_level="PASS",
            score=0,
            details={"txns": txns},
        )

    # Price change data quality check
    if not price_change:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="missing_price_change",
            risk_level="UNKNOWN",
            score=50,
            details={
                "reason": "DexScreener did not return priceChange",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        )
    else:
        await insert_risk_check(
            pool=pool,
            token_id=token_id,
            pair_id=pair_id,
            run_id=run_id,
            check_category="data_quality",
            check_name="price_change_available",
            risk_level="PASS",
            score=0,
            details={"price_change": price_change},
        )
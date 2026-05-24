import json
from decimal import Decimal
from typing import Any

import asyncpg

from app.validation import require_keys

VALID_RISK_LEVELS = {"PASS", "INFO", "WARNING", "DANGER", "UNKNOWN"}

MIN_LIQUIDITY_USD = Decimal("5000")
MIN_VOLUME_5M_USD = Decimal("1000")


def _validated_row(
    token_id: int,
    pair_id: int | None,
    run_id: int | None,
    check_category: str,
    check_name: str,
    risk_level: str,
    score: float | None,
    details: dict | None,
) -> tuple[Any, ...]:
    """Validate one risk_check row and return the tuple ready for insertion."""
    require_keys(
        {
            "token_id": token_id,
            "check_category": check_category,
            "check_name": check_name,
            "risk_level": risk_level,
        },
        ["token_id", "check_category", "check_name", "risk_level"],
        context="risk_check",
    )

    if risk_level not in VALID_RISK_LEVELS:
        raise ValueError(
            f"Invalid risk_level: {risk_level}. "
            f"Allowed values: {sorted(VALID_RISK_LEVELS)}"
        )

    json_details = json.dumps(details) if details is not None else None

    return (
        token_id,
        pair_id,
        run_id,
        check_category,
        check_name,
        risk_level,
        score,
        json_details,
    )


_INSERT_RISK_CHECK_SQL = """
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

_INSERT_RISK_CHECK_BULK_SQL = """
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
VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb);
"""


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
    Insert one risk check result for a token/pair and return the new row.

    Use this for occasional one-off inserts where you want the returned row.
    For the basic ingest checks (10+ rows per token) use
    :func:`insert_risk_checks` which batches into a single transaction.
    """
    row_tuple = _validated_row(
        token_id=token_id,
        pair_id=pair_id,
        run_id=run_id,
        check_category=check_category,
        check_name=check_name,
        risk_level=risk_level,
        score=score,
        details=details,
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(_INSERT_RISK_CHECK_SQL, *row_tuple)

    return dict(row)


async def insert_risk_checks(
    pool: asyncpg.Pool,
    rows: list[dict[str, Any]],
) -> int:
    """
    Bulk-insert many risk_check rows in a single transaction / round-trip.

    Each item in ``rows`` is a dict with keys::

        token_id, pair_id, run_id, check_category, check_name,
        risk_level, score, details

    Returns the number of rows inserted. No-ops if ``rows`` is empty.
    """
    if not rows:
        return 0

    validated = [
        _validated_row(
            token_id=row["token_id"],
            pair_id=row.get("pair_id"),
            run_id=row.get("run_id"),
            check_category=row["check_category"],
            check_name=row["check_name"],
            risk_level=row["risk_level"],
            score=row.get("score"),
            details=row.get("details"),
        )
        for row in rows
    ]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_RISK_CHECK_BULK_SQL, validated)

    return len(validated)


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
) -> int:
    """
    First-stage market / data-quality risk checks based on DexScreener fields.

    All checks are batched into a single transaction (one ``pool.acquire()``
    plus one ``executemany``) instead of opening a fresh connection per row.
    Returns the number of rows inserted.
    """
    rows: list[dict[str, Any]] = []

    # Price check
    if price_usd is None:
        rows.append(_data_quality_unknown_row(
            token_id, pair_id, run_id,
            check_category="market",
            check_name="missing_price",
            score=50,
            details={
                "reason": "DexScreener did not return priceUsd",
                "token_address": token_address,
                "pair_address": pair_address,
            },
        ))
    else:
        rows.append(_pass_row(
            token_id, pair_id, run_id,
            check_category="market",
            check_name="price_available",
            score=0,
            details={"price_usd": str(price_usd)},
        ))

    # Liquidity check
    if liquidity_usd is None:
        rows.append(_data_quality_unknown_row(
            token_id, pair_id, run_id,
            check_category="liquidity",
            check_name="missing_liquidity",
            score=60,
            details={
                "reason": "DexScreener did not return liquidity.usd",
                "min_required_usd": str(MIN_LIQUIDITY_USD),
            },
        ))
    elif liquidity_usd < MIN_LIQUIDITY_USD:
        rows.append({
            "token_id": token_id, "pair_id": pair_id, "run_id": run_id,
            "check_category": "liquidity", "check_name": "low_liquidity",
            "risk_level": "DANGER", "score": 90,
            "details": {
                "liquidity_usd": str(liquidity_usd),
                "min_required_usd": str(MIN_LIQUIDITY_USD),
            },
        })
    else:
        rows.append(_pass_row(
            token_id, pair_id, run_id,
            check_category="liquidity",
            check_name="liquidity_ok",
            score=10,
            details={
                "liquidity_usd": str(liquidity_usd),
                "min_required_usd": str(MIN_LIQUIDITY_USD),
            },
        ))

    # 5m volume check
    if volume_5m_usd is None:
        rows.append(_data_quality_unknown_row(
            token_id, pair_id, run_id,
            check_category="market",
            check_name="missing_volume_5m",
            score=50,
            details={
                "reason": "DexScreener did not return volume.m5",
                "min_required_usd": str(MIN_VOLUME_5M_USD),
            },
        ))
    elif volume_5m_usd < MIN_VOLUME_5M_USD:
        rows.append({
            "token_id": token_id, "pair_id": pair_id, "run_id": run_id,
            "check_category": "market", "check_name": "low_volume_5m",
            "risk_level": "WARNING", "score": 60,
            "details": {
                "volume_5m_usd": str(volume_5m_usd),
                "min_required_usd": str(MIN_VOLUME_5M_USD),
            },
        })
    else:
        rows.append(_pass_row(
            token_id, pair_id, run_id,
            check_category="market",
            check_name="volume_5m_ok",
            score=10,
            details={
                "volume_5m_usd": str(volume_5m_usd),
                "min_required_usd": str(MIN_VOLUME_5M_USD),
            },
        ))

    # 1h volume data quality check
    rows.append(_dq_pair(
        token_id, pair_id, run_id,
        present=volume_1h_usd is not None,
        check_name_present="volume_1h_available",
        check_name_missing="missing_volume_1h",
        missing_reason="DexScreener did not return volume.h1",
        present_details={"volume_1h_usd": str(volume_1h_usd) if volume_1h_usd is not None else None},
        token_address=token_address,
        pair_address=pair_address,
    ))

    # Market cap data quality check
    rows.append(_dq_pair(
        token_id, pair_id, run_id,
        present=market_cap_usd is not None,
        check_name_present="market_cap_available",
        check_name_missing="missing_market_cap",
        missing_reason="DexScreener did not return marketCap",
        present_details={"market_cap_usd": str(market_cap_usd) if market_cap_usd is not None else None},
        token_address=token_address,
        pair_address=pair_address,
    ))

    # FDV data quality check
    rows.append(_dq_pair(
        token_id, pair_id, run_id,
        present=fdv_usd is not None,
        check_name_present="fdv_available",
        check_name_missing="missing_fdv",
        missing_reason="DexScreener did not return fdv",
        present_details={"fdv_usd": str(fdv_usd) if fdv_usd is not None else None},
        token_address=token_address,
        pair_address=pair_address,
    ))

    # Pair created at data quality check
    rows.append(_dq_pair(
        token_id, pair_id, run_id,
        present=pair_created_at is not None,
        check_name_present="pair_created_at_available",
        check_name_missing="missing_pair_created_at",
        missing_reason="DexScreener did not return pairCreatedAt",
        present_details={"pair_created_at": str(pair_created_at) if pair_created_at is not None else None},
        token_address=token_address,
        pair_address=pair_address,
    ))

    # TXNS data quality check
    rows.append(_dq_pair(
        token_id, pair_id, run_id,
        present=bool(txns),
        check_name_present="txns_available",
        check_name_missing="missing_txns",
        missing_reason="DexScreener did not return txns",
        present_details={"txns": txns},
        token_address=token_address,
        pair_address=pair_address,
    ))

    # Price change data quality check
    rows.append(_dq_pair(
        token_id, pair_id, run_id,
        present=bool(price_change),
        check_name_present="price_change_available",
        check_name_missing="missing_price_change",
        missing_reason="DexScreener did not return priceChange",
        present_details={"price_change": price_change},
        token_address=token_address,
        pair_address=pair_address,
    ))

    return await insert_risk_checks(pool, rows)


async def record_data_unavailable(
    pool: asyncpg.Pool,
    token_id: int,
    pair_id: int | None,
    run_id: int | None,
    source: str,
    endpoint: str,
    reason: str,
    token_address: str | None = None,
) -> dict:
    """
    Record a single ``data_unavailable`` risk_check row when an upstream API
    (DexScreener, Helius, ...) was reachable-but-broken after retries.

    This is the canonical way to surface "we tried, upstream was down" in
    the watchlist data, instead of silently writing a misleading empty
    analysis. It is invoked from :mod:`app.ingest_dexscreener` when the
    DexScreener pair fetch raises :class:`UpstreamUnavailable`.
    """
    return await insert_risk_check(
        pool=pool,
        token_id=token_id,
        pair_id=pair_id,
        run_id=run_id,
        check_category="data_quality",
        check_name="upstream_unavailable",
        risk_level="UNKNOWN",
        score=70,
        details={
            "reason": reason,
            "source": source,
            "endpoint": endpoint,
            "token_address": token_address,
        },
    )


# ---- Internal helpers ------------------------------------------------------


def _pass_row(
    token_id: int,
    pair_id: int | None,
    run_id: int | None,
    *,
    check_category: str,
    check_name: str,
    score: float,
    details: dict,
) -> dict[str, Any]:
    return {
        "token_id": token_id,
        "pair_id": pair_id,
        "run_id": run_id,
        "check_category": check_category,
        "check_name": check_name,
        "risk_level": "PASS",
        "score": score,
        "details": details,
    }


def _data_quality_unknown_row(
    token_id: int,
    pair_id: int | None,
    run_id: int | None,
    *,
    check_category: str,
    check_name: str,
    score: float,
    details: dict,
) -> dict[str, Any]:
    return {
        "token_id": token_id,
        "pair_id": pair_id,
        "run_id": run_id,
        "check_category": check_category,
        "check_name": check_name,
        "risk_level": "UNKNOWN",
        "score": score,
        "details": details,
    }


def _dq_pair(
    token_id: int,
    pair_id: int | None,
    run_id: int | None,
    *,
    present: bool,
    check_name_present: str,
    check_name_missing: str,
    missing_reason: str,
    present_details: dict,
    token_address: str,
    pair_address: str,
) -> dict[str, Any]:
    """Build either a PASS row or an UNKNOWN row for a data-quality probe."""
    if present:
        return _pass_row(
            token_id, pair_id, run_id,
            check_category="data_quality",
            check_name=check_name_present,
            score=0,
            details=present_details,
        )
    return _data_quality_unknown_row(
        token_id, pair_id, run_id,
        check_category="data_quality",
        check_name=check_name_missing,
        score=50,
        details={
            "reason": missing_reason,
            "token_address": token_address,
            "pair_address": pair_address,
        },
    )

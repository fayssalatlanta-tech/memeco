import json
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from app.helius import HeliusClient

LAMPORTS_PER_SOL = 1_000_000_000
WHALE_HOLDER_PERCENT = 5.0
TOP_RANK_WHALE_PERCENT = 1.5
SNIPER_SECONDS = 60
EARLY_BUY_SECONDS = 300
DUMPER_SELL_RATIO = 0.65
DUMPER_NEGATIVE_SELL_RATIO = 0.4
BOT_DEX_TX_COUNT = 25
BOT_BURST_DEX_TX_COUNT = 12
BOT_BURST_WINDOW_SECONDS = 600
BOT_TX_PER_MINUTE = 3.0
SHARED_FUNDER_DANGER_COUNT = 3
SHARED_FUNDER_WARNING_COUNT = 2
FRESH_WALLET_SECONDS = 24 * 60 * 60
WALLET_HISTORY_LIMIT = 100
EARLY_BUYER_LIMIT = 20


def unix_to_datetime(value) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def safe_float(value) -> float:
    if value is None:
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def token_transfer_mint(transfer: dict[str, Any]) -> str | None:
    return (
        transfer.get("mint")
        or transfer.get("mintAddress")
        or transfer.get("tokenMint")
    )


def token_transfer_amount(transfer: dict[str, Any]) -> float:
    return safe_float(
        transfer.get("tokenAmount")
        or transfer.get("amount")
        or transfer.get("rawTokenAmount", {}).get("tokenAmount")
    )


def native_transfer_amount(transfer: dict[str, Any]) -> float:
    return safe_float(transfer.get("amount")) / LAMPORTS_PER_SOL


def native_flow_for_wallet(wallet_address: str, transfers: list[dict[str, Any]]) -> tuple[float, float]:
    native_in = 0.0
    native_out = 0.0

    for transfer in transfers:
        if not isinstance(transfer, dict):
            continue

        amount = native_transfer_amount(transfer)
        if amount <= 0:
            continue

        if transfer.get("toUserAccount") == wallet_address:
            native_in += amount

        if transfer.get("fromUserAccount") == wallet_address:
            native_out += amount

    return native_in, native_out


def analyze_wallet_transactions(
    wallet_address: str,
    token_address: str,
    pair_created_at: datetime | None,
    rank: int | None,
    holder_percent: float,
    funding_source: str | None,
    funding_source_holder_count: int,
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    labels = []
    label_reasons = {}
    token_in = 0.0
    token_out = 0.0
    native_spent = 0.0
    native_received = 0.0
    entry_times = []
    exit_times = []
    transaction_times = []
    dex_like_tx_count = 0

    for tx in transactions:
        token_transfers = tx.get("tokenTransfers") or []
        native_transfers = tx.get("nativeTransfers") or []
        tx_time = unix_to_datetime(tx.get("timestamp"))

        if tx_time:
            transaction_times.append(tx_time)

        if tx.get("type") in {"SWAP", "UNKNOWN"} and token_transfers:
            dex_like_tx_count += 1

        if not isinstance(token_transfers, list):
            continue

        tx_token_in = 0.0
        tx_token_out = 0.0

        for transfer in token_transfers:
            if not isinstance(transfer, dict):
                continue

            if token_transfer_mint(transfer) != token_address:
                continue

            amount = token_transfer_amount(transfer)
            to_account = transfer.get("toUserAccount")
            from_account = transfer.get("fromUserAccount")

            if to_account == wallet_address:
                token_in += amount
                tx_token_in += amount
                if tx_time:
                    entry_times.append(tx_time)

            if from_account == wallet_address:
                token_out += amount
                tx_token_out += amount
                if tx_time:
                    exit_times.append(tx_time)

        if isinstance(native_transfers, list) and (tx_token_in > 0 or tx_token_out > 0):
            tx_native_in, tx_native_out = native_flow_for_wallet(wallet_address, native_transfers)

            if tx_token_in > 0:
                native_spent += tx_native_out

            if tx_token_out > 0:
                native_received += tx_native_in

    first_entry_at = min(entry_times) if entry_times else None
    first_exit_at = min(exit_times) if exit_times else None
    seconds_from_launch = None

    if first_entry_at and pair_created_at:
        if pair_created_at.tzinfo is None:
            pair_created_at = pair_created_at.replace(tzinfo=timezone.utc)
        seconds_from_launch = int((first_entry_at - pair_created_at).total_seconds())

    net_token_amount = token_in - token_out
    sell_ratio = token_out / token_in if token_in > 0 else 0
    avg_cost_native = native_spent / token_in if token_in > 0 and native_spent > 0 else None
    realized_cost_native = (
        min(token_out, token_in) * avg_cost_native
        if avg_cost_native is not None and token_out > 0
        else None
    )
    realized_pnl_native = (
        native_received - realized_cost_native
        if realized_cost_native is not None and native_received > 0
        else None
    )
    realized_roi = (
        realized_pnl_native / realized_cost_native
        if realized_pnl_native is not None and realized_cost_native and realized_cost_native > 0
        else None
    )
    early_buyer_status = classify_early_buyer_status(token_in, token_out, net_token_amount)
    profit_state = classify_profit_state(realized_pnl_native, native_received, native_spent)
    active_seconds = None
    tx_per_minute = 0.0
    wallet_age_seconds = None
    oldest_seen_transaction_at = None
    history_may_be_truncated = len(transactions) >= WALLET_HISTORY_LIMIT

    if transaction_times:
        oldest_seen_transaction_at = min(transaction_times)
        wallet_age_seconds = int(
            (datetime.now(timezone.utc) - oldest_seen_transaction_at).total_seconds()
        )
        active_seconds = max(
            1,
            int((max(transaction_times) - min(transaction_times)).total_seconds()),
        )
        tx_per_minute = len(transaction_times) / (active_seconds / 60)

    if holder_percent >= WHALE_HOLDER_PERCENT or (
        rank is not None and rank <= 3 and holder_percent >= TOP_RANK_WHALE_PERCENT
    ):
        labels.append("WHALE")
        label_reasons["WHALE"] = (
            f"Holder owns {round(holder_percent, 2)}% of supply"
            if holder_percent >= WHALE_HOLDER_PERCENT
            else f"Top {rank} holder with {round(holder_percent, 2)}% of supply"
        )

    if seconds_from_launch is not None and 0 <= seconds_from_launch <= SNIPER_SECONDS:
        labels.append("SNIPER")
        label_reasons["SNIPER"] = f"First token entry was {seconds_from_launch}s after launch"

    if (
        wallet_age_seconds is not None
        and 0 <= wallet_age_seconds <= FRESH_WALLET_SECONDS
        and not history_may_be_truncated
    ):
        labels.append("FRESH_WALLET")
        label_reasons["FRESH_WALLET"] = (
            f"Oldest seen wallet transaction is {round(wallet_age_seconds / 3600, 2)}h old"
        )

    if token_in > 0 and (
        sell_ratio >= DUMPER_SELL_RATIO
        or (net_token_amount < 0 and sell_ratio >= DUMPER_NEGATIVE_SELL_RATIO)
    ):
        labels.append("DUMPER")
        label_reasons["DUMPER"] = (
            f"Sold {round(sell_ratio * 100, 2)}% of received tokens"
        )

    shared_funder_danger = funding_source and funding_source_holder_count >= SHARED_FUNDER_DANGER_COUNT
    shared_funder_warning = (
        funding_source
        and funding_source_holder_count >= SHARED_FUNDER_WARNING_COUNT
        and (holder_percent >= 1 or "SNIPER" in labels or "WHALE" in labels)
    )

    if shared_funder_danger or shared_funder_warning:
        labels.append("DEV_RELATED")
        label_reasons["DEV_RELATED"] = (
            f"{funding_source_holder_count} top holders share the same funding source"
        )

    if (
        dex_like_tx_count >= BOT_DEX_TX_COUNT
        or (
            dex_like_tx_count >= BOT_BURST_DEX_TX_COUNT
            and active_seconds is not None
            and active_seconds <= BOT_BURST_WINDOW_SECONDS
        )
        or (len(transactions) >= 15 and tx_per_minute >= BOT_TX_PER_MINUTE)
    ):
        labels.append("BOT")
        label_reasons["BOT"] = (
            f"{dex_like_tx_count} DEX-like transactions, "
            f"{round(tx_per_minute, 2)} tx/min"
        )

    if (
        0.2 <= holder_percent <= 8
        and token_in > 0
        and net_token_amount > 0
        and sell_ratio <= 0.2
        and (seconds_from_launch is None or seconds_from_launch > EARLY_BUY_SECONDS)
        and not {"SNIPER", "FRESH_WALLET", "DUMPER", "DEV_RELATED", "BOT"}.intersection(labels)
    ):
        labels.append("SMART_WALLET")
        label_reasons["SMART_WALLET"] = (
            "Healthy holder profile: positive net position, low sell ratio, no insider/bot signals"
        )

    if not labels:
        labels.append("UNKNOWN")
        label_reasons["UNKNOWN"] = "Not enough strong evidence for a specific label"

    wallet_score = score_wallet(labels, holder_percent, sell_ratio, tx_per_minute)

    return {
        "labels": labels,
        "wallet_score": wallet_score,
        "first_entry_at": first_entry_at,
        "seconds_from_launch": seconds_from_launch,
        "total_token_in": token_in,
        "total_token_out": token_out,
        "net_token_amount": net_token_amount,
        "transaction_count": len(transactions),
        "details": {
            "sell_ratio": round(sell_ratio, 4),
            "first_exit_at": first_exit_at,
            "dex_like_tx_count": dex_like_tx_count,
            "exit_count": len(exit_times),
            "active_seconds": active_seconds,
            "tx_per_minute": round(tx_per_minute, 4),
            "wallet_age_seconds": wallet_age_seconds,
            "oldest_seen_transaction_at": oldest_seen_transaction_at,
            "history_may_be_truncated": history_may_be_truncated,
            "funding_source_holder_count": funding_source_holder_count,
            "early_buyer": {
                "status": early_buyer_status,
                "profit_state": profit_state,
                "native_spent": round(native_spent, 9),
                "native_received": round(native_received, 9),
                "realized_cost_native": round(realized_cost_native, 9) if realized_cost_native is not None else None,
                "realized_pnl_native": round(realized_pnl_native, 9) if realized_pnl_native is not None else None,
                "realized_roi": round(realized_roi, 4) if realized_roi is not None else None,
                "pnl_note": (
                    "Realized SOL PnL from observed swaps only; unrealized value is not estimated"
                    if realized_pnl_native is not None
                    else "PnL unavailable because observed swaps did not expose enough native SOL flow"
                ),
            },
            "label_reasons": label_reasons,
            "label_thresholds": {
                "whale_holder_percent": WHALE_HOLDER_PERCENT,
                "sniper_seconds": SNIPER_SECONDS,
                "fresh_wallet_seconds": FRESH_WALLET_SECONDS,
                "early_buy_seconds": EARLY_BUY_SECONDS,
                "dumper_sell_ratio": DUMPER_SELL_RATIO,
                "bot_dex_tx_count": BOT_DEX_TX_COUNT,
                "shared_funder_danger_count": SHARED_FUNDER_DANGER_COUNT,
            },
        },
    }


def classify_early_buyer_status(token_in: float, token_out: float, net_token_amount: float) -> str:
    if token_in <= 0:
        return "NO_BUY_DETECTED"

    if net_token_amount <= 0 and token_out > 0:
        return "EXITED"

    sell_ratio = token_out / token_in if token_in > 0 else 0

    if sell_ratio >= 0.65:
        return "MOSTLY_EXITED"

    if token_out > 0:
        return "PARTIAL_EXIT"

    return "HOLDING"


def classify_profit_state(
    realized_pnl_native: float | None,
    native_received: float,
    native_spent: float,
) -> str:
    if realized_pnl_native is None:
        if native_spent > 0 and native_received == 0:
            return "UNREALIZED"
        return "UNKNOWN"

    if realized_pnl_native > 0:
        return "PROFIT"

    if realized_pnl_native < 0:
        return "LOSS"

    return "BREAKEVEN"


def score_wallet(
    labels: list[str],
    holder_percent: float,
    sell_ratio: float,
    tx_per_minute: float = 0.0,
) -> int:
    score = 0

    if "SMART_WALLET" in labels:
        score += 3

    if "WHALE" in labels:
        score += 1

    if "SNIPER" in labels:
        score -= 2

    if "FRESH_WALLET" in labels:
        score -= 4

    if "DUMPER" in labels:
        score -= 3

    if "DEV_RELATED" in labels:
        score -= 4

    if "BOT" in labels:
        score -= 2

    if holder_percent >= 20:
        score -= 3
    elif holder_percent >= 10:
        score -= 1

    if sell_ratio >= 0.8:
        score -= 2

    if tx_per_minute >= BOT_TX_PER_MINUTE:
        score -= 1

    return max(-10, min(10, score))


async def get_wallet_intelligence_inputs(
    pool: asyncpg.Pool,
    run_id: int | None = None,
    holder_limit: int = EARLY_BUYER_LIMIT,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        th.run_id,
        th.token_id,
        th.pair_id,
        th.owner_address AS wallet_address,
        th.rank,
        th.percent AS holder_percent,
        t.symbol,
        t.address AS token_address,
        p.pair_created_at,
        fe.funder_address AS funding_source,
        COUNT(*) FILTER (
            WHERE fe.funder_address IS NOT NULL
        ) OVER (
            PARTITION BY th.run_id, th.token_id, fe.funder_address
        ) AS funding_source_holder_count
    FROM token_holders th
    JOIN tokens t
        ON t.id = th.token_id
    LEFT JOIN token_pairs p
        ON p.id = th.pair_id
    LEFT JOIN wallet_funding_edges fe
        ON fe.run_id = th.run_id
       AND fe.token_id = th.token_id
       AND fe.holder_address = th.owner_address
       AND fe.source = 'helius'
    WHERE th.rank <= $1
      AND th.run_id = COALESCE($2, (SELECT MAX(id) FROM ingestion_runs))
    ORDER BY th.run_id DESC, th.token_id, th.rank;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, holder_limit, run_id)

    return [dict(row) for row in rows]


async def save_wallet_intelligence_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    sql = """
    INSERT INTO wallet_intelligence_results (
        run_id,
        token_id,
        pair_id,
        wallet_address,
        rank,
        holder_percent,
        labels,
        wallet_score,
        first_entry_at,
        seconds_from_launch,
        total_token_in,
        total_token_out,
        net_token_amount,
        transaction_count,
        funding_source,
        details
    )
    VALUES (
        $1, $2, $3, $4,
        $5, $6,
        $7::jsonb, $8,
        $9, $10,
        $11, $12, $13,
        $14, $15,
        $16::jsonb
    )
    ON CONFLICT (run_id, token_id, wallet_address)
    DO UPDATE SET
        pair_id = EXCLUDED.pair_id,
        rank = EXCLUDED.rank,
        holder_percent = EXCLUDED.holder_percent,
        labels = EXCLUDED.labels,
        wallet_score = EXCLUDED.wallet_score,
        first_entry_at = EXCLUDED.first_entry_at,
        seconds_from_launch = EXCLUDED.seconds_from_launch,
        total_token_in = EXCLUDED.total_token_in,
        total_token_out = EXCLUDED.total_token_out,
        net_token_amount = EXCLUDED.net_token_amount,
        transaction_count = EXCLUDED.transaction_count,
        funding_source = EXCLUDED.funding_source,
        details = EXCLUDED.details,
        created_at = NOW()
    RETURNING *;
    """

    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        **result["details"],
    }

    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            sql,
            row["run_id"],
            row["token_id"],
            row["pair_id"],
            row["wallet_address"],
            row["rank"],
            row["holder_percent"],
            json.dumps(result["labels"]),
            result["wallet_score"],
            result["first_entry_at"],
            result["seconds_from_launch"],
            result["total_token_in"],
            result["total_token_out"],
            result["net_token_amount"],
            result["transaction_count"],
            row.get("funding_source"),
            json.dumps(details, default=str),
        )

    return dict(saved)


async def update_watchlist_intelligence_summary(pool: asyncpg.Pool) -> None:
    sql = """
    WITH summaries AS (
        SELECT
            run_id,
            token_id,
            jsonb_build_object(
                'smart_wallets', COUNT(*) FILTER (WHERE labels ? 'SMART_WALLET'),
                'fresh_wallets', COUNT(*) FILTER (WHERE labels ? 'FRESH_WALLET'),
                'snipers', COUNT(*) FILTER (WHERE labels ? 'SNIPER'),
                'whales', COUNT(*) FILTER (WHERE labels ? 'WHALE'),
                'dumpers', COUNT(*) FILTER (WHERE labels ? 'DUMPER'),
                'dev_related', COUNT(*) FILTER (WHERE labels ? 'DEV_RELATED'),
                'bots', COUNT(*) FILTER (WHERE labels ? 'BOT'),
                'unknown', COUNT(*) FILTER (WHERE labels ? 'UNKNOWN'),
                'avg_wallet_score', ROUND(AVG(wallet_score), 2),
                'early_buyers', COUNT(*) FILTER (WHERE first_entry_at IS NOT NULL),
                'early_holding', COUNT(*) FILTER (
                    WHERE details->'early_buyer'->>'status' = 'HOLDING'
                ),
                'early_partial_exit', COUNT(*) FILTER (
                    WHERE details->'early_buyer'->>'status' = 'PARTIAL_EXIT'
                ),
                'early_exited', COUNT(*) FILTER (
                    WHERE details->'early_buyer'->>'status' IN ('EXITED', 'MOSTLY_EXITED')
                ),
                'early_profitable', COUNT(*) FILTER (
                    WHERE details->'early_buyer'->>'profit_state' = 'PROFIT'
                ),
                'early_loss', COUNT(*) FILTER (
                    WHERE details->'early_buyer'->>'profit_state' = 'LOSS'
                ),
                'early_unrealized', COUNT(*) FILTER (
                    WHERE details->'early_buyer'->>'profit_state' = 'UNREALIZED'
                )
            ) AS intelligence_summary
        FROM wallet_intelligence_results
        GROUP BY run_id, token_id
    )
    UPDATE watchlist_decisions wd
    SET intelligence_summary = summaries.intelligence_summary
    FROM summaries
    WHERE summaries.run_id = wd.run_id
      AND summaries.token_id = wd.token_id;
    """

    async with pool.acquire() as conn:
        await conn.execute(sql)


async def run_wallet_intelligence_service(
    pool: asyncpg.Pool,
    run_id: int | None = None,
    helius_client: HeliusClient | None = None,
) -> list[dict[str, Any]]:
    rows = await get_wallet_intelligence_inputs(pool, run_id=run_id)
    results = []

    owns_client = helius_client is None
    client = helius_client or HeliusClient()

    try:
        for row in rows:
            try:
                transactions = await client.get_address_transactions(
                    row["wallet_address"],
                    limit=100,
                )
            except (httpx.HTTPError, RuntimeError, json.JSONDecodeError):
                transactions = []

            result = analyze_wallet_transactions(
                wallet_address=row["wallet_address"],
                token_address=row["token_address"],
                pair_created_at=row.get("pair_created_at"),
                rank=row.get("rank"),
                holder_percent=safe_float(row.get("holder_percent")),
                funding_source=row.get("funding_source"),
                funding_source_holder_count=int(row.get("funding_source_holder_count") or 0),
                transactions=transactions,
            )

            saved = await save_wallet_intelligence_result(pool, row, result)
            saved["symbol"] = row.get("symbol")
            saved["token_address"] = row.get("token_address")
            results.append(saved)
    finally:
        if owns_client:
            await client.aclose()

    await update_watchlist_intelligence_summary(pool)

    return results

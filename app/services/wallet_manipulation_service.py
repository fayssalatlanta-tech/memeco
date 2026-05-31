import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import httpx

from app.helius import HeliusClient
from app.http_utils import UpstreamUnavailable

TOP_HOLDER_LIMIT = 3
TRANSACTION_LIMIT = 30
SHARED_FUNDER_WARNING = 2
SHARED_FUNDER_DANGER = 3
TOKEN_DISTRIBUTOR_WARNING = 2
TOKEN_DISTRIBUTOR_DANGER = 3
LINKED_WALLET_WARNING = 2
LINKED_WALLET_DANGER = 4
COORDINATED_DUMP_WARNING = 2
COORDINATED_DUMP_DANGER = 3
COORDINATED_DUMP_WINDOW = timedelta(minutes=10)

# Helius parallelism. Same reasoning as cluster_analysis_service — 4
# in-flight × ~6.6 req/sec keeps us well under the 10/sec free-tier
# ceiling. Override via HELIUS_PARALLELISM env if you have a paid plan.
HELIUS_PARALLELISM = int(os.getenv("HELIUS_PARALLELISM", "4"))


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
    return transfer.get("mint") or transfer.get("mintAddress") or transfer.get("tokenMint")


def token_transfer_amount(transfer: dict[str, Any]) -> float:
    raw_amount = transfer.get("rawTokenAmount")

    if isinstance(raw_amount, dict):
        return safe_float(raw_amount.get("tokenAmount"))

    return safe_float(transfer.get("tokenAmount") or transfer.get("amount"))


def normalize_holders(value) -> list[dict[str, Any]]:
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


def edge_key(edge: dict[str, Any]) -> tuple:
    return (
        edge.get("relation_type"),
        edge.get("from_wallet"),
        edge.get("to_wallet"),
        edge.get("signature"),
    )


def extract_relationship_edges(
    holder_address: str,
    holder_set: set[str],
    token_address: str,
    transactions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    edges = []
    dump_events = []

    for transaction in transactions:
        signature = transaction.get("signature")
        timestamp = unix_to_datetime(transaction.get("timestamp"))

        native_transfers = transaction.get("nativeTransfers") or []
        if isinstance(native_transfers, list):
            for transfer in native_transfers:
                if not isinstance(transfer, dict):
                    continue

                from_wallet = transfer.get("fromUserAccount")
                to_wallet = transfer.get("toUserAccount")

                if from_wallet not in holder_set and to_wallet not in holder_set:
                    continue

                if from_wallet == to_wallet:
                    continue

                relation_type = "SOL_LINK"

                if from_wallet not in holder_set and to_wallet in holder_set:
                    relation_type = "SOL_FUNDER"
                elif from_wallet in holder_set and to_wallet not in holder_set:
                    relation_type = "SOL_OUT"

                edges.append(
                    {
                        "from_wallet": from_wallet,
                        "to_wallet": to_wallet,
                        "relation_type": relation_type,
                        "amount": safe_float(transfer.get("amount")),
                        "signature": signature,
                        "timestamp": timestamp,
                        "raw_json": transaction,
                    }
                )

        token_transfers = transaction.get("tokenTransfers") or []
        if not isinstance(token_transfers, list):
            continue

        for transfer in token_transfers:
            if not isinstance(transfer, dict):
                continue

            if token_transfer_mint(transfer) != token_address:
                continue

            from_wallet = transfer.get("fromUserAccount")
            to_wallet = transfer.get("toUserAccount")
            amount = token_transfer_amount(transfer)

            if from_wallet == to_wallet:
                continue

            if from_wallet == holder_address:
                dump_events.append(
                    {
                        "wallet": holder_address,
                        "timestamp": timestamp,
                        "signature": signature,
                        "amount": amount,
                    }
                )

            if from_wallet not in holder_set and to_wallet not in holder_set:
                continue

            relation_type = "TOKEN_LINK"

            if from_wallet not in holder_set and to_wallet in holder_set:
                relation_type = "TOKEN_DISTRIBUTION"
            elif from_wallet in holder_set and to_wallet not in holder_set:
                relation_type = "TOKEN_OUT"

            edges.append(
                {
                    "from_wallet": from_wallet,
                    "to_wallet": to_wallet,
                    "relation_type": relation_type,
                    "amount": amount,
                    "signature": signature,
                    "timestamp": timestamp,
                    "raw_json": transaction,
                }
            )

    deduped_edges = list({edge_key(edge): edge for edge in edges}.values())
    return deduped_edges, dump_events


def largest_group_size(groups: dict[str, set[str]]) -> tuple[int, str | None]:
    if not groups:
        return 0, None

    owner, members = max(groups.items(), key=lambda item: len(item[1]))
    return len(members), owner


def count_linked_wallets(edges: list[dict[str, Any]], holder_set: set[str]) -> int:
    linked = set()

    for edge in edges:
        from_wallet = edge.get("from_wallet")
        to_wallet = edge.get("to_wallet")

        if from_wallet in holder_set and to_wallet in holder_set:
            linked.add(from_wallet)
            linked.add(to_wallet)

    return len(linked)


def count_coordinated_dumps(dump_events: list[dict[str, Any]]) -> int:
    dated_events = [
        event
        for event in dump_events
        if event.get("timestamp") is not None
    ]

    if not dated_events:
        return 0

    dated_events.sort(key=lambda event: event["timestamp"])
    largest = 0

    for index, event in enumerate(dated_events):
        window_end = event["timestamp"] + COORDINATED_DUMP_WINDOW
        wallets = {
            candidate["wallet"]
            for candidate in dated_events[index:]
            if candidate["timestamp"] <= window_end
        }
        largest = max(largest, len(wallets))

    return largest


def classify_manipulation(
    holder_count: int,
    edges: list[dict[str, Any]],
    existing_funding_edges: list[dict[str, Any]],
    dump_events: list[dict[str, Any]],
    holder_set: set[str],
) -> dict[str, Any]:
    warnings = []
    reasons = []

    shared_funders = defaultdict(set)
    for edge in existing_funding_edges:
        funder = edge.get("funder_address")
        holder = edge.get("holder_address")

        if funder and holder:
            shared_funders[funder].add(holder)

    for edge in edges:
        if edge.get("relation_type") != "SOL_FUNDER":
            continue

        funder = edge.get("from_wallet")
        holder = edge.get("to_wallet")

        if funder and holder:
            shared_funders[funder].add(holder)

    token_distributors = defaultdict(set)
    for edge in edges:
        if edge.get("relation_type") != "TOKEN_DISTRIBUTION":
            continue

        distributor = edge.get("from_wallet")
        receiver = edge.get("to_wallet")

        if distributor and receiver:
            token_distributors[distributor].add(receiver)

    shared_funder_cluster_size, shared_funder = largest_group_size(shared_funders)
    token_distributor_count, token_distributor = largest_group_size(token_distributors)
    linked_wallet_count = count_linked_wallets(edges, holder_set)
    coordinated_dump_count = count_coordinated_dumps(dump_events)

    score = 0

    if shared_funder_cluster_size >= SHARED_FUNDER_DANGER:
        score += 4
        warnings.append("SHARED_FUNDER_CLUSTER")
        reasons.append(f"{shared_funder_cluster_size} top holders share one SOL funding source")
    elif shared_funder_cluster_size >= SHARED_FUNDER_WARNING:
        score += 2
        warnings.append("SHARED_FUNDER_CLUSTER_SMALL")
        reasons.append(f"{shared_funder_cluster_size} top holders share one SOL funding source")

    if token_distributor_count >= TOKEN_DISTRIBUTOR_DANGER:
        score += 4
        warnings.append("TOKEN_SPLITTER")
        reasons.append(f"One wallet distributed token to {token_distributor_count} top holders")
    elif token_distributor_count >= TOKEN_DISTRIBUTOR_WARNING:
        score += 2
        warnings.append("TOKEN_SPLITTER_SMALL")
        reasons.append(f"One wallet distributed token to {token_distributor_count} top holders")

    if linked_wallet_count >= LINKED_WALLET_DANGER:
        score += 3
        warnings.append("LINKED_TOP_HOLDERS")
        reasons.append(f"{linked_wallet_count} top holders have direct wallet links")
    elif linked_wallet_count >= LINKED_WALLET_WARNING:
        score += 1
        warnings.append("LINKED_TOP_HOLDERS_SMALL")
        reasons.append(f"{linked_wallet_count} top holders have direct wallet links")

    if coordinated_dump_count >= COORDINATED_DUMP_DANGER:
        score += 4
        warnings.append("COORDINATED_DUMP")
        reasons.append(f"{coordinated_dump_count} linked/top wallets sold within 10 minutes")
    elif coordinated_dump_count >= COORDINATED_DUMP_WARNING:
        score += 2
        warnings.append("COORDINATED_DUMP_SMALL")
        reasons.append(f"{coordinated_dump_count} linked/top wallets sold within 10 minutes")

    if holder_count == 0:
        status = "MANIPULATION_UNKNOWN"
        passed = False
        reason = "No holder data available"
        warnings.append("NO_HOLDER_DATA")
    elif score >= 7:
        status = "MANIPULATION_DANGER"
        passed = False
        reason = "; ".join(reasons)
    elif score >= 3:
        status = "MANIPULATION_WARNING"
        passed = True
        reason = "; ".join(reasons)
    else:
        status = "MANIPULATION_PASS"
        passed = True
        reason = "No strong wallet manipulation pattern detected"

    return {
        "manipulation_status": status,
        "manipulation_pass": passed,
        "manipulation_reason": reason,
        "manipulation_score": min(10, score),
        "shared_funder_cluster_size": shared_funder_cluster_size,
        "largest_shared_funder": shared_funder,
        "token_distributor_count": token_distributor_count,
        "largest_token_distributor": token_distributor,
        "linked_wallet_count": linked_wallet_count,
        "coordinated_dump_count": coordinated_dump_count,
        "warnings": warnings,
        "details": {
            "holder_count": holder_count,
            "edge_count": len(edges),
            "dump_event_count": len(dump_events),
            "reasons": reasons,
        },
    }


async def get_manipulation_inputs(
    pool: asyncpg.Pool,
    run_id: int | None = None,
    holder_limit: int = TOP_HOLDER_LIMIT,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        wa.run_id,
        wa.token_id,
        wa.pair_id,
        wa.created_at,
        t.symbol,
        t.address AS token_address,
        holders.holders,
        funding_edges.funding_edges
    FROM wallet_analysis_results wa
    JOIN tokens t
        ON t.id = wa.token_id
    LEFT JOIN LATERAL (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'owner_address', ranked.owner_address,
                    'rank', ranked.rank,
                    'percent', ranked.percent
                )
                ORDER BY ranked.rank
            ),
            '[]'::jsonb
        ) AS holders
        FROM (
            SELECT th.owner_address, th.rank, th.percent
            FROM token_holders th
            WHERE th.run_id = wa.run_id
              AND th.token_id = wa.token_id
              AND th.rank <= $2
            ORDER BY th.rank
        ) ranked
    ) holders ON TRUE
    LEFT JOIN LATERAL (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'holder_address', fe.holder_address,
                    'funder_address', fe.funder_address
                )
            ),
            '[]'::jsonb
        ) AS funding_edges
        FROM wallet_funding_edges fe
        WHERE fe.run_id = wa.run_id
          AND fe.token_id = wa.token_id
    ) funding_edges ON TRUE
    WHERE wa.run_id = COALESCE($1, (SELECT MAX(id) FROM ingestion_runs))
    ORDER BY wa.created_at DESC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, run_id, holder_limit)

    return [dict(row) for row in rows]


async def save_relationship_edge(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    edge: dict[str, Any],
) -> None:
    """Insert a single relationship edge.

    Kept for back-compat with anything that imports it directly. The hot
    path in ``run_wallet_manipulation_service`` now uses
    :func:`save_token_manipulation_state` to batch all per-token writes.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            _INSERT_RELATIONSHIP_EDGE_SQL,
            *_relationship_edge_params(row, edge),
        )


_INSERT_RELATIONSHIP_EDGE_SQL = """
INSERT INTO wallet_relationship_edges (
    run_id,
    token_id,
    pair_id,
    from_wallet,
    to_wallet,
    relation_type,
    amount,
    signature,
    timestamp,
    source,
    raw_json
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'helius', $10::jsonb)
ON CONFLICT (
    run_id,
    token_id,
    relation_type,
    from_wallet,
    to_wallet,
    signature
)
DO UPDATE SET
    pair_id = EXCLUDED.pair_id,
    amount = EXCLUDED.amount,
    timestamp = EXCLUDED.timestamp,
    raw_json = EXCLUDED.raw_json,
    created_at = NOW();
"""


def _relationship_edge_params(
    row: dict[str, Any],
    edge: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        row["run_id"],
        row["token_id"],
        row["pair_id"],
        edge.get("from_wallet"),
        edge.get("to_wallet"),
        edge["relation_type"],
        edge.get("amount"),
        edge.get("signature"),
        edge.get("timestamp"),
        json.dumps(edge.get("raw_json") or {}, default=str),
    )


_INSERT_MANIPULATION_RESULT_SQL = """
INSERT INTO wallet_manipulation_results (
    run_id,
    token_id,
    pair_id,
    manipulation_status,
    manipulation_pass,
    manipulation_reason,
    manipulation_score,
    shared_funder_cluster_size,
    token_distributor_count,
    linked_wallet_count,
    coordinated_dump_count,
    warnings,
    details
)
VALUES (
    $1, $2, $3,
    $4, $5, $6, $7,
    $8, $9, $10, $11,
    $12::jsonb, $13::jsonb
)
ON CONFLICT (run_id, token_id)
DO UPDATE SET
    pair_id = EXCLUDED.pair_id,
    manipulation_status = EXCLUDED.manipulation_status,
    manipulation_pass = EXCLUDED.manipulation_pass,
    manipulation_reason = EXCLUDED.manipulation_reason,
    manipulation_score = EXCLUDED.manipulation_score,
    shared_funder_cluster_size = EXCLUDED.shared_funder_cluster_size,
    token_distributor_count = EXCLUDED.token_distributor_count,
    linked_wallet_count = EXCLUDED.linked_wallet_count,
    coordinated_dump_count = EXCLUDED.coordinated_dump_count,
    warnings = EXCLUDED.warnings,
    details = EXCLUDED.details,
    created_at = NOW()
RETURNING *;
"""


def _manipulation_result_params(
    row: dict[str, Any],
    result: dict[str, Any],
) -> tuple[Any, ...]:
    details = {
        "symbol": row.get("symbol"),
        "token_address": row.get("token_address"),
        "source": "helius",
        **result["details"],
        "largest_shared_funder": result.get("largest_shared_funder"),
        "largest_token_distributor": result.get("largest_token_distributor"),
    }
    return (
        row["run_id"],
        row["token_id"],
        row["pair_id"],
        result["manipulation_status"],
        result["manipulation_pass"],
        result["manipulation_reason"],
        result["manipulation_score"],
        result["shared_funder_cluster_size"],
        result["token_distributor_count"],
        result["linked_wallet_count"],
        result["coordinated_dump_count"],
        json.dumps(result["warnings"]),
        json.dumps(details, default=str),
    )


async def save_manipulation_result(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Upsert the manipulation result row for a single token. Back-compat entry."""
    async with pool.acquire() as conn:
        saved = await conn.fetchrow(
            _INSERT_MANIPULATION_RESULT_SQL,
            *_manipulation_result_params(row, result),
        )

    return dict(saved)


async def save_token_manipulation_state(
    pool: asyncpg.Pool,
    row: dict[str, Any],
    edges: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Write all per-token manipulation persistence in a single transaction:

      * upsert each relationship edge via ``executemany``
      * upsert the manipulation result row

    One ``pool.acquire()`` per token instead of one per edge + one for the
    result. With 3 holders × 30 transactions this typically collapses
    dozens of round-trips into one.
    """
    edge_params = [_relationship_edge_params(row, edge) for edge in edges]

    async with pool.acquire() as conn:
        async with conn.transaction():
            if edge_params:
                await conn.executemany(_INSERT_RELATIONSHIP_EDGE_SQL, edge_params)

            saved = await conn.fetchrow(
                _INSERT_MANIPULATION_RESULT_SQL,
                *_manipulation_result_params(row, result),
            )

    return dict(saved)


async def _fetch_holder_relationship_data(
    client: HeliusClient,
    holder_address: str,
    holder_set: set[str],
    token_address: str,
    semaphore: asyncio.Semaphore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Fetch one holder's recent transactions from Helius and reduce them to
    ``(edges, dump_events)``. Always returns two lists, never raises:
    transient errors collapse to empty results so the per-token classifier
    still has data from the other holders.

    The semaphore caps concurrent in-flight tasks. The HeliusClient's own
    rate limiter then serializes the actual outbound requests.
    """
    async with semaphore:
        try:
            transactions = await client.get_address_transactions(
                holder_address,
                limit=TRANSACTION_LIMIT,
            )
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError):
            transactions = []

    return extract_relationship_edges(
        holder_address=holder_address,
        holder_set=holder_set,
        token_address=token_address,
        transactions=transactions,
    )


async def _process_token(
    pool: asyncpg.Pool,
    client: HeliusClient,
    row: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    holders = normalize_holders(row.get("holders"))
    funding_edges = normalize_holders(row.get("funding_edges"))
    holder_addresses = [
        holder["owner_address"]
        for holder in holders
        if holder.get("owner_address")
    ]
    holder_set = set(holder_addresses)

    if not client.is_configured:
        result = {
            "manipulation_status": "MANIPULATION_UNKNOWN",
            "manipulation_pass": False,
            "manipulation_reason": "HELIUS_API_KEY is missing",
            "manipulation_score": 0,
            "shared_funder_cluster_size": 0,
            "largest_shared_funder": None,
            "token_distributor_count": 0,
            "largest_token_distributor": None,
            "linked_wallet_count": 0,
            "coordinated_dump_count": 0,
            "warnings": ["HELIUS_NOT_CONFIGURED"],
            "details": {"holder_count": len(holders), "edge_count": 0, "dump_event_count": 0},
        }
        saved = await save_token_manipulation_state(pool, row, edges=[], result=result)
        saved["symbol"] = row.get("symbol")
        saved["token_address"] = row.get("token_address")
        return saved

    if holder_addresses:
        per_holder = await asyncio.gather(
            *(
                _fetch_holder_relationship_data(
                    client,
                    holder_address,
                    holder_set,
                    row["token_address"],
                    semaphore,
                )
                for holder_address in holder_addresses
            )
        )
    else:
        per_holder = []

    all_edges: list[dict[str, Any]] = []
    all_dump_events: list[dict[str, Any]] = []
    for edges, dump_events in per_holder:
        all_edges.extend(edges)
        all_dump_events.extend(dump_events)

    deduped_edges = list({edge_key(edge): edge for edge in all_edges}.values())

    result = classify_manipulation(
        holder_count=len(holders),
        edges=deduped_edges,
        existing_funding_edges=funding_edges,
        dump_events=all_dump_events,
        holder_set=holder_set,
    )
    saved = await save_token_manipulation_state(
        pool,
        row,
        edges=deduped_edges,
        result=result,
    )
    saved["symbol"] = row.get("symbol")
    saved["token_address"] = row.get("token_address")
    return saved


async def run_wallet_manipulation_service(
    pool: asyncpg.Pool,
    run_id: int | None = None,
    helius_client: HeliusClient | None = None,
) -> list[dict[str, Any]]:
    rows = await get_manipulation_inputs(pool, run_id=run_id)

    semaphore = asyncio.Semaphore(HELIUS_PARALLELISM)
    results: list[dict[str, Any]] = []

    async def _safely_process(client: HeliusClient, row: dict[str, Any]) -> dict[str, Any]:
        # An UpstreamUnavailable from one token (typically Helius 429
        # storms) used to abort the whole pipeline. Now we record the
        # failure on the row and continue so other tokens still progress.
        try:
            return await _process_token(pool, client, row, semaphore)
        except UpstreamUnavailable as exc:
            print(f"[manipulation] Helius unavailable for {row.get('symbol') or row.get('token_address')}: {exc}")
            saved = await save_token_manipulation_state(
                pool, row, edges=[], result={
                    "manipulation_status": "MANIPULATION_UNKNOWN",
                    "manipulation_pass": False,
                    "manipulation_score": 0,
                    "manipulation_reason": "Upstream Helius unavailable — analysis skipped",
                    "shared_funder_cluster_size": 0,
                    "token_distributor_count": 0,
                    "linked_wallet_count": 0,
                    "coordinated_dump_count": 0,
                    "warnings": ["upstream_unavailable"],
                    "details": {},
                    "largest_shared_funder": None,
                    "largest_token_distributor": None,
                },
            )
            saved["symbol"] = row.get("symbol")
            saved["token_address"] = row.get("token_address")
            return saved

    if helius_client is not None:
        for row in rows:
            results.append(await _safely_process(helius_client, row))
        return results

    async with HeliusClient() as client:
        for row in rows:
            results.append(await _safely_process(client, row))

    return results

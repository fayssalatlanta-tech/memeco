import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

from db import create_pool
from dexscreener import (
    DexScreenerClient,
    dedupe_latest_candidates,
    sort_discovered_pairs_by_recency,
)
from tokens import upsert_token
from pairs import upsert_token_pair
from prices import upsert_token_price
from system import start_ingestion_run, finish_ingestion_run, save_raw_snapshot
from risk import add_basic_risk_checks


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

SOURCE = "dexscreener_latest_profiles"
MANUAL_SOURCE = "dexscreener_manual_token"
DEFAULT_MAX_LATEST_TOKENS = 10
MAX_LATEST_TOKENS_HARD_CAP = 30
DEFAULT_MAX_DISCOVERY_CANDIDATES = 40
MAX_DISCOVERY_CANDIDATES_HARD_CAP = 120


def to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def to_int(value, default=0):
    if value is None:
        return default
    return int(value)


def ms_to_datetime(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


async def ingest_token(
    pool,
    client: DexScreenerClient,
    run_id: int,
    token_address: str,
    profile: dict | None = None,
    selected_pair: dict | None = None,
) -> dict:
    profile_endpoint = (profile or {}).get("_source_endpoint", "/token-profiles/latest/v1")
    await save_raw_snapshot(
        pool=pool,
        run_id=run_id,
        source="dexscreener",
        endpoint=profile_endpoint,
        chain="solana",
        token_address=token_address,
        pair_address=None,
        raw_json=profile or {"chainId": "solana", "tokenAddress": token_address},
    )

    token_orders = await client.get_token_orders("solana", token_address)

    await save_raw_snapshot(
        pool=pool,
        run_id=run_id,
        source="dexscreener",
        endpoint="/orders/v1/solana/{tokenAddress}",
        chain="solana",
        token_address=token_address,
        pair_address=None,
        raw_json=token_orders,
    )

    best_pair = selected_pair or await client.get_preferred_token_pair(
        "solana",
        token_address,
    )

    if not best_pair:
        raise ValueError(
            f"Skipped token {token_address}: no completed non-bonding DEX pair found"
        )

    pair_address = best_pair.get("pairAddress")

    if not pair_address:
        raise ValueError(f"Skipped token {token_address}: missing pairAddress")

    base_token = best_pair.get("baseToken", {})
    quote_token = best_pair.get("quoteToken", {})
    liquidity = best_pair.get("liquidity", {})
    volume = best_pair.get("volume", {})
    txns = best_pair.get("txns", {})

    profile_info = best_pair.get("info") or {}
    profile_snapshot = {
        "chainId": "solana",
        "tokenAddress": token_address,
        "url": best_pair.get("url"),
        "icon": profile_info.get("imageUrl") or (profile or {}).get("icon"),
        "description": profile_info.get("description"),
        "links": profile_info.get("websites") or profile_info.get("socials") or [],
    }

    await save_raw_snapshot(
        pool=pool,
        run_id=run_id,
        source="dexscreener",
        endpoint="/token-profiles/latest/v1",
        chain="solana",
        token_address=token_address,
        pair_address=None,
        raw_json=profile_snapshot,
    )

    await save_raw_snapshot(
        pool=pool,
        run_id=run_id,
        source="dexscreener",
        endpoint="/token-pairs/v1/solana/{tokenAddress}",
        chain="solana",
        token_address=token_address,
        pair_address=pair_address,
        raw_json=best_pair,
    )

    price_usd = to_decimal(best_pair.get("priceUsd"))
    price_native = to_decimal(best_pair.get("priceNative"))
    liquidity_usd = to_decimal(liquidity.get("usd"))
    volume_5m_usd = to_decimal(volume.get("m5"))
    volume_1h_usd = to_decimal(volume.get("h1"))
    volume_6h_usd = to_decimal(volume.get("h6"))
    volume_24h_usd = to_decimal(volume.get("h24"))

    token_data = {
        "chain": "solana",
        "address": token_address,
        "symbol": base_token.get("symbol"),
        "name": base_token.get("name"),
        "decimals": None,
        "source": "dexscreener",
        "creator_address": None,
    }

    saved_token = await upsert_token(pool, token_data)

    pair_data = {
        "token_id": saved_token["id"],
        "chain": "solana",
        "pair_address": pair_address,
        "base_token_address": base_token.get("address"),
        "quote_token_address": quote_token.get("address"),
        "quote_token_symbol": quote_token.get("symbol"),
        "dex_id": best_pair.get("dexId"),
        "url": best_pair.get("url"),
        "pair_created_at": ms_to_datetime(best_pair.get("pairCreatedAt")),
        "is_primary": True,
    }

    saved_pair = await upsert_token_pair(pool, pair_data)

    snapshot_time = datetime.now(timezone.utc).replace(
        second=0,
        microsecond=0,
    )

    price_data = {
        "time": snapshot_time,
        "pair_id": saved_pair["id"],
        "price_usd": price_usd,
        "price_native": price_native,
        "liquidity_usd": liquidity_usd,
        "volume_5m_usd": volume_5m_usd,
        "volume_1h_usd": volume_1h_usd,
        "volume_6h_usd": volume_6h_usd,
        "volume_24h_usd": volume_24h_usd,
        "buys_5m": to_int(txns.get("m5", {}).get("buys")),
        "sells_5m": to_int(txns.get("m5", {}).get("sells")),
        "buys_1h": to_int(txns.get("h1", {}).get("buys")),
        "sells_1h": to_int(txns.get("h1", {}).get("sells")),
        "buys_24h": to_int(txns.get("h24", {}).get("buys")),
        "sells_24h": to_int(txns.get("h24", {}).get("sells")),
        "market_cap_usd": to_decimal(best_pair.get("marketCap")),
        "fdv_usd": to_decimal(best_pair.get("fdv")),
        "source": "dexscreener",
    }

    saved_price = await upsert_token_price(pool, price_data)

    await add_basic_risk_checks(
        pool=pool,
        token_id=saved_token["id"],
        pair_id=saved_pair["id"],
        run_id=run_id,
        token_address=token_address,
        pair_address=pair_address,
        price_usd=price_usd,
        liquidity_usd=liquidity_usd,
        volume_5m_usd=volume_5m_usd,
        volume_1h_usd=volume_1h_usd,
        market_cap_usd=price_data["market_cap_usd"],
        fdv_usd=price_data["fdv_usd"],
        pair_created_at=pair_data["pair_created_at"],
        txns=txns,
        price_change=best_pair.get("priceChange"),
    )

    return {
        "token": dict(saved_token),
        "pair": dict(saved_pair),
        "price": dict(saved_price),
    }


async def discover_latest_completed_dex_tokens(
    client: DexScreenerClient,
    max_candidates: int,
) -> list[tuple[dict, dict]]:
    profiles = await client.get_latest_profiles()
    community_takeovers = await client.get_latest_community_takeovers()
    latest_ads = await client.get_latest_ads()
    latest_boosts = await client.get_latest_boosted_tokens()
    top_boosts = await client.get_top_boosted_tokens()

    candidates = dedupe_latest_candidates(
        [
            ("profile", profiles),
            ("community_takeover", community_takeovers),
            ("ad", latest_ads),
            ("boost_latest", latest_boosts),
            ("boost_top", top_boosts),
        ],
        chain_id="solana",
    )

    logger.info(
        "DexScreener Solana candidates found: %s (profiles=%s community=%s ads=%s latest_boosts=%s top_boosts=%s)",
        len(candidates),
        len([item for item in profiles if item.get("chainId") == "solana"]),
        len([item for item in community_takeovers if item.get("chainId") == "solana"]),
        len([item for item in latest_ads if item.get("chainId") == "solana"]),
        len([item for item in latest_boosts if item.get("chainId") == "solana"]),
        len([item for item in top_boosts if item.get("chainId") == "solana"]),
    )

    discovered = []
    for candidate in candidates[:max_candidates]:
        token_address = candidate["tokenAddress"]
        pair = await client.get_preferred_token_pair("solana", token_address)
        if not pair:
            logger.info("Skipping bonding-only or pairless candidate: %s", token_address)
            continue
        discovered.append((candidate, pair))

    return sort_discovered_pairs_by_recency(discovered)


async def ingest_manual_token(token_address: str) -> dict:
    pool = await create_pool()
    client = DexScreenerClient()
    run_id = None

    try:
        run_id = await start_ingestion_run(pool, SOURCE)
        saved = await ingest_token(
            pool=pool,
            client=client,
            run_id=run_id,
            token_address=token_address,
        )

        await finish_ingestion_run(
            pool=pool,
            run_id=run_id,
            status="success",
            tokens_found=1,
            tokens_saved=1,
            pairs_saved=1,
            prices_saved=1,
            errors_count=0,
            error_message=None,
        )

        return {"run_id": run_id, **saved}

    except Exception as exc:
        if run_id is not None:
            await finish_ingestion_run(
                pool=pool,
                run_id=run_id,
                status="failed",
                tokens_found=1,
                tokens_saved=0,
                pairs_saved=0,
                prices_saved=0,
                errors_count=1,
                error_message=str(exc),
            )
        raise
    finally:
        await pool.close()


async def main():
    pool = await create_pool()
    client = DexScreenerClient()

    run_id = None
    tokens_found = 0
    tokens_saved = 0
    pairs_saved = 0
    prices_saved = 0
    errors_count = 0

    try:
        run_id = await start_ingestion_run(pool, SOURCE)
        logger.info("Started ingestion run: %s", run_id)

        max_latest_tokens = min(
            MAX_LATEST_TOKENS_HARD_CAP,
            max(1, int(os.getenv("DEXSCREENER_MAX_LATEST_TOKENS", str(DEFAULT_MAX_LATEST_TOKENS)))),
        )
        logger.info("DexScreener latest token processing limit: %s", max_latest_tokens)

        max_discovery_candidates = min(
            MAX_DISCOVERY_CANDIDATES_HARD_CAP,
            max(
                max_latest_tokens,
                int(os.getenv("DEXSCREENER_MAX_DISCOVERY_CANDIDATES", str(DEFAULT_MAX_DISCOVERY_CANDIDATES))),
            ),
        )
        logger.info("DexScreener discovery candidate limit: %s", max_discovery_candidates)

        discovered = await discover_latest_completed_dex_tokens(
            client=client,
            max_candidates=max_discovery_candidates,
        )
        tokens_found = len(discovered)
        logger.info("Completed non-bonding DEX candidates found: %s", tokens_found)

        for profile, selected_pair in discovered[:max_latest_tokens]:
            token_address = profile["tokenAddress"]

            try:
                logger.info(
                    "Processing token: %s pair=%s dex=%s pairCreatedAt=%s sources=%s",
                    token_address,
                    selected_pair.get("pairAddress"),
                    selected_pair.get("dexId"),
                    selected_pair.get("pairCreatedAt"),
                    profile.get("_sources") or [profile.get("_source")],
                )

                saved = await ingest_token(
                    pool=pool,
                    client=client,
                    run_id=run_id,
                    token_address=token_address,
                    profile=profile,
                    selected_pair=selected_pair,
                )
                saved_token = saved["token"]
                saved_pair = saved["pair"]
                saved_price = saved["price"]
                tokens_saved += 1
                pairs_saved += 1
                prices_saved += 1

                logger.info(
                    "Saved token=%s token_id=%s pair=%s price=%s liquidity=%s",
                    saved_token["symbol"],
                    saved_token["id"],
                    saved_pair["pair_address"],
                    saved_price["price_usd"],
                    saved_price["liquidity_usd"],
                )

            except Exception:
                errors_count += 1
                logger.exception("Error processing token %s", token_address)

        await finish_ingestion_run(
            pool=pool,
            run_id=run_id,
            status="success",
            tokens_found=tokens_found,
            tokens_saved=tokens_saved,
            pairs_saved=pairs_saved,
            prices_saved=prices_saved,
            errors_count=errors_count,
            error_message=None,
        )

        logger.info("Finished ingestion run: %s", run_id)
        logger.info("tokens_found=%s", tokens_found)
        logger.info("tokens_saved=%s", tokens_saved)
        logger.info("pairs_saved=%s", pairs_saved)
        logger.info("prices_saved=%s", prices_saved)
        logger.info("errors_count=%s", errors_count)

    except Exception as e:
        if run_id is not None:
            await finish_ingestion_run(
                pool=pool,
                run_id=run_id,
                status="failed",
                tokens_found=tokens_found,
                tokens_saved=tokens_saved,
                pairs_saved=pairs_saved,
                prices_saved=prices_saved,
                errors_count=errors_count + 1,
                error_message=str(e),
            )

        raise

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

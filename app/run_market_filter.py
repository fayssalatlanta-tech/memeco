import asyncio

from app.db import create_pool
from app.services.market_filter_service import (
    get_early_dex_candidates,
    save_market_filter_results,
)


async def main():
    pool = await create_pool()

    try:
        candidates = await get_early_dex_candidates(pool)
        saved_results = await save_market_filter_results(pool, candidates)

        print(f"Saved market filter results: {len(saved_results)}")

        print("\nMarket Filter Results")
        print("-" * 160)

        for c in candidates:
            print(
                f"symbol={c['symbol']} | "
                f"status={c['data_readiness_status']} | "
                f"age_min={c['pair_age_minutes']} | "
                f"early={c['early_category']} | "
                f"dump={c['dump_risk_category']} | "
                f"activity={c['activity_category']} | "
                f"warning_level={c['market_warning_level']} | "
                f"market_status={c['market_filter_status']} | "
                f"market_pass={c['market_filter_pass']} | "
                f"reason={c['market_filter_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from db import create_pool
from services.whale_discovery_service import run_whale_discovery_service


async def main():
    pool = await create_pool()

    try:
        results = await run_whale_discovery_service(pool)
        print(f"Saved elite wallets: {len(results)}")
        for result in results[:20]:
            print(
                f"wallet={result['wallet_address']} | "
                f"label={result['label']} | "
                f"score={result['reliability_score']} | "
                f"profit={result['total_profit_sol']} SOL | "
                f"win={result['win_rate_percent']}%"
            )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

from db import create_pool
from services.wallet_intelligence_service import run_wallet_intelligence_service


async def main():
    pool = await create_pool()

    try:
        results = await run_wallet_intelligence_service(pool)

        print(f"Saved wallet intelligence results: {len(results)}")

        print("\nWallet Intelligence Results")
        print("-" * 180)

        for r in results[:50]:
            print(
                f"symbol={r.get('symbol')} | "
                f"wallet={r['wallet_address']} | "
                f"rank={r['rank']} | "
                f"labels={r['labels']} | "
                f"score={r['wallet_score']} | "
                f"entry={r['first_entry_at']} | "
                f"txs={r['transaction_count']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

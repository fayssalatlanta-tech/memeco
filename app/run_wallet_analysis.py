import asyncio

from app.db import create_pool
from app.services.wallet_analysis_service import run_wallet_analysis_service


async def main():
    pool = await create_pool()

    try:
        results = await run_wallet_analysis_service(pool)

        print(f"Saved wallet analysis results: {len(results)}")

        print("\nWallet Analysis Results")
        print("-" * 140)

        for r in results:
            print(
                f"symbol={r.get('symbol')} | "
                f"token={r.get('token_address')} | "
                f"status={r['wallet_status']} | "
                f"pass={r['wallet_pass']} | "
                f"top1={r['top_holder_percent']} | "
                f"top10={r['top10_holders_percent']} | "
                f"top20={r['top20_holders_percent']} | "
                f"reason={r['wallet_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

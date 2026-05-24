import asyncio

from db import create_pool
from services.wallet_manipulation_service import run_wallet_manipulation_service


async def main():
    pool = await create_pool()

    try:
        results = await run_wallet_manipulation_service(pool)

        print(f"Saved wallet manipulation results: {len(results)}")
        print("\nWallet Manipulation Results")
        print("-" * 160)

        for r in results:
            print(
                f"symbol={r.get('symbol')} | "
                f"token={r.get('token_address')} | "
                f"status={r['manipulation_status']} | "
                f"score={r['manipulation_score']}/10 | "
                f"shared_funder={r['shared_funder_cluster_size']} | "
                f"token_split={r['token_distributor_count']} | "
                f"linked={r['linked_wallet_count']} | "
                f"dump={r['coordinated_dump_count']} | "
                f"reason={r['manipulation_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

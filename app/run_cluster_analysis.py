import asyncio

from app.db import create_pool
from app.services.cluster_analysis_service import run_cluster_analysis_service


async def main():
    pool = await create_pool()

    try:
        results = await run_cluster_analysis_service(pool)

        print(f"Saved cluster analysis results: {len(results)}")

        print("\nCluster Analysis Results")
        print("-" * 160)

        for r in results:
            print(
                f"symbol={r.get('symbol')} | "
                f"token={r.get('token_address')} | "
                f"status={r['cluster_status']} | "
                f"pass={r['cluster_pass']} | "
                f"holders={r['holder_count']} | "
                f"funded={r['funded_holder_count']} | "
                f"largest_cluster={r['largest_cluster_size']} | "
                f"reason={r['cluster_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

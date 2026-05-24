import asyncio

from app.db import create_pool
from app.services.dev_wallet_flow_service import run_dev_wallet_flow_service


async def main():
    pool = await create_pool()

    try:
        results = await run_dev_wallet_flow_service(pool)
        print(f"Saved dev wallet flow results: {len(results)}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

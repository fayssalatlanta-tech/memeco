import asyncio
import json

from db import create_pool
from services.whale_survival_service import run_whale_survival_service


async def main():
    pool = await create_pool()
    try:
        result = await run_whale_survival_service(pool)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

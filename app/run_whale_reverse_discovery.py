import asyncio
import json

from db import create_pool
from services.whale_reverse_discovery_service import run_reverse_profit_discovery


async def main():
    pool = await create_pool()
    try:
        result = await run_reverse_profit_discovery(pool)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

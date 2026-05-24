import asyncio
import json

from app.db import create_pool
from app.services.whale_price_refresh_service import refresh_whale_trade_prices


async def main():
    pool = await create_pool()
    try:
        result = await refresh_whale_trade_prices(pool)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

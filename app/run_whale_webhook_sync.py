import asyncio
import json

from app.db import create_pool
from app.services.whale_webhook_service import sync_whale_webhook


async def main():
    pool = await create_pool()
    try:
        result = await sync_whale_webhook(pool)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

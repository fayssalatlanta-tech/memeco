import asyncio
import json

from app.db import create_pool
from app.services.whale_consistency_auditor_service import run_whale_consistency_audit


async def main():
    pool = await create_pool()
    try:
        result = await run_whale_consistency_audit(pool)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

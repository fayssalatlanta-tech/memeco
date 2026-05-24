import asyncio
from decimal import InvalidOperation

from db import create_pool
from services.liquidity_filter_service import run_liquidity_filter_service


def fmt_number(value, digits: int = 2) -> str:
    if value is None:
        return "None"

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError, InvalidOperation):
        return str(value)


async def main():
    pool = await create_pool()

    try:
        results = await run_liquidity_filter_service(pool)

        print(f"Saved liquidity filter results: {len(results)}")

        print("\nLiquidity Filter Results")
        print("-" * 140)

        for r in results:
            print(
                f"symbol={r.get('symbol')} | "
                f"token={r.get('token_address')} | "
                f"status={r['liquidity_status']} | "
                f"pass={r['liquidity_pass']} | "
                f"liquidity={fmt_number(r['liquidity_usd'])} | "
                f"mcap={fmt_number(r['market_cap_usd'])} | "
                f"vol_1h={fmt_number(r['volume_1h_usd'])} | "
                f"mcap_liq={fmt_number(r['mcap_to_liquidity_ratio'], 2)} | "
                f"vol_liq={fmt_number(r['volume_to_liquidity_ratio'], 2)} | "
                f"reason={r['liquidity_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

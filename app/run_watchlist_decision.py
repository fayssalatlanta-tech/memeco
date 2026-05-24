import asyncio
from decimal import InvalidOperation

from app.db import create_pool
from app.services.watchlist_decision_service import run_watchlist_decision_service


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
        results = await run_watchlist_decision_service(pool)

        print(f"Saved watchlist decisions: {len(results)}")

        print("\nWatchlist Decisions")
        print("-" * 180)

        for r in results:
            print(
                f"symbol={r.get('symbol')} | "
                f"token={r.get('token_address')} | "

                f"market={r['market_filter_status']} | "

                f"contract={r['contract_risk_status']} | "
                f"top10={fmt_number(r['top_holders_percent'])} | "

                f"liquidity={r.get('liquidity_status')} | "

                f"final={r['final_watchlist_status']} | "
                f"pass={r['final_watchlist_pass']} | "

                f"reason={r['final_watchlist_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

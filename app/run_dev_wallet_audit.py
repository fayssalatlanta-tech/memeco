import asyncio
from decimal import InvalidOperation

from app.db import create_pool
from app.services.dev_wallet_audit_service import run_dev_wallet_audit_service


def fmt_number(value, digits=2):
    if value is None:
        return "n/a"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError, InvalidOperation):
        return str(value)


async def main():
    pool = await create_pool()

    try:
        results = await run_dev_wallet_audit_service(pool)
        print(f"Saved dev wallet audit results: {len(results)}")

        print("\nDev Wallet Audit Results")
        print("-" * 160)

        for result in results:
            print(
                f"symbol={result.get('symbol')} | "
                f"dev={result.get('dev_wallet_address')} | "
                f"status={result.get('dev_audit_status')} | "
                f"sold={fmt_number(result.get('sold_token_amount'))} | "
                f"out={fmt_number(result.get('total_token_out'))} | "
                f"balance={fmt_number(result.get('current_balance'))} | "
                f"reason={result.get('dev_audit_reason')}"
            )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

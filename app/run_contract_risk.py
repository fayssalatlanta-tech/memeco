import asyncio
from decimal import InvalidOperation

from app.db import create_pool
from app.services.contract_risk_service import run_contract_risk_service


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
        results = await run_contract_risk_service(pool)

        print(f"Saved contract risk results: {len(results)}")

        print("\nContract Risk Results")
        print("-" * 120)

        for r in results:
            print(
                f"symbol={r.get('symbol')} | "
                f"token={r.get('token_address')} | "
                f"status={r['contract_risk_status']} | "
                f"pass={r['contract_risk_pass']} | "
                f"risk_score={fmt_number(r['risk_score'], 0)} | "
                f"risk_level={r['risk_level']} | "
                f"mint={r['mint_authority_status']} | "
                f"freeze={r['freeze_authority_status']} | "
                f"top10={fmt_number(r['top_holders_percent'], 2)} | "
                f"reason={r['contract_risk_reason']}"
            )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

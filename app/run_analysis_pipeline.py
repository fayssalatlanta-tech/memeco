import asyncio

from app.db import create_pool
from app.services.cluster_analysis_service import run_cluster_analysis_service
from app.services.contract_risk_service import run_contract_risk_service
from app.services.dev_wallet_audit_service import run_dev_wallet_audit_service
from app.services.dev_wallet_flow_service import run_dev_wallet_flow_service
from app.services.liquidity_filter_service import run_liquidity_filter_service
from app.services.market_filter_service import (
    get_early_dex_candidates,
    save_market_filter_results,
)
from app.services.wallet_analysis_service import run_wallet_analysis_service
from app.services.wallet_intelligence_service import run_wallet_intelligence_service
from app.services.wallet_manipulation_service import run_wallet_manipulation_service
from app.services.watchlist_decision_service import run_watchlist_decision_service


async def main():
    pool = await create_pool()

    try:
        print("\n1. Running Market Filter...")
        market_candidates = await get_early_dex_candidates(pool)
        market_results = await save_market_filter_results(pool, market_candidates)
        print(f"Saved market filter results: {len(market_results)}")

        print("\n2. Running Contract Risk...")
        contract_results = await run_contract_risk_service(pool)
        print(f"Saved contract risk results: {len(contract_results)}")

        print("\n3. Running Liquidity Filter...")
        liquidity_results = await run_liquidity_filter_service(pool)
        print(f"Saved liquidity filter results: {len(liquidity_results)}")

        print("\n4. Running Wallet Analysis...")
        wallet_results = await run_wallet_analysis_service(pool)
        print(f"Saved wallet analysis results: {len(wallet_results)}")

        print("\n5. Running Cluster Analysis...")
        cluster_results = await run_cluster_analysis_service(pool)
        print(f"Saved cluster analysis results: {len(cluster_results)}")

        print("\n6. Running Wallet Intelligence...")
        intelligence_results = await run_wallet_intelligence_service(pool)
        print(f"Saved wallet intelligence results: {len(intelligence_results)}")

        print("\n7. Running Wallet Manipulation...")
        manipulation_results = await run_wallet_manipulation_service(pool)
        print(f"Saved wallet manipulation results: {len(manipulation_results)}")

        print("\n8. Running Dev Wallet Audit...")
        dev_audit_results = await run_dev_wallet_audit_service(pool)
        print(f"Saved dev wallet audit results: {len(dev_audit_results)}")

        print("\n9. Running Dev Wallet Flow...")
        dev_flow_results = await run_dev_wallet_flow_service(pool)
        print(f"Saved dev wallet flow results: {len(dev_flow_results)}")

        print("\n10. Running Watchlist Decision...")
        watchlist_results = await run_watchlist_decision_service(pool)
        print(f"Saved watchlist decisions: {len(watchlist_results)}")

        print("\nPipeline finished.")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())


def cli():
    asyncio.run(main())

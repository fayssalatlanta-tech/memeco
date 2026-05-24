import unittest
from datetime import datetime, timezone

from app.services.whale_reverse_discovery_service import (
    DexGainerTarget,
    extract_early_buyer_positions,
    position_to_trade,
)


class WhaleReverseDiscoveryServiceTests(unittest.TestCase):
    def make_target(self):
        return DexGainerTarget(
            token_id=1,
            pair_id=10,
            chain="solana",
            token_address="TOKEN",
            token_symbol="MOON",
            pair_address="PAIR",
            price_native=0.02,
            price_usd=3.0,
            price_change_24h_percent=900,
            volume_24h_usd=100000,
            liquidity_usd=50000,
            pair_created_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
            raw_json={},
        )

    def test_extracts_early_buyer_and_calculates_open_profit(self):
        target = self.make_target()
        transactions = [
            {
                "signature": "sig1",
                "timestamp": 1_700_000_060,
                "tokenTransfers": [
                    {
                        "mint": "TOKEN",
                        "fromUserAccount": "POOL",
                        "toUserAccount": "BUYER",
                        "tokenAmount": 1000,
                    }
                ],
                "nativeTransfers": [
                    {
                        "fromUserAccount": "BUYER",
                        "toUserAccount": "POOL",
                        "amount": 5_000_000_000,
                    }
                ],
            }
        ]

        positions = extract_early_buyer_positions(target, transactions, early_buyer_limit=50)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].wallet_address, "BUYER")
        self.assertEqual(positions[0].native_spent_sol, 5)
        self.assertEqual(positions[0].token_in, 1000)
        self.assertEqual(positions[0].minutes_after_launch, 1)

        trade = position_to_trade(positions[0], target)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.amount_sol, 5)
        self.assertEqual(trade.pnl_sol, 15)
        self.assertEqual(trade.roi_percent, 300)

    def test_includes_sell_receipts_in_profit(self):
        target = self.make_target()
        transactions = [
            {
                "signature": "buy",
                "timestamp": 1_700_000_060,
                "tokenTransfers": [
                    {
                        "mint": "TOKEN",
                        "fromUserAccount": "POOL",
                        "toUserAccount": "BUYER",
                        "tokenAmount": 1000,
                    }
                ],
                "nativeTransfers": [
                    {
                        "fromUserAccount": "BUYER",
                        "toUserAccount": "POOL",
                        "amount": 5_000_000_000,
                    }
                ],
            },
            {
                "signature": "sell",
                "timestamp": 1_700_000_120,
                "tokenTransfers": [
                    {
                        "mint": "TOKEN",
                        "fromUserAccount": "BUYER",
                        "toUserAccount": "POOL",
                        "tokenAmount": 400,
                    }
                ],
                "nativeTransfers": [
                    {
                        "fromUserAccount": "POOL",
                        "toUserAccount": "BUYER",
                        "amount": 6_000_000_000,
                    }
                ],
            },
        ]

        positions = extract_early_buyer_positions(target, transactions, early_buyer_limit=50)
        trade = position_to_trade(positions[0], target)

        self.assertEqual(positions[0].token_out, 400)
        self.assertEqual(positions[0].native_received_sol, 6)
        self.assertEqual(trade.pnl_sol, 13)


if __name__ == "__main__":
    unittest.main()

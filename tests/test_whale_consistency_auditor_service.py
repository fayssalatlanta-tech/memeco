import unittest

from app.services.whale_consistency_auditor_service import (
    build_positions_from_transactions,
    positions_to_trades,
)


class WhaleConsistencyAuditorTests(unittest.TestCase):
    def test_builds_positions_from_wallet_swaps(self):
        transactions = [
            {
                "signature": "buy",
                "timestamp": 1_700_000_000,
                "tokenTransfers": [
                    {
                        "mint": "TOKEN",
                        "fromUserAccount": "POOL",
                        "toUserAccount": "WALLET",
                        "tokenAmount": 100,
                    }
                ],
                "nativeTransfers": [
                    {
                        "fromUserAccount": "WALLET",
                        "toUserAccount": "POOL",
                        "amount": 1_000_000_000,
                    }
                ],
            },
            {
                "signature": "sell",
                "timestamp": 1_700_000_060,
                "tokenTransfers": [
                    {
                        "mint": "TOKEN",
                        "fromUserAccount": "WALLET",
                        "toUserAccount": "POOL",
                        "tokenAmount": 40,
                    }
                ],
                "nativeTransfers": [
                    {
                        "fromUserAccount": "POOL",
                        "toUserAccount": "WALLET",
                        "amount": 2_000_000_000,
                    }
                ],
            },
        ]

        positions = build_positions_from_transactions("WALLET", transactions)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].token_in, 100)
        self.assertEqual(positions[0].token_out, 40)
        self.assertEqual(positions[0].native_spent_sol, 1)
        self.assertEqual(positions[0].native_received_sol, 2)

        trades = positions_to_trades(positions, {"TOKEN": {"priceNative": "0.05"}})
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0][1].pnl_sol, 4)
        self.assertEqual(trades[0][1].roi_percent, 400)


if __name__ == "__main__":
    unittest.main()

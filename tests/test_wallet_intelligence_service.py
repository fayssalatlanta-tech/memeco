import unittest
from datetime import datetime, timezone

from app.services.wallet_intelligence_service import analyze_wallet_transactions

TOKEN = "TokenMint111111111111111111111111111111111"
WALLET = "Wallet111111111111111111111111111111111111"
OTHER = "Other1111111111111111111111111111111111111"
LAUNCH_AT = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


def token_tx(
    timestamp: int,
    amount: float,
    to_wallet: bool = True,
    tx_type: str = "SWAP",
    sol_spent: float = 0,
    sol_received: float = 0,
):
    native_transfers = []
    if sol_spent:
        native_transfers.append(
            {
                "fromUserAccount": WALLET,
                "toUserAccount": OTHER,
                "amount": int(sol_spent * 1_000_000_000),
            }
        )
    if sol_received:
        native_transfers.append(
            {
                "fromUserAccount": OTHER,
                "toUserAccount": WALLET,
                "amount": int(sol_received * 1_000_000_000),
            }
        )

    return {
        "timestamp": timestamp,
        "type": tx_type,
        "nativeTransfers": native_transfers,
        "tokenTransfers": [
            {
                "mint": TOKEN,
                "tokenAmount": amount,
                "toUserAccount": WALLET if to_wallet else OTHER,
                "fromUserAccount": OTHER if to_wallet else WALLET,
            }
        ],
    }


def analyze(**overrides):
    params = {
        "wallet_address": WALLET,
        "token_address": TOKEN,
        "pair_created_at": LAUNCH_AT,
        "rank": 8,
        "holder_percent": 0.8,
        "funding_source": None,
        "funding_source_holder_count": 0,
        "transactions": [token_tx(1_700_000_400, 100)],
    }
    params.update(overrides)
    return analyze_wallet_transactions(**params)


class WalletIntelligenceTests(unittest.TestCase):
    def test_labels_smart_wallet_for_healthy_holder(self):
        result = analyze()

        self.assertIn("SMART_WALLET", result["labels"])
        self.assertGreater(result["wallet_score"], 0)
        self.assertIn("SMART_WALLET", result["details"]["label_reasons"])

    def test_labels_sniper_only_for_first_minute_entries(self):
        result = analyze(transactions=[token_tx(1_700_000_030, 100)])

        self.assertIn("SNIPER", result["labels"])
        self.assertNotIn("SMART_WALLET", result["labels"])

    def test_labels_fresh_wallet_when_oldest_seen_transaction_is_under_24h(self):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        result = analyze(
            pair_created_at=datetime.fromtimestamp(now_ts - 3600, tz=timezone.utc),
            transactions=[token_tx(now_ts - 1800, 100)],
        )

        self.assertIn("FRESH_WALLET", result["labels"])
        self.assertIn("FRESH_WALLET", result["details"]["label_reasons"])
        self.assertLess(result["wallet_score"], 0)

    def test_labels_whale_for_large_holder_or_top_rank(self):
        large_holder = analyze(holder_percent=6)
        top_rank_holder = analyze(rank=2, holder_percent=2)

        self.assertIn("WHALE", large_holder["labels"])
        self.assertIn("WHALE", top_rank_holder["labels"])

    def test_labels_dumper_when_sell_ratio_is_high(self):
        result = analyze(
            transactions=[
                token_tx(1_700_000_400, 100),
                token_tx(1_700_000_500, 70, to_wallet=False),
            ]
        )

        self.assertIn("DUMPER", result["labels"])
        self.assertLess(result["wallet_score"], 0)

    def test_labels_dev_related_for_shared_funding_source(self):
        result = analyze(
            funding_source="Funder11111111111111111111111111111111111",
            funding_source_holder_count=3,
        )

        self.assertIn("DEV_RELATED", result["labels"])
        self.assertNotIn("SMART_WALLET", result["labels"])

    def test_labels_bot_for_burst_dex_activity(self):
        transactions = [
            token_tx(1_700_000_400 + index * 10, 10)
            for index in range(12)
        ]

        result = analyze(transactions=transactions)

        self.assertIn("BOT", result["labels"])
        self.assertNotIn("SMART_WALLET", result["labels"])

    def test_calculates_early_buyer_realized_profit_from_native_swap_flow(self):
        result = analyze(
            transactions=[
                token_tx(1_700_000_400, 100, sol_spent=1.0),
                token_tx(1_700_000_800, 50, to_wallet=False, sol_received=1.2),
            ]
        )

        early_buyer = result["details"]["early_buyer"]

        self.assertEqual(early_buyer["status"], "PARTIAL_EXIT")
        self.assertEqual(early_buyer["profit_state"], "PROFIT")
        self.assertAlmostEqual(early_buyer["native_spent"], 1.0)
        self.assertAlmostEqual(early_buyer["native_received"], 1.2)
        self.assertAlmostEqual(early_buyer["realized_pnl_native"], 0.7)
        self.assertEqual(
            result["details"]["first_exit_at"],
            datetime.fromtimestamp(1_700_000_800, tz=timezone.utc),
        )

    def test_marks_holding_wallet_as_unrealized_when_no_sell_seen(self):
        result = analyze(transactions=[token_tx(1_700_000_400, 100, sol_spent=0.5)])

        early_buyer = result["details"]["early_buyer"]

        self.assertEqual(early_buyer["status"], "HOLDING")
        self.assertEqual(early_buyer["profit_state"], "UNREALIZED")


if __name__ == "__main__":
    unittest.main()

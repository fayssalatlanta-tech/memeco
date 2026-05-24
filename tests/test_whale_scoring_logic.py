import unittest

from app.whale_scoring_logic import (
    WhaleTrade,
    calculate_whale_reliability,
    classify_elite_wallet,
    summarize_whale_trades,
    whale_score_breakdown,
)


class WhaleScoringLogicTests(unittest.TestCase):
    def test_requires_at_least_five_valid_trades(self):
        trades = [
            WhaleTrade(amount_sol=1, pnl_sol=10, roi_percent=500, minutes_after_launch=1)
            for _ in range(4)
        ]

        self.assertEqual(calculate_whale_reliability(trades), 0)

    def test_scores_consistent_profitable_early_wallet_as_elite(self):
        trades = [
            WhaleTrade(amount_sol=2, pnl_sol=25, roi_percent=600, minutes_after_launch=1.5)
            for _ in range(5)
        ]

        summary = summarize_whale_trades(trades)

        self.assertGreaterEqual(summary["reliability_score"], 75)
        self.assertGreaterEqual(summary["reliability_score_10"], 7.5)
        self.assertEqual(classify_elite_wallet(summary), "ELITE_SMART_MONEY")

    def test_score_breakdown_matches_weighted_formula(self):
        trades = [
            WhaleTrade(amount_sol=2, pnl_sol=10, roi_percent=250, minutes_after_launch=5)
            for _ in range(5)
        ]

        breakdown = whale_score_breakdown(trades)

        self.assertEqual(breakdown["win_rate_score"], 100)
        self.assertEqual(breakdown["roi_score"], 50)
        self.assertEqual(breakdown["early_entry_score"], 50)
        self.assertEqual(breakdown["consistency_score"], 50)
        self.assertEqual(breakdown["score"], 67.5)
        self.assertEqual(calculate_whale_reliability(trades), 67.5)

    def test_excludes_bot_like_wallet(self):
        trades = [
            WhaleTrade(
                amount_sol=2,
                pnl_sol=25,
                roi_percent=600,
                minutes_after_launch=1.5,
                tx_per_minute=6,
            )
            for _ in range(5)
        ]

        summary = summarize_whale_trades(trades)

        self.assertTrue(summary["bot_flag"])
        self.assertEqual(summary["reliability_score"], 0)
        self.assertEqual(classify_elite_wallet(summary), "BOT_EXCLUDED")

    def test_filters_dust_trades(self):
        trades = [
            WhaleTrade(amount_sol=0.01, pnl_sol=100, roi_percent=1000, minutes_after_launch=1),
            WhaleTrade(amount_sol=1, pnl_sol=1, roi_percent=10, minutes_after_launch=20),
        ]

        summary = summarize_whale_trades(trades)

        self.assertEqual(summary["trade_count"], 1)
        self.assertEqual(summary["reliability_score"], 0)


if __name__ == "__main__":
    unittest.main()

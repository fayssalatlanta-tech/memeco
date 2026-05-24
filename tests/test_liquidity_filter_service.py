import unittest

from app.services.liquidity_filter_service import classify_liquidity, extract_lp_lock_summary


class LiquidityFilterTests(unittest.TestCase):
    def test_flags_critical_liquidity_trap_for_tiny_liquidity_and_high_mcap_ratio(self):
        result = classify_liquidity(
            {
                "liquidity_usd": 2500,
                "market_cap_usd": 100000,
                "volume_1h_usd": 60000,
            }
        )

        self.assertEqual(result["liquidity_status"], "LIQUIDITY_DANGER")
        self.assertFalse(result["liquidity_pass"])
        self.assertEqual(result["liquidity_trap_status"], "LIQUIDITY_TRAP_CRITICAL")
        self.assertGreaterEqual(result["liquidity_trap_score"], 75)
        self.assertIn("TRAP_EXTREME_MCAP_TO_LIQUIDITY", result["liquidity_trap_warnings"])

    def test_marks_low_trap_when_liquidity_depth_and_ratios_are_healthy(self):
        result = classify_liquidity(
            {
                "liquidity_usd": 75000,
                "market_cap_usd": 180000,
                "volume_1h_usd": 25000,
                "token_address": "TOKEN",
                "contract_raw_json": {
                    "markets": [
                        {
                            "pubkey": "PAIR",
                            "marketType": "pump_fun_amm",
                            "lp": {
                                "baseMint": "TOKEN",
                                "quoteMint": "So11111111111111111111111111111111111111112",
                                "lpLockedPct": 100,
                                "lpLockedUSD": 75000,
                                "lpUnlocked": 0,
                            },
                        }
                    ]
                },
            }
        )

        self.assertEqual(result["liquidity_status"], "LIQUIDITY_STRONG")
        self.assertTrue(result["liquidity_pass"])
        self.assertEqual(result["liquidity_trap_status"], "LIQUIDITY_TRAP_LOW")
        self.assertEqual(result["lp_lock"]["lp_lock_status"], "LP_LOCKED")
        self.assertEqual(result["lp_lock"]["lp_locked_pct"], 100)
        self.assertLess(result["liquidity_trap_score"], 25)

    def test_extracts_unlocked_lp_status_from_rugcheck_market(self):
        summary = extract_lp_lock_summary(
            {
                "markets": [
                    {
                        "pubkey": "PAIR",
                        "lp": {
                            "baseMint": "TOKEN",
                            "quoteMint": "SOL",
                            "lpLockedPct": 10,
                            "lpUnlocked": 900,
                        },
                    }
                ]
            },
            "TOKEN",
        )

        self.assertEqual(summary["lp_lock_status"], "LP_UNLOCKED")
        self.assertEqual(summary["lp_locked_pct"], 10)


if __name__ == "__main__":
    unittest.main()

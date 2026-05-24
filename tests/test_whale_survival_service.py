import unittest

from app.services.whale_survival_service import (
    SurvivalTrade,
    build_survival_profile,
    classify_whale_style,
    is_rugged_trade,
)


class WhaleSurvivalServiceTests(unittest.TestCase):
    def test_flags_rugged_trade_below_minus_90_roi(self):
        trade = SurvivalTrade(
            wallet_address="wallet",
            token_address="token",
            token_symbol="RUG",
            native_spent_sol=10,
            native_received_sol=0,
            pnl_sol=-9.5,
            roi_percent=-95,
        )

        self.assertTrue(is_rugged_trade(trade))

    def test_builds_safe_survival_profile(self):
        trades = [
            SurvivalTrade(
                wallet_address="wallet",
                token_address=f"token{i}",
                token_symbol=f"T{i}",
                native_spent_sol=1,
                native_received_sol=2,
                pnl_sol=1,
                roi_percent=100,
                raw_json={"token_in": 100, "token_out": 50},
            )
            for i in range(5)
        ]

        profile = build_survival_profile("wallet", trades)

        self.assertEqual(profile["survival_rate_percent"], 100)
        self.assertEqual(profile["security_level"], "SAFE_TO_WATCH")
        self.assertEqual(profile["exit_style"], "LADDERING_OUT")

    def test_low_survival_rate_is_risky(self):
        trades = [
            SurvivalTrade("wallet", f"token{i}", f"T{i}", 1, 0, -0.95, -95)
            for i in range(3)
        ] + [
            SurvivalTrade("wallet", f"ok{i}", f"OK{i}", 1, 2, 1, 100)
            for i in range(2)
        ]

        profile = build_survival_profile("wallet", trades)

        self.assertEqual(profile["rugged_trade_count"], 3)
        self.assertEqual(profile["survival_rate_percent"], 40)
        self.assertEqual(profile["security_level"], "RISKY")

    def test_classifies_whale_style_by_hold_time(self):
        self.assertEqual(classify_whale_style(4.9), "SCALPER_SNIPER")
        self.assertEqual(classify_whale_style(20), "DAY_TRADER")
        self.assertEqual(classify_whale_style(90), "SWING_WHALE")


if __name__ == "__main__":
    unittest.main()

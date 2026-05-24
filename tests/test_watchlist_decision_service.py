import unittest

from app.services.watchlist_decision_service import (
    calculate_insider_probability,
    classify_watchlist_decision,
)


class WatchlistDecisionTests(unittest.TestCase):
    def test_calculates_low_insider_probability_for_clean_distribution(self):
        probability = calculate_insider_probability(
            {
                "cluster_status": "CLUSTER_PASS",
                "largest_cluster_size": 0,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_score": 0,
                "top_holder_percent": 3,
                "top10_holders_percent": 18,
                "intelligence_summary": {"snipers": 0},
            }
        )

        self.assertEqual(probability["score"], 0)
        self.assertEqual(probability["level"], "LOW")

    def test_calculates_high_insider_probability_from_cluster_manipulation_snipers_and_holders(self):
        probability = calculate_insider_probability(
            {
                "cluster_status": "CLUSTER_DANGER",
                "largest_cluster_size": 6,
                "manipulation_status": "MANIPULATION_DANGER",
                "manipulation_score": 8,
                "top_holder_percent": 28,
                "top10_holders_percent": 72,
                "intelligence_summary": {"snipers": 4, "fresh_wallets": 2},
            }
        )

        self.assertGreaterEqual(probability["score"], 75)
        self.assertEqual(probability["level"], "CRITICAL")
        self.assertIn("4 sniper wallet(s)", probability["reasons"])
        self.assertIn("2 fresh top-holder wallet(s)", probability["reasons"])

    def test_rejects_market_failure_before_other_filters(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": False,
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_MARKET")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_rejects_when_developer_sold_tokens(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
                "dev_audit_status": "DEV_SOLD_PARTIAL",
                "dev_audit_reason": "Developer sold some tokens",
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_DEV_WALLET")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_waits_for_missing_contract_data(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": None,
                "contract_risk_pass": None,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_WAIT_SECURITY_DATA")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_rejects_contract_risk_failure(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_DANGER",
                "contract_risk_pass": False,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_CONTRACT_RISK")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_waits_for_missing_liquidity_data(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": None,
                "liquidity_pass": None,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_WAIT_LIQUIDITY")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_rejects_dangerous_liquidity(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_DANGER",
                "liquidity_pass": False,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_LIQUIDITY")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_passes_with_high_risk_for_market_or_liquidity_warnings(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS_HIGH_RISK",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_PASS_HIGH_RISK")
        self.assertTrue(decision["final_watchlist_pass"])

    def test_passes_clean_token(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_PASS")
        self.assertTrue(decision["final_watchlist_pass"])

    def test_rejects_dangerous_wallet_intelligence(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
                "intelligence_summary": {
                    "dev_related": 1,
                    "dumpers": 1,
                    "bots": 0,
                    "snipers": 0,
                    "whales": 0,
                    "smart_wallets": 0,
                    "avg_wallet_score": -2,
                },
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_WALLET_INTELLIGENCE")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_marks_warning_wallet_intelligence_as_high_risk(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
                "intelligence_summary": {
                    "dev_related": 0,
                    "dumpers": 1,
                    "bots": 0,
                    "snipers": 0,
                    "whales": 0,
                    "smart_wallets": 0,
                    "avg_wallet_score": -1,
                },
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_PASS_HIGH_RISK")
        self.assertTrue(decision["final_watchlist_pass"])

    def test_rejects_wallet_danger_before_liquidity_warning_pass(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_WARNING",
                "liquidity_pass": True,
                "wallet_status": "WALLET_DANGER",
                "wallet_pass": False,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_WALLET_RISK")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_waits_for_missing_wallet_data(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": None,
                "wallet_pass": None,
                "cluster_status": "CLUSTER_PASS",
                "cluster_pass": True,
                "manipulation_status": "MANIPULATION_PASS",
                "manipulation_pass": True,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_WAIT_WALLET_DATA")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_rejects_cluster_danger(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": "CLUSTER_DANGER",
                "cluster_pass": False,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_REJECT_CLUSTER_RISK")
        self.assertFalse(decision["final_watchlist_pass"])

    def test_waits_for_missing_cluster_data(self):
        decision = classify_watchlist_decision(
            {
                "market_filter_pass": True,
                "market_filter_status": "MARKET_PASS",
                "contract_risk_status": "CONTRACT_PASS",
                "contract_risk_pass": True,
                "liquidity_status": "LIQUIDITY_STRONG",
                "liquidity_pass": True,
                "wallet_status": "WALLET_PASS",
                "wallet_pass": True,
                "cluster_status": None,
                "cluster_pass": None,
            }
        )

        self.assertEqual(decision["final_watchlist_status"], "WATCHLIST_WAIT_CLUSTER_DATA")
        self.assertFalse(decision["final_watchlist_pass"])


if __name__ == "__main__":
    unittest.main()

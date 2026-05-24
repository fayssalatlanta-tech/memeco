import unittest

from app.dexscreener import (
    dedupe_latest_candidates,
    is_bonding_pair,
    select_preferred_pair,
    sort_discovered_pairs_by_recency,
)


class DexScreenerPairSelectionTests(unittest.TestCase):
    def test_prefers_new_real_dex_pair_over_pumpfun_bonding_pair(self):
        pairs = [
            {
                "chainId": "solana",
                "dexId": "pumpfun",
                "pairAddress": "old",
                "pairCreatedAt": 1_778_432_365_000,
                "liquidity": {"usd": 50_000},
                "volume": {"h1": 0, "h24": 80_000},
                "txns": {"h1": {"buys": 0, "sells": 0}, "h24": {"buys": 900, "sells": 600}},
            },
            {
                "chainId": "solana",
                "dexId": "pumpswap",
                "pairAddress": "new",
                "pairCreatedAt": 1_778_435_238_000,
                "liquidity": {"usd": 4_000},
                "volume": {"h1": 250, "h24": 30_000},
                "txns": {"h1": {"buys": 2, "sells": 3}, "h24": {"buys": 400, "sells": 490}},
            },
        ]

        selected = select_preferred_pair(pairs, "solana")

        self.assertEqual(selected["pairAddress"], "new")

    def test_rejects_tokens_that_only_have_pumpfun_bonding_pairs(self):
        pairs = [
            {
                "chainId": "solana",
                "dexId": "pumpfun",
                "pairAddress": "bonding-only",
                "pairCreatedAt": 1_778_432_365_000,
                "liquidity": {"usd": 50_000},
                "volume": {"h1": 5_000, "h24": 80_000},
                "txns": {"h1": {"buys": 30, "sells": 12}, "h24": {"buys": 900, "sells": 600}},
            },
        ]

        selected = select_preferred_pair(pairs, "solana")

        self.assertIsNone(selected)

    def test_only_pumpfun_is_treated_as_bonding(self):
        self.assertTrue(is_bonding_pair({"dexId": "pumpfun"}))
        self.assertFalse(is_bonding_pair({"dexId": "pumpswap"}))

    def test_dedupes_latest_candidates_from_multiple_sources(self):
        candidates = dedupe_latest_candidates(
            [
                ("profile", [{"chainId": "solana", "tokenAddress": "A", "icon": "profile.png"}]),
                ("ad", [{"chainId": "solana", "tokenAddress": "A"}]),
                ("boost_latest", [{"chainId": "ethereum", "tokenAddress": "B"}]),
                ("boost_top", [{"chainId": "solana", "tokenAddress": "C"}]),
            ]
        )

        self.assertEqual([candidate["tokenAddress"] for candidate in candidates], ["A", "C"])
        self.assertEqual(candidates[0]["_sources"], ["profile", "ad"])
        self.assertEqual(candidates[0]["icon"], "profile.png")

    def test_sorts_discovered_pairs_by_newest_pair_created_at(self):
        old_profile = {"tokenAddress": "old"}
        new_profile = {"tokenAddress": "new"}
        discovered = [
            (old_profile, {"pairCreatedAt": 1_700_000_000_000, "volume": {}, "txns": {}, "liquidity": {}}),
            (new_profile, {"pairCreatedAt": 1_800_000_000_000, "volume": {}, "txns": {}, "liquidity": {}}),
        ]

        sorted_pairs = sort_discovered_pairs_by_recency(discovered)

        self.assertEqual(sorted_pairs[0][0]["tokenAddress"], "new")


if __name__ == "__main__":
    unittest.main()

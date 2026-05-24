import unittest
from datetime import datetime, timezone

from app.services.wallet_manipulation_service import classify_manipulation


class WalletManipulationTests(unittest.TestCase):
    def test_flags_danger_for_shared_funder_and_linked_dump(self):
        holder_set = {"A", "B", "C"}
        result = classify_manipulation(
            holder_count=3,
            edges=[
                {"relation_type": "TOKEN_LINK", "from_wallet": "A", "to_wallet": "B"},
                {"relation_type": "SOL_LINK", "from_wallet": "B", "to_wallet": "C"},
            ],
            existing_funding_edges=[
                {"funder_address": "F", "holder_address": "A"},
                {"funder_address": "F", "holder_address": "B"},
                {"funder_address": "F", "holder_address": "C"},
            ],
            dump_events=[
                {"wallet": "A", "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)},
                {"wallet": "B", "timestamp": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)},
            ],
            holder_set=holder_set,
        )

        self.assertEqual(result["manipulation_status"], "MANIPULATION_DANGER")
        self.assertFalse(result["manipulation_pass"])

    def test_passes_when_no_strong_relationships_exist(self):
        result = classify_manipulation(
            holder_count=3,
            edges=[],
            existing_funding_edges=[],
            dump_events=[],
            holder_set={"A", "B", "C"},
        )

        self.assertEqual(result["manipulation_status"], "MANIPULATION_PASS")
        self.assertTrue(result["manipulation_pass"])


if __name__ == "__main__":
    unittest.main()

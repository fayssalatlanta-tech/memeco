import unittest

from app.services.dev_wallet_audit_service import analyze_dev_wallet_transactions


TOKEN = "TokenMint111111111111111111111111111111111"
DEV = "DevWallet111111111111111111111111111111111"
OTHER = "OtherWallet111111111111111111111111111111"


def token_tx(amount: float, from_dev: bool = True, tx_type: str = "SWAP"):
    return {
        "timestamp": 1_700_000_000,
        "signature": "sig",
        "type": tx_type,
        "tokenTransfers": [
            {
                "mint": TOKEN,
                "tokenAmount": amount,
                "fromUserAccount": DEV if from_dev else OTHER,
                "toUserAccount": OTHER if from_dev else DEV,
            }
        ],
    }


class DevWalletAuditTests(unittest.TestCase):
    def test_detects_dev_partial_sell(self):
        result = analyze_dev_wallet_transactions(
            dev_wallet=DEV,
            token_address=TOKEN,
            creator_balance=700,
            transactions=[
                token_tx(1000, from_dev=False),
                token_tx(300, from_dev=True, tx_type="SWAP"),
            ],
        )

        self.assertEqual(result["dev_audit_status"], "DEV_SOLD_PARTIAL")
        self.assertFalse(result["dev_audit_pass"])
        self.assertEqual(result["sold_token_amount"], 300)

    def test_detects_dev_transfer_without_sell(self):
        result = analyze_dev_wallet_transactions(
            dev_wallet=DEV,
            token_address=TOKEN,
            creator_balance=600,
            transactions=[
                token_tx(1000, from_dev=False),
                token_tx(400, from_dev=True, tx_type="TRANSFER"),
            ],
        )

        self.assertEqual(result["dev_audit_status"], "DEV_TRANSFERRED_TOKENS")
        self.assertFalse(result["dev_audit_pass"])
        self.assertEqual(result["transferred_token_amount"], 400)


if __name__ == "__main__":
    unittest.main()

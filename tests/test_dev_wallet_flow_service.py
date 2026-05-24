import unittest

from app.services.dev_wallet_flow_service import analyze_dev_wallet_flow

TOKEN = "TokenMint111111111111111111111111111111111"
DEV = "DevWallet111111111111111111111111111111111"
A = "ProxyA111111111111111111111111111111111111"
B = "ProxyB111111111111111111111111111111111111"
BUYER = "Buyer111111111111111111111111111111111111"


def token_transfer_tx(from_wallet, to_wallet, amount, tx_type="TRANSFER", signature="sig"):
    return {
        "timestamp": 1_700_000_000,
        "signature": signature,
        "type": tx_type,
        "tokenTransfers": [
            {
                "mint": TOKEN,
                "tokenAmount": amount,
                "fromUserAccount": from_wallet,
                "toUserAccount": to_wallet,
            }
        ],
    }


class DevWalletFlowTests(unittest.TestCase):
    def test_flags_proxy_dump_from_direct_recipient(self):
        result = analyze_dev_wallet_flow(
            dev_wallet=DEV,
            token_address=TOKEN,
            creator_balance=700,
            dev_transactions=[
                token_transfer_tx(BUYER, DEV, 1000, signature="in"),
                token_transfer_tx(DEV, A, 300, signature="dev_to_a"),
            ],
            wallet_transactions={
                A: [token_transfer_tx(A, BUYER, 250, tx_type="SWAP", signature="a_sell")]
            },
        )

        self.assertEqual(result["flow_status"], "DEV_FLOW_DANGER")
        self.assertFalse(result["flow_pass"])
        self.assertIn("DEV_PROXY_DUMP", result["warnings"])
        self.assertEqual(result["proxy_dump_count"], 1)

    def test_flags_splitter_wallet(self):
        split_transactions = [
            token_transfer_tx(A, f"Receiver{i:02d}", 20, signature=f"split_{i}")
            for i in range(10)
        ]
        result = analyze_dev_wallet_flow(
            dev_wallet=DEV,
            token_address=TOKEN,
            creator_balance=700,
            dev_transactions=[
                token_transfer_tx(BUYER, DEV, 1000, signature="in"),
                token_transfer_tx(DEV, A, 300, signature="dev_to_a"),
            ],
            wallet_transactions={A: split_transactions},
        )

        self.assertEqual(result["flow_status"], "DEV_FLOW_DANGER")
        self.assertIn("DEV_SPLITTER_DETECTED", result["warnings"])
        self.assertEqual(result["splitter_count"], 1)

    def test_ignores_dust_recipients_below_threshold(self):
        result = analyze_dev_wallet_flow(
            dev_wallet=DEV,
            token_address=TOKEN,
            creator_balance=999,
            dev_transactions=[
                token_transfer_tx(BUYER, DEV, 1000, signature="in"),
                token_transfer_tx(DEV, A, 1, signature="dust"),
            ],
            wallet_transactions={A: [token_transfer_tx(A, BUYER, 1, tx_type="SWAP")]},
        )

        self.assertEqual(result["flow_status"], "DEV_FLOW_PASS")
        self.assertEqual(result["direct_recipient_count"], 0)
        self.assertEqual(result["shadow_dev_score"], 0)


if __name__ == "__main__":
    unittest.main()

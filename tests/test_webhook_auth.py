"""
Tests for the whale-signal webhook authorization check.

The check uses :func:`hmac.compare_digest` to avoid leaking the secret
through response-time differences. These tests verify the behavior of the
helper itself; the FastAPI route wiring is exercised end-to-end by manual
testing and is intentionally not covered here (no fixture for spinning up
the full app with a real ``app.state.pool``).
"""

import unittest

from app.web_server import _whale_webhook_auth_ok


class WhaleWebhookAuthOkTests(unittest.TestCase):
    def test_no_expected_secret_means_auth_disabled(self) -> None:
        # When the operator did not configure WHALE_WEBHOOK_AUTH_HEADER, any
        # incoming request (including one without an Authorization header)
        # is allowed through. This matches the previous behavior.
        self.assertTrue(_whale_webhook_auth_ok(None, None))
        self.assertTrue(_whale_webhook_auth_ok("anything", None))
        self.assertTrue(_whale_webhook_auth_ok(None, ""))

    def test_missing_provided_header_is_rejected(self) -> None:
        self.assertFalse(_whale_webhook_auth_ok(None, "expected-secret"))
        self.assertFalse(_whale_webhook_auth_ok("", "expected-secret"))

    def test_correct_header_is_accepted(self) -> None:
        self.assertTrue(
            _whale_webhook_auth_ok("expected-secret", "expected-secret")
        )

    def test_wrong_header_is_rejected(self) -> None:
        self.assertFalse(
            _whale_webhook_auth_ok("wrong-secret", "expected-secret")
        )

    def test_off_by_one_prefix_is_rejected(self) -> None:
        # The classic timing attack: an attacker sends the secret one byte
        # at a time and watches response timing. The == operator returns as
        # soon as a byte differs, leaking the prefix length. compare_digest
        # always walks both inputs to the end. This test pins the
        # functional outcome (rejection); the timing property is enforced
        # by hmac.compare_digest itself.
        self.assertFalse(
            _whale_webhook_auth_ok("expected-secre", "expected-secret")
        )
        self.assertFalse(
            _whale_webhook_auth_ok("expected-secretX", "expected-secret")
        )

    def test_unicode_in_secret(self) -> None:
        # The helper encodes both inputs to UTF-8 bytes before comparing,
        # so non-ASCII secrets work end to end.
        secret = "péro-gátè-key-🚀"
        self.assertTrue(_whale_webhook_auth_ok(secret, secret))
        self.assertFalse(_whale_webhook_auth_ok(secret + "x", secret))


if __name__ == "__main__":
    unittest.main()

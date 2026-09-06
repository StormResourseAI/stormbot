"""Approval tokens must be unforgeable, unreplayable, and short-lived."""

from __future__ import annotations

import unittest
from datetime import timedelta

from stormbot.governance import ApprovalTokenIssuer, InvalidApprovalToken
from tests.support import BUSINESS_HOURS

TARGET = "b" * 64
OTHER_TARGET = "c" * 64
ACTION = "outreach.send_sms"


class ApprovalTokenTests(unittest.TestCase):
    def setUp(self):
        self.issuer = ApprovalTokenIssuer(secret=b"approval-secret-for-tests-only")

    def issue(self, **overrides) -> str:
        fields = {
            "action_type": ACTION,
            "target_digest": TARGET,
            "approver": "brian",
            "now": BUSINESS_HOURS,
        }
        fields.update(overrides)
        return self.issuer.issue(**fields)

    def test_a_valid_token_round_trips_with_its_approver(self):
        token = self.issuer.verify(self.issue(), action_type=ACTION, target_digest=TARGET, now=BUSINESS_HOURS)

        self.assertEqual(token.approver, "brian")
        self.assertEqual(token.action_type, ACTION)

    def test_a_token_signed_by_a_different_secret_is_rejected(self):
        forged = ApprovalTokenIssuer(secret=b"a-different-secret-entirely!!").issue(
            action_type=ACTION, target_digest=TARGET, approver="attacker", now=BUSINESS_HOURS
        )

        with self.assertRaises(InvalidApprovalToken):
            self.issuer.verify(forged, action_type=ACTION, target_digest=TARGET, now=BUSINESS_HOURS)

    def test_tampering_with_the_payload_invalidates_the_signature(self):
        payload, _, signature = self.issue().partition(".")
        tampered = f"{payload[:-1]}X.{signature}"

        with self.assertRaises(InvalidApprovalToken):
            self.issuer.verify(tampered, action_type=ACTION, target_digest=TARGET, now=BUSINESS_HOURS)

    def test_a_token_cannot_be_replayed_against_another_recipient(self):
        with self.assertRaises(InvalidApprovalToken) as raised:
            self.issuer.verify(
                self.issue(), action_type=ACTION, target_digest=OTHER_TARGET, now=BUSINESS_HOURS
            )

        self.assertIn("different target", str(raised.exception))

    def test_a_token_cannot_be_reused_for_a_different_action_type(self):
        with self.assertRaises(InvalidApprovalToken) as raised:
            self.issuer.verify(
                self.issue(),
                action_type="outreach.send_email",
                target_digest=TARGET,
                now=BUSINESS_HOURS,
            )

        self.assertIn("different action type", str(raised.exception))

    def test_a_token_expires(self):
        token = self.issue(ttl=timedelta(minutes=15))

        with self.assertRaises(InvalidApprovalToken) as raised:
            self.issuer.verify(
                token,
                action_type=ACTION,
                target_digest=TARGET,
                now=BUSINESS_HOURS + timedelta(minutes=16),
            )

        self.assertIn("expired", str(raised.exception))

    def test_a_token_is_still_valid_one_second_before_expiry(self):
        token = self.issue(ttl=timedelta(minutes=15))

        verified = self.issuer.verify(
            token,
            action_type=ACTION,
            target_digest=TARGET,
            now=BUSINESS_HOURS + timedelta(minutes=14, seconds=59),
        )

        self.assertEqual(verified.approver, "brian")

    def test_malformed_tokens_are_rejected_without_raising_anything_else(self):
        for candidate in ("", "not-a-token", "onlypayload", "a.b", "....."):
            with self.subTest(candidate=candidate), self.assertRaises(InvalidApprovalToken):
                self.issuer.verify(candidate, action_type=ACTION, target_digest=TARGET, now=BUSINESS_HOURS)

    def test_a_short_secret_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            ApprovalTokenIssuer(secret=b"tooshort")


if __name__ == "__main__":
    unittest.main()

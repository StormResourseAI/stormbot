"""Redaction tests, written as negative assertions.

The useful shape here is "this string does not appear in the output", not "the
output equals this". A test that pins the exact redacted string passes happily
when a new detector is added and the old one silently stops firing; a test that
asserts absence keeps working.

The literals below are syntactically valid credential shapes with obviously fake
bodies. They are the reason this file matches credential scanners, and that is
intended — a redaction test with no key-shaped input tests nothing.
"""

from __future__ import annotations

import unittest

from stormbot.governance import Redactor

FAKE_STRIPE_KEY = "sk_live_" + "0123456789abcdefghij"
FAKE_GITHUB_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_BEARER = "Bearer " + "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9fake"
FAKE_TWILIO_SID = "AC" + "0" * 32


class SecretDetectionTests(unittest.TestCase):
    def setUp(self):
        self.redactor = Redactor()

    def test_known_credential_shapes_are_detected(self):
        for label, sample in (
            ("stripe", FAKE_STRIPE_KEY),
            ("github", FAKE_GITHUB_TOKEN),
            ("aws", FAKE_AWS_KEY),
            ("bearer", FAKE_BEARER),
            ("twilio", FAKE_TWILIO_SID),
        ):
            with self.subTest(label=label):
                self.assertTrue(self.redactor.contains_secret(f"debug output: {sample}"))

    def test_redaction_removes_the_secret_body(self):
        text = f"authorization={FAKE_BEARER} and stripe={FAKE_STRIPE_KEY}"

        redacted = self.redactor.redact(text)

        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9fake", redacted)
        self.assertNotIn("0123456789abcdefghij", redacted)
        self.assertIn("<REDACTED>", redacted)

    def test_findings_never_carry_the_matched_value(self):
        """Findings end up in CI logs. A finding that echoes its match is a leak."""
        findings = self.redactor.scan(f"token={FAKE_GITHUB_TOKEN}")

        self.assertTrue(findings)
        serialized = repr(findings)
        self.assertNotIn("A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", serialized)

    def test_ordinary_prose_is_not_flagged(self):
        text = "Following up on the estimate we discussed on Tuesday afternoon."

        self.assertFalse(self.redactor.contains_secret(text))
        self.assertEqual(self.redactor.redact(text), text)

    def test_summary_reports_counts_without_values(self):
        summary = self.redactor.summarize(f"{FAKE_STRIPE_KEY} {FAKE_STRIPE_KEY}")

        self.assertEqual(summary, {"stripe_live_key": 2})


class PersonalDataTests(unittest.TestCase):
    def setUp(self):
        self.redactor = Redactor()

    def test_contact_details_are_redacted_from_loggable_text(self):
        text = "Reached Dana at dana.reyes@example.com / (813) 555-0142, 4102 Bayshore Blvd."

        redacted = self.redactor.redact(text)

        self.assertNotIn("dana.reyes@example.com", redacted)
        self.assertNotIn("555-0142", redacted)
        self.assertNotIn("4102 Bayshore Blvd", redacted)

    def test_personal_data_alone_is_not_treated_as_a_secret(self):
        """PII is redacted from logs, but it does not block an outbound send.

        A message to a prospect legitimately contains their phone number.
        Conflating the two controls would block the product's core action.
        """
        text = "Calling you back at (813) 555-0142."

        self.assertFalse(self.redactor.contains_secret(text))
        self.assertNotIn("555-0142", self.redactor.redact(text))

    def test_a_secret_containing_a_phone_shaped_substring_is_removed_whole(self):
        secret = "sk_live_" + "813555014212345678"

        redacted = Redactor().redact(f"key={secret}")

        self.assertNotIn("813555014212345678", redacted)


if __name__ == "__main__":
    unittest.main()

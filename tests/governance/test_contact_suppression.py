"""Suppression has to survive reformatting, and must not become a lead list."""

from __future__ import annotations

import unittest

from stormbot.governance import SuppressionRegistry
from stormbot.governance.suppression import normalize_contact

KEY = b"suppression-key-for-tests-only"
RAW_VARIANTS = ("+18135550142", "18135550142", "(813) 555-0142", "813-555-0142", "813.555.0142")


class NormalizationTests(unittest.TestCase):
    def test_every_common_phone_format_normalizes_to_one_key(self):
        keys = {normalize_contact(variant) for variant in RAW_VARIANTS}

        self.assertEqual(keys, {"tel:+18135550142"})

    def test_email_case_is_normalized_but_the_local_part_is_preserved(self):
        self.assertEqual(normalize_contact("Dana.Reyes@Example.COM"), "email:dana.reyes@example.com")

    def test_empty_and_unrecognizable_identifiers_raise(self):
        for candidate in ("", "   ", "not-a-contact"):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                normalize_contact(candidate)


class SuppressionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = SuppressionRegistry(key=KEY)

    def test_opt_out_applies_to_every_format_of_the_same_number(self):
        self.registry.suppress("(813) 555-0142", reason="opt_out", source="sms_stop_keyword")

        for variant in RAW_VARIANTS:
            with self.subTest(variant=variant):
                self.assertTrue(self.registry.is_suppressed(variant))

    def test_an_unrelated_number_is_not_suppressed(self):
        self.registry.suppress("+18135550142", reason="opt_out", source="sms_stop_keyword")

        self.assertFalse(self.registry.is_suppressed("+18135550199"))

    def test_an_identifier_that_cannot_be_normalized_is_treated_as_suppressed(self):
        """Fail closed: an identifier we cannot check is one we cannot clear."""
        self.assertTrue(self.registry.is_suppressed("garbage input"))

    def test_export_contains_no_raw_contact_data(self):
        self.registry.suppress("+18135550142", reason="complaint", source="operator")
        self.registry.suppress("dana.reyes@example.com", reason="opt_out", source="unsubscribe_link")

        serialized = repr(self.registry.export())

        self.assertNotIn("8135550142", serialized)
        self.assertNotIn("555-0142", serialized)
        self.assertNotIn("dana.reyes", serialized)
        self.assertNotIn("example.com", serialized)

    def test_export_still_carries_the_operational_fields(self):
        self.registry.suppress("+18135550142", reason="litigation_hold", source="counsel")

        row = self.registry.export()[0]

        self.assertEqual(row["reason"], "litigation_hold")
        self.assertEqual(row["source"], "counsel")
        self.assertEqual(len(row["digest"]), 64)

    def test_digests_are_key_dependent(self):
        """An unkeyed hash of a 10-digit number is reversible in seconds."""
        other = SuppressionRegistry(key=b"a-completely-different-key!!!")

        self.assertNotEqual(self.registry.digest_for("+18135550142"), other.digest_for("+18135550142"))

    def test_an_unknown_reason_code_is_refused(self):
        with self.assertRaises(ValueError):
            self.registry.suppress("+18135550142", reason="felt_like_it", source="operator")

    def test_an_empty_key_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            SuppressionRegistry(key=b"")


if __name__ == "__main__":
    unittest.main()

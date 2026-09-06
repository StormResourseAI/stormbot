"""Contract tests on the committed registries themselves.

These catch the class of mistake the schema cannot: an evidence record pointing
at a file that was renamed, or a capability whose id drifted away from the
module that implements it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from stormbot.assurance import load_bundle
from stormbot.assurance.registry import default_registry_root

REGISTRY_ROOT = default_registry_root(Path(__file__))
REPO_ROOT = REGISTRY_ROOT.parent


class RegistryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle(REGISTRY_ROOT)

    def test_the_committed_registries_validate(self):
        self.assertEqual(self.bundle.schema_errors, [])

    def test_every_evidence_artifact_actually_exists_in_the_repository(self):
        """An evidence pointer into a deleted file is worse than no pointer."""
        missing = [
            record.artifact_uri
            for record in self.bundle.ledger.records()
            if record.artifact_uri and not (REPO_ROOT / record.artifact_uri).exists()
        ]

        self.assertEqual(missing, [])

    def test_every_capability_carries_evidence(self):
        without_evidence = sorted(set(self.bundle.capabilities) - set(self.bundle.ledger.subjects()))

        self.assertEqual(without_evidence, [])

    def test_no_evidence_record_describes_an_unregistered_capability(self):
        orphaned = sorted(set(self.bundle.ledger.subjects()) - set(self.bundle.capabilities))

        self.assertEqual(orphaned, [])

    def test_high_risk_capabilities_require_a_human(self):
        exceptions = {
            # Suppression and redaction are refusals, not actions. Requiring an
            # operator to approve a refusal would invert the safety property.
            "governance.contact_suppression",
        }
        violations = [
            capability.id
            for capability in self.bundle.capabilities.values()
            if capability.risk_tier == "high"
            and not capability.requires_human
            and capability.id not in exceptions
        ]

        self.assertEqual(violations, [])

    def test_every_customer_facing_claim_is_written_in_plain_language(self):
        """Claims are read by customers, so they must not name internal modules."""
        jargon = ("src/", ".py", "class ", "def ", "HMAC", "SHA-256")
        violations = [
            claim.id
            for claim in self.bundle.claims.values()
            if claim.customer_facing and any(term in claim.statement for term in jargon)
        ]

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

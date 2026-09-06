"""The ladder must be unclimbable without evidence for every rung below."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from stormbot.assurance import (
    EvidenceKind,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceState,
    UnprovenClaimError,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
SUBJECT = "governance.execution_governor"
SHA = "9f1c2ab"


def record(kind: EvidenceKind, *, at: datetime = NOW, sha: str | None = None, subject: str = SUBJECT):
    return EvidenceRecord(
        id=f"ev.{subject.split('.')[-1]}.{kind.value.lower()}",
        kind=kind,
        subject=subject,
        recorded_at=at,
        detail=f"{kind.value} evidence recorded for the test suite.",
        commit_sha=sha,
    )


class LadderTests(unittest.TestCase):
    def test_no_evidence_means_unknown_not_planned_or_built(self):
        self.assertIs(EvidenceLedger().state_of(SUBJECT, now=NOW), EvidenceState.UNKNOWN)

    def test_each_rung_requires_its_own_evidence_kind(self):
        ledger = EvidenceLedger()

        ledger.record(record(EvidenceKind.SOURCE_TREE))
        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.BUILT)

        ledger.record(record(EvidenceKind.INTEGRATION_RUN))
        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.INTEGRATED)

        ledger.record(record(EvidenceKind.TEST_RUN))
        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.TESTED)

    def test_the_ladder_is_contiguous_so_a_gap_caps_the_state(self):
        """Certification evidence with no test evidence proves nothing above BUILT."""
        ledger = EvidenceLedger()
        ledger.record(record(EvidenceKind.SOURCE_TREE))
        ledger.record(record(EvidenceKind.CERTIFICATION, sha=SHA))
        ledger.record(record(EvidenceKind.DEPLOYMENT, sha=SHA))

        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.BUILT)

    def test_a_full_chain_reaches_active(self):
        ledger = EvidenceLedger()
        for kind in EvidenceKind:
            sha = SHA if kind.name in {"CERTIFICATION", "DEPLOYMENT", "RUNTIME_PROBE"} else None
            ledger.record(record(kind, sha=sha))

        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.ACTIVE)

    def test_states_off_the_ladder_never_satisfy_a_comparison(self):
        self.assertFalse(EvidenceState.BLOCKED.at_least(EvidenceState.BUILT))
        self.assertFalse(EvidenceState.TESTED.at_least(EvidenceState.UNKNOWN))
        self.assertTrue(EvidenceState.CERTIFIED.at_least(EvidenceState.TESTED))


class FreshnessTests(unittest.TestCase):
    def test_runtime_evidence_expires_because_it_is_a_present_tense_claim(self):
        ledger = EvidenceLedger()
        yesterday = NOW - timedelta(days=2)
        for kind in EvidenceKind:
            sha = SHA if kind.name in {"CERTIFICATION", "DEPLOYMENT", "RUNTIME_PROBE"} else None
            at = yesterday if kind is EvidenceKind.RUNTIME_PROBE else NOW
            ledger.record(record(kind, at=at, sha=sha))

        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.DEPLOYED)

    def test_source_evidence_does_not_expire_on_a_clock(self):
        ledger = EvidenceLedger()
        long_ago = NOW - timedelta(days=900)
        ledger.record(record(EvidenceKind.SOURCE_TREE, at=long_ago))
        ledger.record(record(EvidenceKind.INTEGRATION_RUN, at=long_ago))
        ledger.record(record(EvidenceKind.TEST_RUN, at=long_ago))

        self.assertIs(ledger.state_of(SUBJECT, now=NOW), EvidenceState.TESTED)


class RecordIntegrityTests(unittest.TestCase):
    def test_build_specific_evidence_must_name_an_exact_sha(self):
        for kind in (EvidenceKind.CERTIFICATION, EvidenceKind.DEPLOYMENT, EvidenceKind.RUNTIME_PROBE):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                record(kind, sha=None)

    def test_naive_timestamps_are_refused(self):
        with self.assertRaises(ValueError):
            EvidenceRecord(
                id="ev.subject.source_tree",
                kind=EvidenceKind.SOURCE_TREE,
                subject=SUBJECT,
                recorded_at=datetime(2026, 9, 6, 12, 0),
                detail="A timestamp with no timezone is not a point in time.",
            )

    def test_reusing_an_evidence_id_for_different_content_is_refused(self):
        ledger = EvidenceLedger()
        ledger.record(record(EvidenceKind.SOURCE_TREE))

        conflicting = EvidenceRecord(
            id="ev.execution_governor.source_tree",
            kind=EvidenceKind.SOURCE_TREE,
            subject=SUBJECT,
            recorded_at=NOW,
            detail="A different detail under the same identifier.",
        )

        with self.assertRaises(ValueError):
            ledger.record(conflicting)

    def test_recording_the_identical_record_twice_is_idempotent(self):
        ledger = EvidenceLedger()
        ledger.record(record(EvidenceKind.SOURCE_TREE))
        ledger.record(record(EvidenceKind.SOURCE_TREE))

        self.assertEqual(len(ledger), 1)


class AssertionTests(unittest.TestCase):
    def test_asserting_an_unproven_state_raises_and_names_the_actual_state(self):
        ledger = EvidenceLedger()
        ledger.record(record(EvidenceKind.SOURCE_TREE))

        with self.assertRaises(UnprovenClaimError) as raised:
            ledger.assert_state(SUBJECT, EvidenceState.ACTIVE)

        self.assertIn("BUILT", str(raised.exception))

    def test_asserting_a_proven_state_is_silent(self):
        ledger = EvidenceLedger()
        ledger.record(record(EvidenceKind.SOURCE_TREE))

        ledger.assert_state(SUBJECT, EvidenceState.BUILT, now=NOW)


if __name__ == "__main__":
    unittest.main()

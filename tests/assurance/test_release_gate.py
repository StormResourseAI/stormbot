"""The gate is only worth having if it fails when it should.

Most of these tests deliberately corrupt a copy of the committed registries and
assert the gate catches it. Testing only the happy path on a gate is close to
testing nothing: a gate that returns "pass" unconditionally would pass it.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stormbot.assurance import load_bundle
from stormbot.assurance.registry import RegistryLoadError, default_registry_root
from stormbot.assurance.release_gate import (
    EXIT_EXECUTION_ERROR,
    EXIT_FAIL,
    EXIT_PASS,
    POLICIES,
    CheckStatus,
    Verdict,
    evaluate,
    main,
    render,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
REGISTRY_ROOT = default_registry_root(Path(__file__))


@contextlib.contextmanager
def quiet():
    """Keep CLI output out of the test report without hiding failures."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class TemporaryRegistry:
    """A writable copy of the committed registries, for corruption tests."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "assurance"
        shutil.copytree(REGISTRY_ROOT, self.root)

    def edit(self, filename: str, mutate) -> None:
        path = self.root / filename
        document = json.loads(path.read_text(encoding="utf-8"))
        mutate(document)
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    def __enter__(self) -> TemporaryRegistry:
        return self

    def __exit__(self, *exc_info) -> None:
        self._tmp.cleanup()


class CommittedRegistryTests(unittest.TestCase):
    """The registries in this repository must actually satisfy the gate."""

    def test_deployment_policy_passes_on_the_committed_registries(self):
        report = evaluate(load_bundle(REGISTRY_ROOT), policy=POLICIES["deployment"], now=NOW)

        self.assertIs(report.verdict, Verdict.PASS)
        self.assertEqual(report.exit_code, EXIT_PASS)

    def test_certification_policy_fails_and_that_is_the_honest_answer(self):
        """Nothing here is certified: certification needs evidence bound to a SHA."""
        report = evaluate(load_bundle(REGISTRY_ROOT), policy=POLICIES["certification"], now=NOW)

        self.assertIs(report.verdict, Verdict.FAIL)
        failed = [check.id for check in report.checks if check.status is CheckStatus.FAIL]
        self.assertEqual(failed, ["customer-facing-floor"])

    def test_advisory_policy_never_blocks(self):
        report = evaluate(load_bundle(REGISTRY_ROOT), policy=POLICIES["advisory"], now=NOW)

        self.assertNotEqual(report.verdict, Verdict.FAIL)


class DetectionTests(unittest.TestCase):
    def gate(self, registry: TemporaryRegistry, policy: str = "deployment", now: datetime = NOW):
        return evaluate(load_bundle(registry.root), policy=POLICIES[policy], now=now)

    def assert_fails(self, report, check_id: str) -> None:
        failed = [check.id for check in report.checks if check.status is CheckStatus.FAIL]
        self.assertIn(check_id, failed)
        self.assertIs(report.verdict, Verdict.FAIL)

    def test_a_claim_referencing_a_missing_capability_fails(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "product_claims.json",
                lambda doc: doc["claims"][0]["capability_refs"].append("governance.does_not_exist"),
            )

            self.assert_fails(self.gate(registry), "capability-refs-resolve")

    def test_a_claim_referencing_missing_evidence_fails(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "product_claims.json",
                lambda doc: doc["claims"][0]["evidence_refs"].append("ev.nothing.here"),
            )

            self.assert_fails(self.gate(registry), "evidence-refs-resolve")

    def test_a_claim_demanding_more_than_the_ledger_proves_fails(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "product_claims.json",
                lambda doc: doc["claims"][0].update({"required_state": "ACTIVE"}),
            )

            self.assert_fails(self.gate(registry), "claim-evidence-sufficiency")

    def test_a_capability_declaring_more_than_its_evidence_fails(self):
        """The registry cannot promote itself; only the ledger promotes."""
        with TemporaryRegistry() as registry:
            registry.edit(
                "ai_capabilities.json",
                lambda doc: doc["capabilities"][0].update({"evidence_state": "ACTIVE"}),
            )

            self.assert_fails(self.gate(registry), "declared-state-honesty")

    def test_removing_test_evidence_drops_the_state_and_fails_the_claim(self):
        def drop_test_runs(document):
            document["records"] = [r for r in document["records"] if r["kind"] != "TEST_RUN"]

        with TemporaryRegistry() as registry:
            registry.edit("evidence/baseline-2026-09-06.json", drop_test_runs)

            report = self.gate(registry)

            self.assert_fails(report, "claim-evidence-sufficiency")
            self.assert_fails(report, "customer-facing-floor")

    def test_a_human_in_the_loop_capability_without_an_approval_gate_fails(self):
        def strip_gate(document):
            document["capabilities"][0].pop("approval_gate", None)

        with TemporaryRegistry() as registry:
            registry.edit("ai_capabilities.json", strip_gate)

            self.assert_fails(self.gate(registry), "hitl-approval-gate")

    def test_a_blocked_capability_under_an_active_claim_fails(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "ai_capabilities.json",
                lambda doc: doc["capabilities"][0].update({"evidence_state": "BLOCKED"}),
            )

            self.assert_fails(self.gate(registry), "no-blocked-capabilities")

    def test_a_schema_violation_fails_the_gate_rather_than_crashing_it(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "ai_capabilities.json",
                lambda doc: doc["capabilities"][0].update({"risk_tier": "catastrophic"}),
            )

            self.assert_fails(self.gate(registry), "registry-schema")

    def test_a_retired_claim_is_not_enforced(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "product_claims.json",
                lambda doc: doc["claims"][0].update({"status": "retired", "required_state": "ACTIVE"}),
            )

            report = self.gate(registry)

            self.assertNotIn(
                "claim-evidence-sufficiency",
                [c.id for c in report.checks if c.status is CheckStatus.FAIL],
            )


class AdvisoryTests(unittest.TestCase):
    def test_a_stale_review_warns_but_does_not_block(self):
        report = evaluate(
            load_bundle(REGISTRY_ROOT),
            policy=POLICIES["deployment"],
            now=NOW + timedelta(days=400),
        )

        self.assertIs(report.verdict, Verdict.WARN)
        warned = [check.id for check in report.checks if check.status is CheckStatus.WARN]
        self.assertEqual(warned, ["review-recency"])

    def test_advisory_policy_downgrades_blocking_findings_to_warnings(self):
        with TemporaryRegistry() as registry:
            registry.edit(
                "product_claims.json",
                lambda doc: doc["claims"][0]["capability_refs"].append("governance.does_not_exist"),
            )

            report = evaluate(load_bundle(registry.root), policy=POLICIES["advisory"], now=NOW)

            self.assertIs(report.verdict, Verdict.WARN)


class ReportAndCliTests(unittest.TestCase):
    def test_the_json_report_matches_the_published_schema(self):
        from stormbot.assurance.schema import validate

        report = evaluate(load_bundle(REGISTRY_ROOT), policy=POLICIES["deployment"], now=NOW)
        schema = json.loads(
            (REGISTRY_ROOT / "schemas" / "release_gate.schema.json").read_text(encoding="utf-8")
        )

        self.assertEqual(validate(report.to_dict(), schema), [])

    def test_every_render_format_produces_output(self):
        report = evaluate(load_bundle(REGISTRY_ROOT), policy=POLICIES["deployment"], now=NOW)

        for fmt in ("text", "markdown", "json"):
            with self.subTest(fmt=fmt):
                self.assertIn("deployment", render(report, fmt))

    def test_cli_exit_codes_distinguish_a_verdict_from_a_broken_run(self):
        """Exit 3 must never be readable as a policy answer."""
        with tempfile.TemporaryDirectory() as tmp, quiet():
            output = Path(tmp) / "artifacts" / "gate.json"
            passing = main(
                [
                    "--registry-root",
                    str(REGISTRY_ROOT),
                    "--policy",
                    "deployment",
                    "--now",
                    NOW.isoformat(),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(passing, EXIT_PASS)
            self.assertTrue(output.is_file())

            failing = main(
                [
                    "--registry-root",
                    str(REGISTRY_ROOT),
                    "--policy",
                    "certification",
                    "--now",
                    NOW.isoformat(),
                ]
            )
            self.assertEqual(failing, EXIT_FAIL)

            broken = main(["--registry-root", str(Path(tmp) / "nowhere")])
            self.assertEqual(broken, EXIT_EXECUTION_ERROR)

    def test_a_missing_registry_raises_a_load_error_rather_than_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RegistryLoadError):
            load_bundle(Path(tmp))


if __name__ == "__main__":
    unittest.main()

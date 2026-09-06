"""Merge policy: a gate verdict, read in the context of what changed."""

from __future__ import annotations

import unittest

from stormbot.assurance.ci_policy import classify, decide


def report(verdict: str, *warn: str, fail: tuple[str, ...] = ()) -> dict:
    checks = [{"id": check_id, "status": "warn"} for check_id in warn]
    checks += [{"id": check_id, "status": "fail"} for check_id in fail]
    checks.append({"id": "registry-schema", "status": "pass"})
    return {"verdict": verdict, "checks": checks}


class ClassificationTests(unittest.TestCase):
    def test_paths_are_sorted_into_governed_test_and_documentation(self):
        changes = classify(
            [
                "src/stormbot/governance/governor.py",
                "assurance/product_claims.json",
                "tests/governance/test_execution_governor.py",
                "docs/architecture/ARCHITECTURE.md",
                "README.md",
                "pyproject.toml",
            ]
        )

        self.assertEqual(len(changes.governed), 2)
        self.assertEqual(len(changes.tests), 1)
        self.assertEqual(len(changes.documentation), 2)
        self.assertEqual(changes.other, ("pyproject.toml",))

    def test_a_test_file_under_a_governed_name_still_counts_as_a_test(self):
        """Otherwise adding a test for governance code would block itself."""
        changes = classify(["tests/governance/test_execution_governor.py"])

        self.assertFalse(changes.governed)
        self.assertTrue(changes.tests)

    def test_blank_lines_from_a_changed_files_file_are_ignored(self):
        self.assertTrue(classify(["", "  ", "README.md"]).documentation_only)


class DecisionTests(unittest.TestCase):
    def test_a_failing_gate_blocks_everything(self):
        decision = decide(report("fail", fail=("claim-evidence-sufficiency",)), classify(["README.md"]))

        self.assertFalse(decision.allowed)
        self.assertIn("claim-evidence-sufficiency", decision.reasons[0])

    def test_advisory_findings_are_tolerated_on_a_documentation_change(self):
        decision = decide(report("warn", "review-recency"), classify(["docs/RUNBOOK.md"]))

        self.assertTrue(decision.allowed)
        self.assertTrue(any("tolerated" in note for note in decision.notes))

    def test_advisory_findings_escalate_when_governed_surface_changes(self):
        decision = decide(
            report("warn", "review-recency"),
            classify(["assurance/product_claims.json", "tests/assurance/test_release_gate.py"]),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("review-recency", decision.reasons[0])

    def test_governed_change_without_a_test_change_blocks_on_a_passing_gate(self):
        """A green gate is not permission to edit safety code untested."""
        decision = decide(report("pass"), classify(["src/stormbot/governance/governor.py"]))

        self.assertFalse(decision.allowed)
        self.assertIn("no accompanying test change", decision.reasons[0])

    def test_governed_change_with_a_test_change_is_allowed(self):
        decision = decide(
            report("pass"),
            classify(
                [
                    "src/stormbot/governance/governor.py",
                    "tests/governance/test_execution_governor.py",
                ]
            ),
        )

        self.assertTrue(decision.allowed)

    def test_a_report_with_no_verdict_field_is_treated_as_a_failure(self):
        decision = decide({}, classify(["README.md"]))

        self.assertFalse(decision.allowed)

    def test_an_empty_change_set_falls_back_to_the_gate_verdict(self):
        allowed = decide(report("pass"), classify([]))
        blocked = decide(report("fail", fail=("registry-schema",)), classify([]))

        self.assertTrue(allowed.allowed)
        self.assertFalse(blocked.allowed)

    def test_the_summary_names_the_verdict_and_every_blocking_reason(self):
        decision = decide(report("pass"), classify(["src/stormbot/governance/governor.py"]))

        markdown = decision.to_markdown("pass")

        self.assertIn("blocked", markdown)
        self.assertIn("governor.py", markdown)


if __name__ == "__main__":
    unittest.main()

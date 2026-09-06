"""End-to-end: registries on disk, through the gate, into a merge decision.

This is the pipeline CI actually runs, exercised in-process against the
committed registries. If the workflow and this test ever disagree, one of them
is wrong, and this one is cheaper to find out about.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from stormbot.assurance.ci_policy import EXIT_ALLOW, EXIT_BLOCK
from stormbot.assurance.ci_policy import main as ci_policy_main
from stormbot.assurance.registry import default_registry_root
from stormbot.assurance.release_gate import EXIT_FAIL, EXIT_PASS
from stormbot.assurance.release_gate import main as gate_main
from stormbot.assurance.schema import validate

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
REGISTRY_ROOT = default_registry_root(Path(__file__))


@contextlib.contextmanager
def quiet():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class ReleasePipelineTests(unittest.TestCase):
    def run_gate(self, workspace: Path, policy: str = "deployment") -> tuple[int, Path]:
        output = workspace / "artifacts" / "release-gate.json"
        with quiet():
            code = gate_main(
                [
                    "--registry-root",
                    str(REGISTRY_ROOT),
                    "--policy",
                    policy,
                    "--target",
                    "HEAD",
                    "--compare-to",
                    "origin/main",
                    "--now",
                    NOW.isoformat(),
                    "--format",
                    "text",
                    "--output",
                    str(output),
                    "--markdown-output",
                    str(output.with_suffix(".md")),
                ]
            )
        return code, output

    def run_policy(self, report: Path, changed: list[str], workspace: Path) -> int:
        changed_files = workspace / "changed-files.txt"
        changed_files.write_text("\n".join(changed), encoding="utf-8")
        with quiet():
            return ci_policy_main(
                [
                    str(report),
                    "--changed-files-from",
                    str(changed_files),
                    "--summary-output",
                    str(workspace / "summary.md"),
                ]
            )

    def test_the_deployment_pipeline_passes_and_leaves_auditable_artifacts(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            code, report = self.run_gate(workspace)

            self.assertEqual(code, EXIT_PASS)
            self.assertTrue(report.is_file())
            self.assertTrue(report.with_suffix(".md").is_file())

            decision = self.run_policy(
                report,
                ["docs/architecture/ARCHITECTURE.md", "README.md"],
                workspace,
            )

            self.assertEqual(decision, EXIT_ALLOW)
            self.assertIn("allowed", (workspace / "summary.md").read_text(encoding="utf-8"))

    def test_the_published_artifact_conforms_to_its_own_schema(self):
        """The artifact is the audit trail; an unparseable one is no trail at all."""
        with TemporaryDirectory() as tmp:
            _, report = self.run_gate(Path(tmp))

            document = json.loads(report.read_text(encoding="utf-8"))
            schema = json.loads(
                (REGISTRY_ROOT / "schemas" / "release_gate.schema.json").read_text(encoding="utf-8")
            )

            self.assertEqual(validate(document, schema), [])
            self.assertEqual(document["compare_to"], "origin/main")

    def test_a_governed_change_without_tests_is_blocked_on_a_passing_gate(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            code, report = self.run_gate(workspace)
            self.assertEqual(code, EXIT_PASS)

            decision = self.run_policy(report, ["src/stormbot/governance/governor.py"], workspace)

            self.assertEqual(decision, EXIT_BLOCK)

    def test_a_failing_gate_blocks_the_merge_decision_too(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)

            code, report = self.run_gate(workspace, policy="certification")

            self.assertEqual(code, EXIT_FAIL)
            self.assertEqual(self.run_policy(report, ["README.md"], workspace), EXIT_BLOCK)

    def test_the_gate_writes_nothing_outside_the_directory_it_was_given(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.run_gate(workspace)

            written = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file())

            self.assertEqual(written, ["artifacts/release-gate.json", "artifacts/release-gate.md"])


if __name__ == "__main__":
    unittest.main()

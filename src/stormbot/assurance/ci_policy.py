"""Turns a release-gate verdict plus a changed-file set into a CI decision.

The gate answers "is the claim registry consistent with the evidence?". That is
not quite the same question as "should this pull request be allowed to merge?",
and conflating them produces a gate that is either too loud on a typo fix or too
quiet on a change to the code that decides whether to text a stranger.

So the two stay separate. This module applies change-scoped rules on top of the
verdict:

- A failing gate blocks, always.
- Advisory findings block only when the change touches governed surface.
- A change to safety-critical code with no accompanying test change blocks,
  regardless of the gate verdict.

Exit codes are 0 (allow) and 1 (block). A gate report that cannot be read exits
2, because "I could not evaluate the policy" is not "the policy passed".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = ["PolicyDecision", "classify", "decide", "main"]

EXIT_ALLOW = 0
EXIT_BLOCK = 1
EXIT_EXECUTION_ERROR = 2

#: Paths where a mistake has real-world consequences.
GOVERNED_PREFIXES = (
    "src/stormbot/governance/",
    "src/stormbot/assurance/",
    "assurance/",
    ".github/workflows/",
)

#: Paths whose changes cannot alter runtime behaviour.
DOCUMENTATION_PREFIXES = ("docs/", "examples/")
DOCUMENTATION_SUFFIXES = (".md", ".rst", ".txt")

TEST_PREFIXES = ("tests/",)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def exit_code(self) -> int:
        return EXIT_ALLOW if self.allowed else EXIT_BLOCK

    def to_markdown(self, verdict: str) -> str:
        heading = "allowed" if self.allowed else "blocked"
        lines = [
            f"## CI policy: **{heading}**",
            "",
            f"- Release-gate verdict: `{verdict}`",
        ]
        if self.reasons:
            lines += ["", "### Blocking reasons", ""]
            lines += [f"- {reason}" for reason in self.reasons]
        if self.notes:
            lines += ["", "### Notes", ""]
            lines += [f"- {note}" for note in self.notes]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ChangeSet:
    governed: tuple[str, ...]
    tests: tuple[str, ...]
    documentation: tuple[str, ...]
    other: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not (self.governed or self.tests or self.documentation or self.other)

    @property
    def documentation_only(self) -> bool:
        return bool(self.documentation) and not (self.governed or self.tests or self.other)


def classify(changed_files: Iterable[str]) -> ChangeSet:
    governed: list[str] = []
    tests: list[str] = []
    documentation: list[str] = []
    other: list[str] = []

    for raw in changed_files:
        path = raw.strip()
        if not path:
            continue
        if path.startswith(TEST_PREFIXES):
            tests.append(path)
        elif path.startswith(GOVERNED_PREFIXES):
            governed.append(path)
        elif path.startswith(DOCUMENTATION_PREFIXES) or path.endswith(DOCUMENTATION_SUFFIXES):
            documentation.append(path)
        else:
            other.append(path)

    return ChangeSet(tuple(governed), tuple(tests), tuple(documentation), tuple(other))


def decide(report: dict, changes: ChangeSet) -> PolicyDecision:
    verdict = str(report.get("verdict", "fail"))
    reasons: list[str] = []
    notes: list[str] = []

    if verdict == "fail":
        failed = [c["id"] for c in report.get("checks", []) if c.get("status") == "fail"]
        reasons.append(f"release gate failed: {', '.join(failed) or 'unspecified check'}")
    elif verdict == "warn":
        warned = [c["id"] for c in report.get("checks", []) if c.get("status") == "warn"]
        if changes.governed:
            reasons.append(
                f"advisory findings ({', '.join(warned)}) are blocking because this change "
                f"touches governed surface: {', '.join(changes.governed[:5])}"
            )
        else:
            notes.append(f"advisory findings tolerated on a non-governed change: {', '.join(warned)}")

    if changes.governed and not changes.tests:
        reasons.append(
            "governed surface changed with no accompanying test change: " + ", ".join(changes.governed[:5])
        )

    if changes.documentation_only:
        notes.append("documentation-only change; runtime behaviour is unaffected")
    if changes.empty:
        notes.append("no changed files supplied; gate verdict applied on its own")

    return PolicyDecision(allowed=not reasons, reasons=tuple(reasons), notes=tuple(notes))


def _read_changed_files(path: Path | None, inline: Sequence[str]) -> list[str]:
    files = list(inline)
    if path is not None:
        if not path.is_file():
            raise FileNotFoundError(f"changed-files list not found: {path}")
        files += path.read_text(encoding="utf-8").splitlines()
    return files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stormbot.assurance.ci_policy",
        description="Apply change-scoped CI policy to a release-gate report.",
    )
    parser.add_argument("report", type=Path, help="path to the release-gate JSON report")
    parser.add_argument("--changed-files-from", type=Path, default=None)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--summary-output", type=Path, default=None, help="write the Markdown summary here")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        changed_files = _read_changed_files(args.changed_files_from, args.changed_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ci policy could not run: {exc}", file=sys.stderr)
        return EXIT_EXECUTION_ERROR

    decision = decide(report, classify(changed_files))
    summary = decision.to_markdown(str(report.get("verdict", "unknown")))
    sys.stdout.write(summary)

    if args.summary_output:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(summary, encoding="utf-8")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)

    return decision.exit_code


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())

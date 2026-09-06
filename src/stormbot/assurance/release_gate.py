"""The release gate: machine-checkable product claims.

The premise is narrow and, once stated, hard to argue with. If the product page
says "an operator approves every outbound message before it sends", that
sentence is a testable assertion about the system. It should not be possible to
ship a build where the sentence is false and CI is green.

So every customer-facing claim is a registry entry that names the capabilities
it depends on and the evidence that backs it. This gate refuses the release when
a claim outruns its evidence.

Exit codes are part of the contract:

===== ==========================================================
  0    pass — no violations
  1    warn — advisory findings only
  2    fail — at least one blocking violation
 >2    the gate itself failed to run; this is not a verdict
===== ==========================================================

That last row is the important one. A crashed gate must never be readable as a
policy answer, which is why :func:`main` catches load errors separately and
exits 3.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from stormbot.assurance.evidence import EvidenceState
from stormbot.assurance.registry import AssuranceBundle, RegistryLoadError, load_bundle

__all__ = [
    "POLICIES",
    "CheckReport",
    "CheckStatus",
    "GatePolicy",
    "GateReport",
    "Severity",
    "Verdict",
    "evaluate",
    "main",
    "render",
]

SCHEMA_VERSION = "1.0.0"

EXIT_PASS = 0
EXIT_WARN = 1
EXIT_FAIL = 2
EXIT_EXECUTION_ERROR = 3

#: How stale a review may be before the gate mentions it.
REVIEW_MAX_AGE = timedelta(days=180)


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Severity(StrEnum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


class Verdict(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckReport:
    id: str
    title: str
    status: CheckStatus
    severity: Severity
    detail: str
    subjects: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["severity"] = self.severity.value
        payload["subjects"] = list(self.subjects)
        return payload


@dataclass(frozen=True)
class GatePolicy:
    """A named policy. The same checks, judged at different strictness.

    ``advisory`` exists so a contributor can see the full finding set without
    the gate blocking a docs-only change; ``certification`` exists so that
    promoting a build to certified requires evidence that is bound to an exact
    SHA, which ordinary CI evidence is not.
    """

    name: str
    minimum_state_for_customer_facing: EvidenceState
    enforce_blocking: bool = True

    def severity_of(self, declared: Severity) -> Severity:
        if not self.enforce_blocking:
            return Severity.ADVISORY
        return declared


POLICIES: dict[str, GatePolicy] = {
    "advisory": GatePolicy(
        name="advisory",
        minimum_state_for_customer_facing=EvidenceState.BUILT,
        enforce_blocking=False,
    ),
    "deployment": GatePolicy(
        name="deployment",
        minimum_state_for_customer_facing=EvidenceState.TESTED,
    ),
    "certification": GatePolicy(
        name="certification",
        minimum_state_for_customer_facing=EvidenceState.CERTIFIED,
    ),
}


@dataclass(frozen=True)
class GateReport:
    schema_version: str
    generated_at: datetime
    policy: str
    target: str
    compare_to: str | None
    verdict: Verdict
    checks: tuple[CheckReport, ...]

    @property
    def exit_code(self) -> int:
        return {Verdict.PASS: EXIT_PASS, Verdict.WARN: EXIT_WARN, Verdict.FAIL: EXIT_FAIL}[self.verdict]

    @property
    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in CheckStatus}
        for check in self.checks:
            counts[check.status.value] += 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "policy": self.policy,
            "target": self.target,
            "compare_to": self.compare_to,
            "verdict": self.verdict.value,
            "summary": {
                "total_checks": len(self.checks),
                "passed": self.counts["pass"],
                "warned": self.counts["warn"],
                "failed": self.counts["fail"],
            },
            "checks": [check.to_dict() for check in self.checks],
        }


# ----------------------------------------------------------------------- checks

Check = Callable[[AssuranceBundle, GatePolicy, datetime], CheckReport]


def _report(
    check_id: str,
    title: str,
    policy: GatePolicy,
    declared_severity: Severity,
    failures: Sequence[str],
    ok_detail: str,
    fail_detail: str,
) -> CheckReport:
    severity = policy.severity_of(declared_severity)
    if not failures:
        return CheckReport(check_id, title, CheckStatus.PASS, severity, ok_detail)
    status = CheckStatus.FAIL if severity is Severity.BLOCKING else CheckStatus.WARN
    return CheckReport(
        check_id,
        title,
        status,
        severity,
        f"{fail_detail} ({len(failures)})",
        tuple(sorted(failures)),
    )


def _check_registry_schema(bundle: AssuranceBundle, policy: GatePolicy, _now: datetime) -> CheckReport:
    return _report(
        "registry-schema",
        "Registries validate against their JSON Schemas",
        policy,
        Severity.BLOCKING,
        bundle.schema_errors,
        f"{len(bundle.source_files)} registry files validate",
        "schema violations",
    )


def _check_capability_refs(bundle: AssuranceBundle, policy: GatePolicy, _now: datetime) -> CheckReport:
    failures = [
        f"{claim.id} -> {ref}"
        for claim in bundle.claims.values()
        for ref in claim.capability_refs
        if ref not in bundle.capabilities
    ]
    return _report(
        "capability-refs-resolve",
        "Every claim references a capability that exists",
        policy,
        Severity.BLOCKING,
        failures,
        f"{len(bundle.claims)} claims reference known capabilities",
        "dangling capability references",
    )


def _check_evidence_refs(bundle: AssuranceBundle, policy: GatePolicy, _now: datetime) -> CheckReport:
    failures = [
        f"{claim.id} -> {ref}"
        for claim in bundle.claims.values()
        for ref in claim.evidence_refs
        if ref not in bundle.evidence_ids
    ]
    return _report(
        "evidence-refs-resolve",
        "Every claim references evidence that exists",
        policy,
        Severity.BLOCKING,
        failures,
        f"{len(bundle.evidence_ids)} evidence records referenced cleanly",
        "dangling evidence references",
    )


def _check_claim_state(bundle: AssuranceBundle, policy: GatePolicy, now: datetime) -> CheckReport:
    failures = []
    for claim in bundle.claims.values():
        if not claim.active:
            continue
        for ref in claim.capability_refs:
            capability = bundle.capabilities.get(ref)
            if capability is None:
                continue  # already reported by capability-refs-resolve
            actual = bundle.ledger.state_of(ref, now=now)
            if not actual.at_least(claim.required_state):
                failures.append(
                    f"{claim.id} requires {claim.required_state.value} of {ref}, ledger supports {actual.value}"
                )
    return _report(
        "claim-evidence-sufficiency",
        "Each active claim is backed to its declared evidence state",
        policy,
        Severity.BLOCKING,
        failures,
        "all active claims are backed by sufficient evidence",
        "claims outrunning their evidence",
    )


def _check_customer_facing_floor(bundle: AssuranceBundle, policy: GatePolicy, now: datetime) -> CheckReport:
    floor = policy.minimum_state_for_customer_facing
    failures = []
    for claim in bundle.claims.values():
        if not (claim.active and claim.customer_facing):
            continue
        for ref in claim.capability_refs:
            actual = bundle.ledger.state_of(ref, now=now)
            if not actual.at_least(floor):
                failures.append(f"{claim.id} ({ref} is {actual.value}, policy floor is {floor.value})")
    return _report(
        "customer-facing-floor",
        f"Customer-facing claims reach the {floor.value} floor",
        policy,
        Severity.BLOCKING,
        failures,
        f"customer-facing claims meet the {floor.value} floor",
        f"customer-facing claims below the {floor.value} floor",
    )


def _check_declared_state_honesty(bundle: AssuranceBundle, policy: GatePolicy, now: datetime) -> CheckReport:
    """The registry may not promote itself past what the ledger proves."""
    failures = [
        f"{capability.id} declares {capability.declared_state.value}, ledger supports {bundle.ledger.state_of(capability.id, now=now).value}"
        for capability in bundle.capabilities.values()
        if capability.declared_state.on_ladder
        and not bundle.ledger.state_of(capability.id, now=now).at_least(capability.declared_state)
    ]
    return _report(
        "declared-state-honesty",
        "Declared capability states do not exceed ledger evidence",
        policy,
        Severity.BLOCKING,
        failures,
        "declared states match the evidence ledger",
        "capabilities declaring more than the ledger proves",
    )


def _check_hitl_gates(bundle: AssuranceBundle, policy: GatePolicy, _now: datetime) -> CheckReport:
    failures = [
        capability.id
        for capability in bundle.capabilities.values()
        if capability.requires_human and not capability.approval_gate
    ]
    return _report(
        "hitl-approval-gate",
        "Human-in-the-loop capabilities name their approval gate",
        policy,
        Severity.BLOCKING,
        failures,
        "every human-in-the-loop capability names an approval gate",
        "capabilities requiring a human with no approval gate declared",
    )


def _check_blocked_capabilities(bundle: AssuranceBundle, policy: GatePolicy, _now: datetime) -> CheckReport:
    failures = [
        f"{claim.id} -> {ref}"
        for claim in bundle.claims.values()
        if claim.active
        for ref in claim.capability_refs
        if ref in bundle.capabilities and bundle.capabilities[ref].declared_state is EvidenceState.BLOCKED
    ]
    return _report(
        "no-blocked-capabilities",
        "No active claim depends on a BLOCKED capability",
        policy,
        Severity.BLOCKING,
        failures,
        "no active claim depends on a blocked capability",
        "active claims depending on blocked capabilities",
    )


def _check_review_recency(bundle: AssuranceBundle, policy: GatePolicy, now: datetime) -> CheckReport:
    cutoff = (now - REVIEW_MAX_AGE).date()
    failures = [
        f"{item.id} last reviewed {item.last_reviewed.isoformat()}"
        for item in (*bundle.capabilities.values(), *bundle.claims.values())
        if item.last_reviewed < cutoff
    ]
    return _report(
        "review-recency",
        f"Registry entries reviewed within {REVIEW_MAX_AGE.days} days",
        policy,
        Severity.ADVISORY,
        failures,
        "every registry entry has a recent review",
        "registry entries overdue for review",
    )


def _check_orphan_capabilities(bundle: AssuranceBundle, policy: GatePolicy, _now: datetime) -> CheckReport:
    referenced = {ref for claim in bundle.claims.values() for ref in claim.capability_refs}
    failures = sorted(set(bundle.capabilities) - referenced)
    return _report(
        "orphan-capabilities",
        "Every registered capability is referenced by a claim",
        policy,
        Severity.ADVISORY,
        failures,
        "no orphaned capabilities",
        "capabilities referenced by no claim",
    )


CHECKS: tuple[Check, ...] = (
    _check_registry_schema,
    _check_capability_refs,
    _check_evidence_refs,
    _check_claim_state,
    _check_customer_facing_floor,
    _check_declared_state_honesty,
    _check_hitl_gates,
    _check_blocked_capabilities,
    _check_review_recency,
    _check_orphan_capabilities,
)


# --------------------------------------------------------------------- evaluate


def evaluate(
    bundle: AssuranceBundle,
    *,
    policy: GatePolicy,
    target: str = "HEAD",
    compare_to: str | None = None,
    now: datetime | None = None,
) -> GateReport:
    now = now or datetime.now(UTC)
    checks = tuple(check(bundle, policy, now) for check in CHECKS)

    if any(c.status is CheckStatus.FAIL for c in checks):
        verdict = Verdict.FAIL
    elif any(c.status is CheckStatus.WARN for c in checks):
        verdict = Verdict.WARN
    else:
        verdict = Verdict.PASS

    return GateReport(
        schema_version=SCHEMA_VERSION,
        generated_at=now,
        policy=policy.name,
        target=target,
        compare_to=compare_to,
        verdict=verdict,
        checks=checks,
    )


# ----------------------------------------------------------------------- render

_ICON = {CheckStatus.PASS: "PASS", CheckStatus.WARN: "WARN", CheckStatus.FAIL: "FAIL"}


def render(report: GateReport, fmt: str = "text") -> str:
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=False) + "\n"
    if fmt == "markdown":
        return _render_markdown(report)
    if fmt == "text":
        return _render_text(report)
    raise ValueError(f"unknown format: {fmt!r}")


def _render_text(report: GateReport) -> str:
    lines = [
        f"release gate: {report.verdict.value.upper()}",
        f"policy={report.policy} target={report.target} compare_to={report.compare_to or '-'}",
        "",
    ]
    for check in report.checks:
        lines.append(f"[{_ICON[check.status]}] {check.id} ({check.severity.value}) — {check.detail}")
        for subject in check.subjects:
            lines.append(f"         - {subject}")
    counts = report.counts
    lines += [
        "",
        f"{counts['pass']} passed, {counts['warn']} warned, {counts['fail']} failed",
    ]
    return "\n".join(lines) + "\n"


def _render_markdown(report: GateReport) -> str:
    counts = report.counts
    lines = [
        f"## Release gate: `{report.verdict.value.upper()}`",
        "",
        f"- **Policy:** `{report.policy}`",
        f"- **Target:** `{report.target}`",
        f"- **Compared to:** `{report.compare_to or '-'}`",
        f"- **Result:** {counts['pass']} passed, {counts['warn']} warned, {counts['fail']} failed",
        "",
        "| Check | Severity | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        lines.append(f"| `{check.id}` | {check.severity.value} | {check.status.value} | {check.detail} |")
    findings = [(c, s) for c in report.checks for s in c.subjects]
    if findings:
        lines += ["", "<details><summary>Findings</summary>", ""]
        for check, subject in findings:
            lines.append(f"- `{check.id}` — {subject}")
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------- cli


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stormbot.assurance.release_gate",
        description="Evaluate product claims against evidence and emit a release verdict.",
    )
    parser.add_argument("--registry-root", type=Path, default=None, help="path to the assurance/ directory")
    parser.add_argument("--policy", choices=sorted(POLICIES), default="deployment")
    parser.add_argument("--target", default="HEAD", help="commit-ish being evaluated")
    parser.add_argument("--compare-to", default=None, help="base commit-ish for the comparison")
    parser.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    parser.add_argument("--output", type=Path, default=None, help="write the JSON report here")
    parser.add_argument("--markdown-output", type=Path, default=None, help="write a Markdown report here")
    parser.add_argument("--now", default=None, help="ISO-8601 evaluation time (for reproducible runs)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        bundle = load_bundle(args.registry_root)
    except RegistryLoadError as exc:
        print(f"release gate could not run: {exc}", file=sys.stderr)
        return EXIT_EXECUTION_ERROR

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    report = evaluate(
        bundle,
        policy=POLICIES[args.policy],
        target=args.target,
        compare_to=args.compare_to,
        now=now,
    )

    sys.stdout.write(render(report, args.format))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render(report, "json"), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render(report, "markdown"), encoding="utf-8")

    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())

"""The execution governor: one ordered, fail-closed decision pipeline.

An autonomous agent that can send SMS, email prospects, or move money needs a
single place where "may I do this?" is answered. Scattering the checks across
call sites guarantees that some future call site will be missing one.

Design rules, in the order they matter:

1. **Default deny.** An action type the policy has never heard of is denied. New
   capabilities become reachable by an explicit policy edit, not by shipping a
   new tool.
2. **The governor decides, it does not act.** ``evaluate`` returns a
   :class:`Decision`. Nothing in this module can send anything.
3. **Every check runs.** The pipeline does not short-circuit on the first block,
   because an operator debugging a denial needs the whole trail, not the first
   reason alphabetically.
4. **An exception is a denial.** A check that raises has not passed. There is no
   path through this function that turns an error into an allow.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum

from stormbot.governance.approvals import ApprovalTokenIssuer, InvalidApprovalToken
from stormbot.governance.redaction import Redactor
from stormbot.governance.suppression import SuppressionRegistry

__all__ = [
    "ActionRequest",
    "CheckOutcome",
    "CheckResult",
    "Decision",
    "ExecutionGovernor",
    "GovernorPolicy",
    "Verdict",
]


class Verdict(StrEnum):
    ALLOW = "ALLOW"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    DENY = "DENY"


class CheckOutcome(StrEnum):
    PASS = "PASS"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK = "BLOCK"
    ERROR = "ERROR"


@dataclass(frozen=True)
class CheckResult:
    """One check's contribution to the decision. Safe to log verbatim."""

    check_id: str
    outcome: CheckOutcome
    detail: str

    @property
    def blocking(self) -> bool:
        return self.outcome in (CheckOutcome.BLOCK, CheckOutcome.ERROR)


@dataclass(frozen=True)
class ActionRequest:
    """A proposed real-world action.

    ``target`` is a raw contact identifier and is never logged by this module —
    only its suppression digest is. ``dry_run`` does not influence the verdict:
    a rehearsal that takes a different path through the checks is not a
    rehearsal of anything.
    """

    action_type: str
    actor: str
    target: str
    payload: str
    requested_at: datetime
    approval_token: str | None = None
    dry_run: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """The governor's answer, plus the complete reasoning trail."""

    verdict: Verdict
    action_type: str
    target_digest: str
    decided_at: datetime
    checks: tuple[CheckResult, ...]

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        return tuple(f"{c.check_id}: {c.detail}" for c in self.checks if c.blocking)

    def as_log_record(self) -> dict[str, object]:
        """A structured record with no raw contact data and no payload."""
        return {
            "verdict": self.verdict.value,
            "action_type": self.action_type,
            "target_digest": self.target_digest,
            "decided_at": self.decided_at.astimezone(UTC).isoformat(),
            "checks": [
                {"check_id": c.check_id, "outcome": c.outcome.value, "detail": c.detail} for c in self.checks
            ],
        }


@dataclass(frozen=True)
class GovernorPolicy:
    """Static policy. Everything not named here is denied.

    ``consequential_actions`` is the subset of ``allowed_actions`` that reaches a
    third party. Those require the go-live gate, an approval token, quiet-hours
    compliance, and a daily budget. Read-only actions skip those four but still
    face the allowlist and payload scan.
    """

    allowed_actions: frozenset[str]
    consequential_actions: frozenset[str]
    daily_budget: Mapping[str, int]
    go_live: bool = False
    kill_switch_engaged: bool = False
    quiet_hours: tuple[int, int] = (21, 8)
    operator_utc_offset_hours: int = 0

    def __post_init__(self) -> None:
        unknown = self.consequential_actions - self.allowed_actions
        if unknown:
            raise ValueError(f"consequential actions must also be allowed actions: {sorted(unknown)}")
        start, end = self.quiet_hours
        if not (0 <= start <= 23 and 0 <= end <= 23):
            raise ValueError("quiet_hours must be hours in [0, 23]")

    def is_consequential(self, action_type: str) -> bool:
        return action_type in self.consequential_actions

    def in_quiet_hours(self, moment: datetime) -> bool:
        local = moment.astimezone(timezone(timedelta(hours=self.operator_utc_offset_hours)))
        start, end = self.quiet_hours
        if start == end:
            return False
        if start < end:
            return start <= local.hour < end
        return local.hour >= start or local.hour < end


class ExecutionGovernor:
    """Evaluates action requests against policy. Never performs an action."""

    def __init__(
        self,
        *,
        policy: GovernorPolicy,
        suppression: SuppressionRegistry,
        approvals: ApprovalTokenIssuer,
        redactor: Redactor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy
        self._suppression = suppression
        self._approvals = approvals
        self._redactor = redactor or Redactor()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._spend: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------ public

    def evaluate(self, request: ActionRequest) -> Decision:
        decided_at = self._clock()
        try:
            target_digest = self._suppression.digest_for(request.target)
        except ValueError:
            # An identifier that cannot be normalized cannot be cleared against
            # the suppression list, so it cannot be contacted.
            return Decision(
                verdict=Verdict.DENY,
                action_type=request.action_type,
                target_digest="unresolvable",
                decided_at=decided_at,
                checks=(
                    CheckResult(
                        "target_normalization",
                        CheckOutcome.BLOCK,
                        "target identifier could not be normalized",
                    ),
                ),
            )

        checks = tuple(self._run_checks(request, target_digest))
        return Decision(
            verdict=self._verdict_for(checks),
            action_type=request.action_type,
            target_digest=target_digest,
            decided_at=decided_at,
            checks=checks,
        )

    def commit(self, request: ActionRequest, decision: Decision) -> None:
        """Record budget spend after an allowed action was actually performed.

        Spend is recorded on commit rather than on evaluation so that a denied
        or merely simulated action never consumes a real send quota.
        """
        if not decision.allowed or request.dry_run:
            return
        key = self._budget_key(request)
        self._spend[key] = self._spend.get(key, 0) + 1

    def spend_today(self, action_type: str, moment: datetime) -> int:
        return self._spend.get((action_type, self._day_key(moment)), 0)

    # ----------------------------------------------------------------- checks

    def _run_checks(self, request: ActionRequest, target_digest: str):
        checks = (
            self._check_known_action,
            self._check_kill_switch,
            self._check_go_live_gate,
            self._check_payload_safety,
            self._check_suppression,
            self._check_quiet_hours,
            self._check_budget,
            self._check_approval,
        )
        for check in checks:
            try:
                yield check(request, target_digest)
            except Exception as exc:  # a raising check is a failing check
                yield CheckResult(
                    check_id=check.__name__.removeprefix("_check_"),
                    outcome=CheckOutcome.ERROR,
                    detail=f"check raised {type(exc).__name__}",
                )

    def _check_known_action(self, request: ActionRequest, _digest: str) -> CheckResult:
        if request.action_type not in self._policy.allowed_actions:
            return CheckResult(
                "known_action",
                CheckOutcome.BLOCK,
                f"action type {request.action_type!r} is not in the policy allowlist",
            )
        return CheckResult("known_action", CheckOutcome.PASS, "action type is allowlisted")

    def _check_kill_switch(self, _request: ActionRequest, _digest: str) -> CheckResult:
        if self._policy.kill_switch_engaged:
            return CheckResult("kill_switch", CheckOutcome.BLOCK, "operator kill switch is engaged")
        return CheckResult("kill_switch", CheckOutcome.PASS, "kill switch is clear")

    def _check_go_live_gate(self, request: ActionRequest, _digest: str) -> CheckResult:
        if not self._policy.is_consequential(request.action_type):
            return CheckResult("go_live_gate", CheckOutcome.PASS, "action is not consequential")
        if not self._policy.go_live:
            return CheckResult("go_live_gate", CheckOutcome.BLOCK, "go-live gate is closed")
        return CheckResult("go_live_gate", CheckOutcome.PASS, "go-live gate is open")

    def _check_payload_safety(self, request: ActionRequest, _digest: str) -> CheckResult:
        detectors = sorted({f.detector for f in self._redactor.scan(request.payload) if f.is_secret})
        if detectors:
            return CheckResult(
                "payload_safety",
                CheckOutcome.BLOCK,
                f"outbound payload matched credential detectors: {detectors}",
            )
        return CheckResult("payload_safety", CheckOutcome.PASS, "no credential shapes in payload")

    def _check_suppression(self, request: ActionRequest, _digest: str) -> CheckResult:
        if not self._policy.is_consequential(request.action_type):
            return CheckResult("suppression", CheckOutcome.PASS, "action does not reach a contact")
        if self._suppression.is_suppressed(request.target):
            reason = self._suppression.reason_for(request.target) or "unknown"
            return CheckResult("suppression", CheckOutcome.BLOCK, f"target is suppressed ({reason})")
        return CheckResult("suppression", CheckOutcome.PASS, "target is not suppressed")

    def _check_quiet_hours(self, request: ActionRequest, _digest: str) -> CheckResult:
        if not self._policy.is_consequential(request.action_type):
            return CheckResult("quiet_hours", CheckOutcome.PASS, "action does not reach a contact")
        if self._policy.in_quiet_hours(request.requested_at):
            return CheckResult("quiet_hours", CheckOutcome.BLOCK, "request falls inside quiet hours")
        return CheckResult("quiet_hours", CheckOutcome.PASS, "request is outside quiet hours")

    def _check_budget(self, request: ActionRequest, _digest: str) -> CheckResult:
        if not self._policy.is_consequential(request.action_type):
            return CheckResult("budget", CheckOutcome.PASS, "action is not budgeted")
        limit = self._policy.daily_budget.get(request.action_type)
        if limit is None:
            return CheckResult("budget", CheckOutcome.BLOCK, "consequential action has no daily budget")
        spent = self.spend_today(request.action_type, request.requested_at)
        if spent >= limit:
            return CheckResult("budget", CheckOutcome.BLOCK, f"daily budget exhausted ({spent}/{limit})")
        return CheckResult("budget", CheckOutcome.PASS, f"within daily budget ({spent}/{limit})")

    def _check_approval(self, request: ActionRequest, target_digest: str) -> CheckResult:
        if not self._policy.is_consequential(request.action_type):
            return CheckResult("approval", CheckOutcome.PASS, "action does not require approval")
        if not request.approval_token:
            return CheckResult("approval", CheckOutcome.REQUIRE_APPROVAL, "no approval token presented")
        try:
            token = self._approvals.verify(
                request.approval_token,
                action_type=request.action_type,
                target_digest=target_digest,
                now=request.requested_at,
            )
        except InvalidApprovalToken as exc:
            return CheckResult("approval", CheckOutcome.BLOCK, f"approval rejected: {exc}")
        return CheckResult("approval", CheckOutcome.PASS, f"approved by {token.approver}")

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _verdict_for(checks: tuple[CheckResult, ...]) -> Verdict:
        if any(c.blocking for c in checks):
            return Verdict.DENY
        if any(c.outcome is CheckOutcome.REQUIRE_APPROVAL for c in checks):
            return Verdict.REQUIRES_APPROVAL
        return Verdict.ALLOW

    def _budget_key(self, request: ActionRequest) -> tuple[str, str]:
        return (request.action_type, self._day_key(request.requested_at))

    def _day_key(self, moment: datetime) -> str:
        local = moment.astimezone(timezone(timedelta(hours=self._policy.operator_utc_offset_hours)))
        return local.date().isoformat()

"""Shared fixtures. Deliberately small — most tests build their own policy.

A test that hides its policy inside a shared factory is a test whose reader has
to go somewhere else to find out what is being asserted. These helpers cover
only the boilerplate that is genuinely identical everywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime

from stormbot.governance import (
    ApprovalTokenIssuer,
    ExecutionGovernor,
    GovernorPolicy,
    Redactor,
    SuppressionRegistry,
)

#: A Tuesday, 14:00 UTC — a weekday, comfortably outside default quiet hours.
BUSINESS_HOURS = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)

#: 03:00 UTC on the same day, inside the default 21:00-08:00 quiet window.
QUIET_HOURS = datetime(2026, 9, 8, 3, 0, tzinfo=UTC)

SUPPRESSION_KEY = b"test-suppression-key-not-a-secret"
APPROVAL_SECRET = b"test-approval-secret-not-a-secret"

SEND_SMS = "outreach.send_sms"
SEND_EMAIL = "outreach.send_email"
DRAFT_MESSAGE = "outreach.draft_message"


def default_policy(**overrides) -> GovernorPolicy:
    settings = {
        "allowed_actions": frozenset({SEND_SMS, SEND_EMAIL, DRAFT_MESSAGE}),
        "consequential_actions": frozenset({SEND_SMS, SEND_EMAIL}),
        "daily_budget": {SEND_SMS: 3, SEND_EMAIL: 5},
        "go_live": True,
        "quiet_hours": (21, 8),
    }
    settings.update(overrides)
    return GovernorPolicy(**settings)


def build_governor(
    policy: GovernorPolicy | None = None,
    suppression: SuppressionRegistry | None = None,
) -> tuple[ExecutionGovernor, SuppressionRegistry, ApprovalTokenIssuer]:
    suppression = suppression or SuppressionRegistry(key=SUPPRESSION_KEY)
    approvals = ApprovalTokenIssuer(secret=APPROVAL_SECRET)
    governor = ExecutionGovernor(
        policy=policy or default_policy(),
        suppression=suppression,
        approvals=approvals,
        redactor=Redactor(),
        clock=lambda: BUSINESS_HOURS,
    )
    return governor, suppression, approvals

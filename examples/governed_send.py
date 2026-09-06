#!/usr/bin/env python3
"""Walk one outreach message through the governor, four ways.

    PYTHONPATH=src python3 examples/governed_send.py

Each scenario is the same message to the same person, changing one thing at a
time, so the effect of each control is visible on its own.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stormbot.governance import (
    ActionRequest,
    ApprovalTokenIssuer,
    ExecutionGovernor,
    GovernorPolicy,
    SuppressionRegistry,
)

SEND_SMS = "outreach.send_sms"
PROSPECT = "+18135550142"
OPTED_OUT = "+18135550199"
TUESDAY_2PM = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)

POLICY = GovernorPolicy(
    allowed_actions=frozenset({SEND_SMS, "outreach.draft_message"}),
    consequential_actions=frozenset({SEND_SMS}),
    daily_budget={SEND_SMS: 25},
    go_live=True,
    quiet_hours=(21, 8),
)


def main() -> int:
    suppression = SuppressionRegistry(key=b"demo-key-do-not-use-in-production")
    suppression.suppress(OPTED_OUT, reason="opt_out", source="sms_stop_keyword")
    approvals = ApprovalTokenIssuer(secret=b"demo-approval-secret-not-real")

    governor = ExecutionGovernor(
        policy=POLICY,
        suppression=suppression,
        approvals=approvals,
        clock=lambda: TUESDAY_2PM,
    )

    def request(**overrides) -> ActionRequest:
        fields = {
            "action_type": SEND_SMS,
            "actor": "agent.outreach",
            "target": PROSPECT,
            "payload": "Hi Dana - following up on the roof estimate. Thursday still work?",
            "requested_at": TUESDAY_2PM,
        }
        fields.update(overrides)
        return ActionRequest(**fields)

    def approved(req: ActionRequest) -> ActionRequest:
        token = approvals.issue(
            action_type=req.action_type,
            target_digest=suppression.digest_for(req.target),
            approver="brian",
            now=req.requested_at,
        )
        return replace(req, approval_token=token)

    scenarios = [
        ("agent proposes a send, nobody has approved it", request()),
        ("an operator approves this exact message", approved(request())),
        ("the same approval, aimed at someone who opted out", approved(request(target=OPTED_OUT))),
        (
            "the draft accidentally contains an API key",
            approved(request(payload="Portal login: sk_live_" + "0123456789abcdefghij")),
        ),
        ("an action nobody put on the allowlist", approved(request(action_type="billing.charge_card"))),
    ]

    for title, action in scenarios:
        decision = governor.evaluate(action)
        print(f"\n{title}")
        print(f"  verdict: {decision.verdict.value}")
        for reason in decision.blocking_reasons or ("-",):
            print(f"  reason:  {reason}")

    print("\nNote that the log record carries no phone number and no message body:")
    print(f"  {governor.evaluate(request()).as_log_record()['target_digest'][:16]}... (digest)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

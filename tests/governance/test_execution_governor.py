"""Contract tests for the execution governor.

The valuable assertions here are the negative ones. A test proving that a
correctly approved message is allowed is worth much less than a test proving
that an unknown action type, a closed go-live gate, or a check that raised an
exception all end in DENY.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from stormbot.governance import ActionRequest, CheckOutcome, Verdict
from tests.support import (
    BUSINESS_HOURS,
    DRAFT_MESSAGE,
    QUIET_HOURS,
    SEND_SMS,
    build_governor,
    default_policy,
)

RECIPIENT = "+18135550142"


def request(**overrides) -> ActionRequest:
    fields = {
        "action_type": SEND_SMS,
        "actor": "agent.outreach",
        "target": RECIPIENT,
        "payload": "Hi Dana - following up on the roof inspection quote.",
        "requested_at": BUSINESS_HOURS,
    }
    fields.update(overrides)
    return ActionRequest(**fields)


class DefaultDenyTests(unittest.TestCase):
    def test_unknown_action_type_is_denied(self):
        governor, _, _ = build_governor()

        decision = governor.evaluate(request(action_type="outreach.wire_transfer"))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertIn("known_action", decision.blocking_reasons[0])

    def test_unnormalizable_target_is_denied_without_reaching_other_checks(self):
        governor, _, _ = build_governor()

        decision = governor.evaluate(request(target="   "))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.target_digest, "unresolvable")

    def test_a_check_that_raises_denies_rather_than_allows(self):
        """The single most important property in this module."""
        governor, suppression, _ = build_governor()

        def explode(_contact: str) -> bool:
            raise RuntimeError("suppression backend unavailable")

        suppression.is_suppressed = explode  # type: ignore[method-assign]

        decision = governor.evaluate(request(approval_token=None))

        self.assertIs(decision.verdict, Verdict.DENY)
        errored = [c for c in decision.checks if c.outcome is CheckOutcome.ERROR]
        self.assertEqual([c.check_id for c in errored], ["suppression"])
        self.assertIn("RuntimeError", errored[0].detail)


class GateTests(unittest.TestCase):
    def test_consequential_action_is_blocked_while_go_live_is_closed(self):
        governor, _, _ = build_governor(default_policy(go_live=False))

        decision = governor.evaluate(request())

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("go_live_gate" in reason for reason in decision.blocking_reasons))

    def test_kill_switch_blocks_even_a_fully_approved_request(self):
        governor, suppression, approvals = build_governor(default_policy(kill_switch_engaged=True))
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        decision = governor.evaluate(request(approval_token=token))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("kill_switch" in reason for reason in decision.blocking_reasons))

    def test_non_consequential_action_bypasses_the_go_live_gate(self):
        governor, _, _ = build_governor(default_policy(go_live=False))

        decision = governor.evaluate(request(action_type=DRAFT_MESSAGE))

        self.assertIs(decision.verdict, Verdict.ALLOW)

    def test_quiet_hours_block_outbound_contact(self):
        governor, suppression, approvals = build_governor()
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=QUIET_HOURS,
        )

        decision = governor.evaluate(request(requested_at=QUIET_HOURS, approval_token=token))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("quiet_hours" in reason for reason in decision.blocking_reasons))


class ApprovalTests(unittest.TestCase):
    def test_missing_approval_requests_approval_rather_than_denying(self):
        governor, _, _ = build_governor()

        decision = governor.evaluate(request())

        self.assertIs(decision.verdict, Verdict.REQUIRES_APPROVAL)

    def test_valid_scoped_approval_allows_the_send(self):
        governor, suppression, approvals = build_governor()
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        decision = governor.evaluate(request(approval_token=token))

        self.assertIs(decision.verdict, Verdict.ALLOW)

    def test_approval_for_a_different_recipient_is_denied_not_merely_unapproved(self):
        """A wrong-target token is an attempted bypass, so it blocks."""
        governor, suppression, approvals = build_governor()
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for("+18135550199"),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        decision = governor.evaluate(request(approval_token=token))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("different target" in reason for reason in decision.blocking_reasons))

    def test_expired_approval_is_denied(self):
        governor, suppression, approvals = build_governor()
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS - timedelta(hours=2),
            ttl=timedelta(minutes=30),
        )

        decision = governor.evaluate(request(approval_token=token))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("expired" in reason for reason in decision.blocking_reasons))


class SuppressionAndBudgetTests(unittest.TestCase):
    def test_suppressed_recipient_is_denied_despite_a_valid_approval(self):
        governor, suppression, approvals = build_governor()
        suppression.suppress(RECIPIENT, reason="opt_out", source="sms_stop_keyword")
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        decision = governor.evaluate(request(approval_token=token))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("suppressed" in reason for reason in decision.blocking_reasons))

    def test_budget_is_consumed_on_commit_and_exhausts(self):
        governor, suppression, approvals = build_governor(default_policy(daily_budget={SEND_SMS: 2}))
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        for _ in range(2):
            allowed = governor.evaluate(request(approval_token=token))
            self.assertIs(allowed.verdict, Verdict.ALLOW)
            governor.commit(request(approval_token=token), allowed)

        exhausted = governor.evaluate(request(approval_token=token))

        self.assertIs(exhausted.verdict, Verdict.DENY)
        self.assertTrue(any("budget exhausted" in reason for reason in exhausted.blocking_reasons))

    def test_denied_and_dry_run_actions_do_not_consume_budget(self):
        governor, suppression, approvals = build_governor()
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        denied_request = request()  # no approval token
        governor.commit(denied_request, governor.evaluate(denied_request))

        rehearsal = request(approval_token=token, dry_run=True)
        governor.commit(rehearsal, governor.evaluate(rehearsal))

        self.assertEqual(governor.spend_today(SEND_SMS, BUSINESS_HOURS), 0)

    def test_consequential_action_without_a_budget_is_denied(self):
        governor, suppression, approvals = build_governor(default_policy(daily_budget={}))
        token = approvals.issue(
            action_type=SEND_SMS,
            target_digest=suppression.digest_for(RECIPIENT),
            approver="brian",
            now=BUSINESS_HOURS,
        )

        decision = governor.evaluate(request(approval_token=token))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("no daily budget" in reason for reason in decision.blocking_reasons))


class PayloadAndLoggingTests(unittest.TestCase):
    def test_payload_carrying_a_credential_shape_is_blocked(self):
        governor, _, _ = build_governor()

        # Split so the literal never exists as a key-shaped string in this file;
        # tests/contract/test_repository_hygiene.py enforces that convention.
        decision = governor.evaluate(request(payload="Use this to log in: sk_live_" + "0123456789abcdefghij"))

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertTrue(any("payload_safety" in reason for reason in decision.blocking_reasons))

    def test_log_record_contains_no_raw_target_and_no_payload(self):
        governor, _, _ = build_governor()
        payload = "Hi Dana - reaching you at 813-555-0142."

        record = governor.evaluate(request(payload=payload)).as_log_record()

        serialized = repr(record)
        self.assertNotIn(RECIPIENT, serialized)
        self.assertNotIn("813-555-0142", serialized)
        self.assertNotIn(payload, serialized)

    def test_every_check_appears_in_the_trail_even_after_a_block(self):
        """Operators debugging a denial need the whole picture, not the first no."""
        governor, _, _ = build_governor(default_policy(go_live=False))

        decision = governor.evaluate(request())

        self.assertEqual(
            [check.check_id for check in decision.checks],
            [
                "known_action",
                "kill_switch",
                "go_live_gate",
                "payload_safety",
                "suppression",
                "quiet_hours",
                "budget",
                "approval",
            ],
        )


if __name__ == "__main__":
    unittest.main()

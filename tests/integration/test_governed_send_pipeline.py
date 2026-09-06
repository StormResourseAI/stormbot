"""End-to-end: an outreach message from draft to send, or to refusal.

Unit tests prove each control works. This proves they compose — that the
suppression list, the approval issuer, the redactor, and the budget are all
consulted by the same decision, and that no arrangement of them lets a message
through that should not have gone.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from stormbot.governance import (
    ActionRequest,
    ApprovalTokenIssuer,
    ExecutionGovernor,
    ProductionDatabaseError,
    Redactor,
    SuppressionRegistry,
    Verdict,
    assert_test_database,
)
from tests.support import (
    APPROVAL_SECRET,
    BUSINESS_HOURS,
    DRAFT_MESSAGE,
    SEND_SMS,
    SUPPRESSION_KEY,
    default_policy,
)

PROSPECT = "+18135550142"
OPTED_OUT = "(813) 555-0199"


class OutboundSender:
    """Stands in for the SMS provider. Records what it was actually asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, target: str, body: str) -> None:
        self.sent.append((target, body))


class GovernedSendPipeline:
    """The only path from an agent's intent to a real message.

    The provider is private to this object and is reachable only through a
    dispatch table keyed by action type. There is no method here that sends
    without first consulting the governor, which is the entire point: the safety
    property is structural rather than a rule someone has to remember.
    """

    def __init__(self, governor: ExecutionGovernor, sender: OutboundSender) -> None:
        self._governor = governor
        self._dispatch = {SEND_SMS: sender.send}
        self.audit: list[dict[str, object]] = []

    def attempt(self, request: ActionRequest):
        decision = self._governor.evaluate(request)
        self.audit.append(decision.as_log_record())
        if decision.allowed and not request.dry_run:
            handler = self._dispatch.get(request.action_type)
            if handler is not None:
                handler(request.target, request.payload)
            self._governor.commit(request, decision)
        return decision


class GovernedSendPipelineTests(unittest.TestCase):
    def setUp(self):
        self.suppression = SuppressionRegistry(key=SUPPRESSION_KEY)
        self.suppression.suppress(OPTED_OUT, reason="opt_out", source="sms_stop_keyword")
        self.approvals = ApprovalTokenIssuer(secret=APPROVAL_SECRET)
        self.governor = ExecutionGovernor(
            policy=default_policy(daily_budget={SEND_SMS: 2}),
            suppression=self.suppression,
            approvals=self.approvals,
            redactor=Redactor(),
            clock=lambda: BUSINESS_HOURS,
        )
        self.sender = OutboundSender()
        self.pipeline = GovernedSendPipeline(self.governor, self.sender)

    def request(self, **overrides) -> ActionRequest:
        fields = {
            "action_type": SEND_SMS,
            "actor": "agent.outreach",
            "target": PROSPECT,
            "payload": "Following up on your roof estimate - happy to book Thursday.",
            "requested_at": BUSINESS_HOURS,
        }
        fields.update(overrides)
        return ActionRequest(**fields)

    def approve(self, request: ActionRequest) -> ActionRequest:
        token = self.approvals.issue(
            action_type=request.action_type,
            target_digest=self.suppression.digest_for(request.target),
            approver="brian",
            now=request.requested_at,
        )
        return replace(request, approval_token=token)

    # ------------------------------------------------------------------ flows

    def test_the_full_happy_path_reaches_the_provider_exactly_once(self):
        draft = self.request(action_type=DRAFT_MESSAGE)
        self.assertIs(self.pipeline.attempt(draft).verdict, Verdict.ALLOW)

        pending = self.request()
        self.assertIs(self.pipeline.attempt(pending).verdict, Verdict.REQUIRES_APPROVAL)
        self.assertEqual(self.sender.sent, [])

        approved = self.approve(pending)
        self.assertIs(self.pipeline.attempt(approved).verdict, Verdict.ALLOW)

        self.assertEqual(len(self.sender.sent), 1)
        self.assertEqual(self.sender.sent[0][0], PROSPECT)

    def test_an_opted_out_prospect_is_never_reached_even_with_a_valid_approval(self):
        request = self.approve(self.request(target=OPTED_OUT))

        decision = self.pipeline.attempt(request)

        self.assertIs(decision.verdict, Verdict.DENY)
        self.assertEqual(self.sender.sent, [])

    def test_opt_out_survives_a_reformatted_import_of_the_same_number(self):
        """The opt-out was recorded as '(813) 555-0199'; the CRM exports E.164."""
        request = self.approve(self.request(target="+18135550199"))

        self.assertIs(self.pipeline.attempt(request).verdict, Verdict.DENY)
        self.assertEqual(self.sender.sent, [])

    def test_a_leaked_credential_in_a_drafted_message_blocks_the_send(self):
        request = self.approve(self.request(payload="Portal access: sk_live_" + "0123456789abcdefghij"))

        self.assertIs(self.pipeline.attempt(request).verdict, Verdict.DENY)
        self.assertEqual(self.sender.sent, [])

    def test_the_daily_budget_stops_the_third_send(self):
        for index in range(2):
            request = self.approve(self.request(payload=f"Follow-up number {index}."))
            self.assertIs(self.pipeline.attempt(request).verdict, Verdict.ALLOW)

        third = self.approve(self.request(payload="One more follow-up."))

        self.assertIs(self.pipeline.attempt(third).verdict, Verdict.DENY)
        self.assertEqual(len(self.sender.sent), 2)

    def test_a_dry_run_makes_the_same_decision_and_sends_nothing(self):
        live = self.approve(self.request())
        rehearsal = replace(live, dry_run=True)

        rehearsed = self.pipeline.attempt(rehearsal)
        performed = self.pipeline.attempt(live)

        self.assertIs(rehearsed.verdict, performed.verdict)
        self.assertEqual(len(self.sender.sent), 1)

    def test_an_approval_issued_for_yesterday_no_longer_works_today(self):
        stale = self.request(requested_at=BUSINESS_HOURS - timedelta(days=1))
        token = self.approve(stale).approval_token
        today = replace(self.request(), approval_token=token)

        self.assertIs(self.pipeline.attempt(today).verdict, Verdict.DENY)
        self.assertEqual(self.sender.sent, [])

    # ------------------------------------------------------------------ audit

    def test_every_attempt_is_audited_without_raw_contact_data(self):
        self.pipeline.attempt(self.request())
        self.pipeline.attempt(self.approve(self.request(target=OPTED_OUT)))

        serialized = repr(self.pipeline.audit)

        self.assertEqual(len(self.pipeline.audit), 2)
        self.assertNotIn(PROSPECT, serialized)
        self.assertNotIn("555-0199", serialized)
        self.assertIn("suppression", serialized)

    def test_this_pipeline_cannot_be_pointed_at_production_state(self):
        with self.assertRaises(ProductionDatabaseError):
            assert_test_database("sqlite:///./stormbot.db", env={"STORMBOT_TEST_MODE": "1"})


if __name__ == "__main__":
    unittest.main()

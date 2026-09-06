"""Runtime governance: the controls that stand between an agent and the world.

Every consequential action an agent proposes is routed through
:class:`~stormbot.governance.governor.ExecutionGovernor`, which returns a
:class:`~stormbot.governance.governor.Decision` rather than performing the
action. Callers cannot bypass a check by forgetting one; the governor owns the
whole ordered pipeline and denies by default.
"""

from __future__ import annotations

from stormbot.governance.approvals import (
    ApprovalToken,
    ApprovalTokenIssuer,
    InvalidApprovalToken,
)
from stormbot.governance.db_guard import ProductionDatabaseError, assert_test_database
from stormbot.governance.governor import (
    ActionRequest,
    CheckOutcome,
    CheckResult,
    Decision,
    ExecutionGovernor,
    GovernorPolicy,
    Verdict,
)
from stormbot.governance.redaction import Finding, Redactor
from stormbot.governance.suppression import SuppressionRecord, SuppressionRegistry

__all__ = [
    "ActionRequest",
    "ApprovalToken",
    "ApprovalTokenIssuer",
    "CheckOutcome",
    "CheckResult",
    "Decision",
    "ExecutionGovernor",
    "Finding",
    "GovernorPolicy",
    "InvalidApprovalToken",
    "ProductionDatabaseError",
    "Redactor",
    "SuppressionRecord",
    "SuppressionRegistry",
    "Verdict",
    "assert_test_database",
]

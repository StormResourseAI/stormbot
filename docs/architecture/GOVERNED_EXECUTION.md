# Governed execution

The eight checks in [`ExecutionGovernor`](../../src/stormbot/governance/governor.py),
what each one actually defends against, and how it fails.

---

## The shape of the decision

```python
@dataclass(frozen=True)
class Decision:
    verdict: Verdict  # ALLOW · REQUIRES_APPROVAL · DENY
    action_type: str
    target_digest: str  # never the raw identifier
    decided_at: datetime
    checks: tuple[CheckResult, ...]  # all eight, always
```

Verdict resolution, from [`_verdict_for`](../../src/stormbot/governance/governor.py):

```
any check BLOCK or ERROR        → DENY
else any check REQUIRE_APPROVAL → REQUIRES_APPROVAL
else                            → ALLOW
```

`DENY` dominates. A request with a perfectly valid approval token and a suppressed
recipient is denied, not "approved but blocked" — there is no verdict that means
"partially permitted", because a caller would eventually treat one as a yes.

---

## The checks

### 1. `known_action` — default deny

```python
if request.action_type not in self._policy.allowed_actions:
    return CheckResult("known_action", CheckOutcome.BLOCK, ...)
```

**Defends against:** capability creep. Someone adds a tool to the agent's
registry, and the agent starts using it in production before anyone reviewed the
blast radius.

**Why first:** it is the cheapest check and the most absolute. An action type
nobody wrote down cannot be reasoned about by any of the other seven.

**Consequence:** shipping a new tool is not the same as enabling it. Enabling it
is a policy edit, which is a diff someone reviews.

### 2. `kill_switch` — operator override

**Defends against:** the situation where something is clearly wrong and the
operator does not have time to work out which specific control to reach for.

**Why second:** it must sit above everything, including a valid approval. An
engaged kill switch that could be overridden by a token is not a kill switch.

### 3. `go_live_gate` — system-wide readiness

**Defends against:** a staging or freshly-deployed system reaching real people.
Non-consequential actions (drafting, scoring, summarizing) pass through, so
development is unaffected while the gate is closed.

**Consequence:** the default is `go_live=False`. A misconfigured deployment sends
nothing rather than sending everything.

### 4. `payload_safety` — credential egress

```python
detectors = sorted({f.detector for f in self._redactor.scan(request.payload) if f.is_secret})
if detectors:
    return CheckResult("payload_safety", CheckOutcome.BLOCK, ...)
```

**Defends against:** an agent that read a `.env` file, an error page, or a log
line and is about to paste it into a message. This is a realistic LLM failure
mode, not a hypothetical one.

**Note the asymmetry:** credential shapes *block*. Personal data does not — a
message to a prospect legitimately contains their phone number. PII redaction
applies to logs and evidence artifacts, not to the message itself. Conflating the
two would block the product's core action.
See `test_personal_data_alone_is_not_treated_as_a_secret`.

### 5. `suppression` — do-not-contact

**Defends against:** contacting someone who opted out, which in the US is a
regulatory matter and not merely rude.

**Why before quiet hours:** a suppressed contact is unreachable at every hour.
Reporting "quiet hours" first for someone who is permanently suppressed would be
technically true and actively misleading.

**Failure mode:** `is_suppressed` returns `True` when the identifier cannot be
normalized. An identifier that cannot be checked cannot be cleared.

### 6. `quiet_hours` — timing

**Defends against:** the 3am text. The window is expressed in the operator's
timezone via `operator_utc_offset_hours`, and wraps midnight (`21:00–08:00` is
one window, not two).

### 7. `budget` — volume

**Defends against:** a loop bug turning into a thousand messages. A consequential
action with no configured budget is **denied**, not treated as unlimited — the
absence of a limit is the most dangerous possible default here.

**Spend is recorded on `commit`,** after the action actually happened, so denied
and simulated requests cost nothing.

### 8. `approval` — human in the loop

The only check that can return `REQUIRE_APPROVAL`, and therefore the only one
that produces a verdict other than allow or deny.

| Situation | Outcome | Why |
| --- | --- | --- |
| No token | `REQUIRE_APPROVAL` | Nobody has been asked yet |
| Valid token | `PASS` | |
| Wrong target | `BLOCK` | Attempted replay against a different person |
| Wrong action type | `BLOCK` | Attempted scope escalation |
| Expired | `BLOCK` | The approval was for a moment that has passed |
| Forged signature | `BLOCK` | |

The distinction between the first row and the rest is the interesting one. A
missing approval is a normal state in the workflow. A *wrong* approval is an
attempted bypass, and treating it as "just needs approval" would let a caller
retry until something stuck.

**Why last:** an operator should never be asked to approve an action that would
have been denied for another reason anyway.

---

## Approval tokens

```
token = base64url(action_type|target_digest|approver|expiry) + "." + HMAC-SHA256(payload)
```

The secret belongs to the approval surface — the operator's chat client
integration — and not to the agent runtime. That split is what makes the token
mean anything. A boolean `approved=True` field on a request is not an approval,
because the thing requesting permission can set it.

Verification order in [`verify`](../../src/stormbot/governance/approvals.py) is
deliberate: **signature first, then scope, then expiry.** Checking expiry before
the signature would let an attacker distinguish a forged token from a merely
expired one by timing the response, which leaks whether a valid token for that
scope was ever issued.

Comparisons use `hmac.compare_digest`, including the scope comparisons.

---

## What the audit trail contains

```python
{
    "verdict": "DENY",
    "action_type": "outreach.send_sms",
    "target_digest": "c0fa3e2c...",  # HMAC digest, not a phone number
    "decided_at": "2026-09-08T14:00:00+00:00",
    "checks": [
        {"check_id": "suppression", "outcome": "BLOCK", "detail": "target is suppressed (opt_out)"},
        ...,
    ],
}
```

No raw contact identifier. No payload. The trail is complete enough to explain
any decision and useless as a data source — which matters, because an audit log
is the most-copied, least-guarded artifact in most systems. It gets tailed into
terminals, shipped to log aggregators, and pasted into tickets.

`test_log_record_contains_no_raw_target_and_no_payload` enforces it.

---

## Failure modes, on purpose

| Situation | Behaviour |
| --- | --- |
| A check raises | `CheckOutcome.ERROR`, which is blocking → `DENY` |
| Suppression backend unavailable | `DENY` (the raise is caught as an error outcome) |
| Target identifier unparseable | `DENY` before any other check runs |
| Action type unknown | `DENY` |
| Consequential action with no budget configured | `DENY` |
| Approval secret misconfigured | Signature fails → `DENY` |
| Policy misconfigured (`consequential ⊄ allowed`) | `ValueError` at construction, before any request is served |

There is no configuration of this module that fails open. That is the claim, and
`test_a_check_that_raises_denies_rather_than_allows` is the test that would break
if someone made it untrue.

---

## Extending it

Adding a check means adding a method to `ExecutionGovernor` and listing it in the
tuple inside `_run_checks`. Three rules:

1. **Return, don't raise.** A raise becomes `ERROR`, which is correct behaviour
   for a bug but a poor way to express a policy decision.
2. **Skip explicitly, with a passing result.** Non-consequential actions return
   `PASS` with a detail saying why the check did not apply. A check that silently
   omits itself from the trail makes the trail incomplete.
3. **Take the digest, not the target.** Check methods receive `target_digest`
   precisely so a new check does not casually start logging phone numbers.

The [CI policy](../assurance/RELEASE_ASSURANCE.md#merge-policy) blocks any change
under `src/stormbot/governance/` that arrives without a test change.

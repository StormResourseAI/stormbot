# Runbook

Operating the governance controls. Written for the person on the other end of a
notification at an inconvenient hour, so each section leads with the action.

---

## Stop everything

```python
policy = replace(current_policy, kill_switch_engaged=True)
```

`kill_switch` is check 2 of 8 and applies to every action type including
non-consequential ones. It blocks even a fully approved request — there is
[a test](../../tests/governance/test_execution_governor.py) for exactly that,
because "the kill switch works unless someone already approved the thing" is not
a kill switch.

Use it when you do not yet know what is wrong. Diagnosis is a separate activity
from stopping, and doing them in the wrong order is how a five-minute incident
becomes a fifty-minute one.

**Narrower alternatives**, when you do know what is wrong:

| Action | Effect |
| --- | --- |
| `go_live=False` | Blocks consequential actions; drafting and internal work continue |
| Remove one action type from `allowed_actions` | Blocks that capability only |
| Set `daily_budget[action] = 0` | Stops that action without changing the allowlist |

---

## Daily posture check

```console
make gate     # release gate under the deployment policy
make test     # 141 tests, ~0.15s
make audit    # lockfile drift
```

Any non-`pass` verdict from the gate means a product claim and its evidence have
diverged. That is not a build problem to be worked around; it means something the
system says about itself has stopped being true, and the fix is either the code
or the claim.

---

## Suppression

**Add an opt-out:**

```python
registry.suppress("+18135550142", reason="opt_out", source="sms_stop_keyword")
```

Valid reasons: `opt_out`, `complaint`, `bounce`, `litigation_hold`,
`manual_operator`, `regulatory`. An unrecognized reason raises rather than being
stored as free text, so the field stays aggregatable.

**Check one contact:**

```python
registry.is_suppressed("(813) 555-0142")  # format does not matter
registry.reason_for("+18135550142")
```

**Export for an audit or a vendor:**

```python
registry.export()
# [{"digest": "...", "reason": "opt_out", "source": "...", "suppressed_at": "..."}]
```

The export contains no phone numbers or email addresses and is safe to attach to
a ticket.

**Removing a suppression** is deliberately not supported by this interface. If
someone re-consents, that is a new consent event and belongs in whatever system
records consent — not a deletion from the do-not-contact list. Reversing an
opt-out should require more ceremony than a method call.

---

## Rotate the suppression key

**Read this before you rotate, not during.** Digests are keyed, so a new key
produces different digests for the same people. Every existing entry stops
matching, and everyone on the list becomes reachable again.

This is the accepted cost of not storing raw identifiers
([ADR-0007](../adr/0007-keyed-digest-suppression.md)), and it forces one
operational rule:

> **The system of record for opt-outs lives outside this registry.** The registry
> is an enforcement index built from that record, not the record itself.

Rotation procedure:

1. Confirm you can re-derive the full list from the source of record. If you
   cannot, **stop** — rotating will silently discard the list.
2. Engage the kill switch. A partially rebuilt index is worse than no index,
   because it looks like one.
3. Build the new registry with the new key and replay every opt-out from the
   source of record.
4. Reconcile counts: the new registry's length must equal the source record's
   count of active opt-outs. A mismatch means an entry failed to normalize.
5. Swap the registry, then release the kill switch.

Treat the key as a long-lived secret and back it up accordingly. Losing it is not
a credential incident that rotation fixes — it means rebuilding the index from
the source of record, which is only possible if step 1 was true all along.

---

## Approvals

**Issue one:**

```python
token = approvals.issue(
    action_type="outreach.send_sms",
    target_digest=suppression.digest_for(target),
    approver="brian",
    ttl=timedelta(minutes=30),
)
```

**A token cannot be revoked.** Keep TTLs short — 15 to 30 minutes is a reasonable
default. If a token is believed compromised, rotate the approval secret, which
invalidates every outstanding token at once. That is blunt, and it is the only
lever available; see [ADR-0004](../adr/0004-scoped-approval-tokens.md).

**Rotating the secret** invalidates outstanding approvals. Do it during a quiet
window or expect a batch of `REQUIRES_APPROVAL` verdicts.

---

## Reading a denial

Every decision carries the full check trail, not just the first failure.

```json
{
  "verdict": "DENY",
  "action_type": "outreach.send_sms",
  "target_digest": "c0fa3e2c3f366c58...",
  "checks": [
    {"check_id": "known_action", "outcome": "PASS", "detail": "action type is allowlisted"},
    {"check_id": "suppression", "outcome": "BLOCK", "detail": "target is suppressed (opt_out)"},
    {"check_id": "budget", "outcome": "PASS", "detail": "within daily budget (3/25)"}
  ]
}
```

| Outcome | Meaning | Usual response |
| --- | --- | --- |
| `BLOCK` | A policy rule was violated | Working as intended; investigate why the agent proposed it |
| `ERROR` | The check itself raised | **Investigate immediately** — a dependency is failing and the system is denying by default |
| `REQUIRE_APPROVAL` | Waiting on a human | Normal for consequential actions |

`ERROR` deserves a note. The system is safe — errors deny — but it is safe by
accident of the fallback rather than by working correctly, and a suppression
backend that is failing closed today is a suppression backend that is failing.

---

## Budgets

```python
governor.spend_today("outreach.send_sms", now)  # 12
```

Spend is recorded on `commit`, after a real send, so denials and rehearsals do
not consume quota.

**Budget exhausted mid-day?** Ask why before raising it. The daily cap exists to
turn a runaway loop into 25 wasted messages instead of 10,000, and raising it
during an incident removes the control at the moment it is doing its job.

**Caveat:** budget state is in memory and per-process. Across multiple workers
the effective cap is the configured value times the worker count. See
[ADR-0006](../adr/0006-in-memory-budget-state.md).

---

## Quiet hours

```python
GovernorPolicy(quiet_hours=(21, 8), operator_utc_offset_hours=-4, ...)
```

Windows crossing midnight are handled (`start > end`). Setting `start == end`
disables the check entirely rather than blocking for 24 hours, which is the less
surprising of the two possible readings.

Messages proposed during quiet hours are denied, not queued. Queuing would mean
holding a message whose approval will have expired by the time the window opens,
and delivering a message the operator approved eleven hours ago is a different
action from the one they approved.

---

## Adding a capability

Order matters — this is the sequence, and doing it backwards makes the gate tell
you so.

1. Write the code.
2. Write the tests, including the negative ones.
3. Add the capability to `assurance/ai_capabilities.json` with its risk tier and
   human-in-the-loop requirement.
4. Add evidence records in `assurance/evidence/` pointing at the tests.
5. Add the action type to `GovernorPolicy.allowed_actions`, and to
   `consequential_actions` if it reaches a third party.
6. Set a daily budget if it is consequential — without one it is denied.
7. Add or update the product claim.
8. `make gate`.

---

## Dependency updates

Dependabot opens the version bump. The lockfile check fails until both platform
lockfiles are regenerated with real hashes — see
[DEPENDENCY_MANAGEMENT.md](DEPENDENCY_MANAGEMENT.md). This is intentional: an
automated bump should not be able to weaken the pinning it is bumping.

---

## When something has already gone out

See [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md). Stop first, using the kill
switch above, then work the relevant playbook.

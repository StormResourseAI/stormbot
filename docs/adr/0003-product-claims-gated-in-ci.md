# ADR-0003 — Product claims are registry entries gated in CI

**Status:** Accepted · **Date:** 2026-09-06

## Context

A product page says: *an operator approves every message before it sends.*

That is an assertion about program behaviour. It has a truth value. And it lives
in a CMS, maintained by whoever last edited the copy, verified by nobody.

The gap opens gradually and invisibly. A refactor makes approval optional for one
channel. A performance fix adds a fast path. Every change is individually
defensible; nobody re-reads the marketing copy afterward; the sentence quietly
becomes false and stays that way until a customer, an auditor, or a regulator
finds out.

Meanwhile the same organization enforces type signatures on every merge.

## Decision

Product claims become schema-validated artifacts in the repository, each one
naming the capabilities it depends on and the evidence supporting it. CI resolves
every active claim against an evidence ledger and fails the build when a claim
outruns its evidence.

```json
{
  "id": "claim.approval_before_contact",
  "statement": "No message reaches a real person until a human operator has approved that specific message for that specific recipient.",
  "customer_facing": true,
  "capability_refs": ["governance.execution_governor", "governance.approval_tokens"],
  "evidence_refs": ["ev.execution_governor.tests", "ev.approval_tokens.tests"],
  "required_state": "TESTED",
  "status": "active"
}
```

Ten checks, of which two carry the weight: `claim-evidence-sufficiency` stops a
claim from outrunning its evidence, and `declared-state-honesty` stops the
registry from manufacturing that evidence by editing a field. Either one alone is
defeatable.

Three policies — `advisory`, `deployment`, `certification` — apply the same checks
at different evidence floors.

## Consequences

**Good.** Deleting the test that proves opt-out survives reformatting fails the
build on `claim-evidence-sufficiency` — not because a test went missing, but
because a promise stopped being true. Claims get a review cadence, an owner, and
a retirement path. Writing the claim before the evidence produces an immediate,
specific error, which is the system telling you the sentence is not true yet.

**Costs.** Real bookkeeping: a new capability means a registry entry, evidence
records, and a claim. Registry maintenance is a new failure mode, and a stale
registry is a gate that checks stale things. There is a persistent temptation,
when the gate is red at an inconvenient time, to fix the registry rather than the
code — the [incident playbook](../operations/INCIDENT_RESPONSE.md) names that
explicitly as the thing not to do.

**The limit.** This resists carelessness, not a determined committer. Someone with
merge rights willing to edit the test, the registry, and the evidence together can
produce a green build for a false claim. The control makes that require
deliberate, visible, reviewable effort rather than one field edit, which is the
realistic bar for a process control.

## Alternatives considered

**Acceptance tests named after claims.** Genuinely good, and closer to the code.
Rejected as insufficient alone because it has no notion of evidence *state* — a
test can exist, be skipped, and still look like coverage — and because it offers
nowhere to record that a claim is customer-facing, who owns it, or when it was
last reviewed.

**A compliance spreadsheet.** The usual answer. It is not in the repository, so it
does not move with the code, and nothing fails when it becomes wrong.

**Documentation review in the PR template.** A checkbox is a reminder. The PR
template here still has one, but as a prompt to think before CI does, not as the
control.

**Runtime assertions.** Some claims can be asserted at runtime, and that is worth
doing. But it catches the violation after the build shipped, which for a claim
about not contacting people is after somebody was contacted.

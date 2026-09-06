# ADR-0004 — Approvals are scoped, signed, expiring tokens

**Status:** Accepted · **Date:** 2026-09-06

## Context

Human-in-the-loop is the headline safety property of an outreach agent: a person
approves each message before it goes out. The naive encoding is a flag:

```python
ActionRequest(..., approved=True)
```

The problem is who sets it. The agent runtime constructs the request, so the
agent can set the flag. The control it is supposed to represent — a human made a
decision — is not represented at all.

A shared secret checked at the boundary fixes forgery and leaves two holes. An
approval for one recipient can be replayed against another, because the token
says nothing about who it was for. And an approval granted this morning is still
valid tonight, because it says nothing about when.

Those matter because of what an approval actually is. An operator reading a
drafted message and tapping approve is making a claim about *that message*, *that
recipient*, and *right now*.

## Decision

Tokens are HMAC-SHA256 signed over their own scope:

```
base64(action_type | target_digest | approver | expiry) . hmac_sha256(payload)
```

Verification checks the signature **first**, then scope, then expiry, so a forged
token and an expired one are not distinguishable by response timing. Scope
comparisons use `hmac.compare_digest` for the same reason.

The signing secret belongs to the approval surface — the operator's chat bot —
not to the agent runtime. That split is what makes the token mean anything.

The target is identified by its suppression digest rather than its raw value, so
the token can be logged and passed around without carrying a phone number.

## Consequences

**Good.** The agent cannot mint an approval. A token for Dana cannot be replayed
against Marco, and the governor treats a wrong-target token as `DENY` rather than
merely unapproved — a wrong-target token is an attempted bypass, not an absence.
Tokens are stateless, so verification needs no store and no network call. Short
TTLs bound the damage of a leaked token.

**Costs, and one of them is significant.**

**There is no revocation.** A leaked token is valid until it expires. The only
lever is rotating the secret, which invalidates every outstanding approval at
once. A revocation list would fix it and would reintroduce shared state on the
verification path, which is the thing statelessness bought. For 15-to-30-minute
TTLs the trade favours statelessness; for hour-long approvals it would not.

Clock skew between issuer and verifier shifts the effective window. The approver
name is inside the signed payload but is not verified against any identity
system — this component authenticates the *approval*, not the *approver*, and who
may hold the secret is upstream and out of scope. And the operator surface
becomes a high-value target, since it holds the key to every approval.

## Alternatives considered

**Boolean flag.** Forgeable by the component asking for permission. Not a control.

**Approval record in a database.** Revocable, auditable, and the right answer once
approvals need to outlive a chat session. Rejected here for the state and the
lookup on every send, and because a reference implementation is clearer without a
storage dependency. This is the natural first extension.

**Signed JWT.** Same properties, standard tooling, plus a dependency, a
parser with a real CVE history, and the `alg: none` family of footguns. For a
token with four fields, 130 lines of HMAC has a smaller attack surface than a
JWT library. See [ADR-0005](0005-zero-runtime-dependencies.md).

**Per-message nonce consumed on use.** Prevents replay of a token against the
same target twice, which HMAC scoping does not. Requires shared state. Worth
adding alongside a database-backed approval record, not instead of scoping.

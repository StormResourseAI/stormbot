# ADR-0001 — One fail-closed governor that decides but cannot act

**Status:** Accepted · **Date:** 2026-09-06

## Context

An agent that can send SMS, email prospects, or charge a card needs authorization
checks. The obvious implementation is to put them where the action happens:

```python
def send_sms(target, body):
    if not suppression.is_suppressed(target):
        if within_budget("sms"):
            provider.send(target, body)
```

This works, and it degrades in a specific way. A second send path appears for a
different channel. Someone adds a bulk variant. A retry helper calls the provider
directly. Each one is individually reasonable, and each is a chance to omit a
check. The set of checks is now a convention distributed across call sites, and
conventions are audited by reading every call site.

## Decision

One component owns the entire ordered pipeline and returns a verdict rather than
performing the action.

```python
decision = governor.evaluate(request)  # pure
if decision.allowed:
    provider.send(...)  # the caller sends
    governor.commit(request, decision)
```

Four rules, each with a test:

1. **Default deny.** An action type not on the allowlist is denied.
2. **Decide, don't act.** The governor holds no provider client.
3. **Every check runs.** No short-circuit on the first block.
4. **An exception is a denial.** Every check runs inside a `try`; `ERROR` is
   treated identically to `BLOCK`.

## Consequences

**Good.** The audit surface is one function. "Is every check applied?" is
answered by reading `_run_checks` rather than by finding every send site. The
decision is a pure value, so it can be logged, replayed, or diffed. Adding a
check is one function and one row in a trail, with no call-site changes.

**Costs.** Every caller must honour the verdict, and nothing forces it to — see
below. The full trail costs a few microseconds per decision, which is irrelevant
here and would not be at high volume. Policy becomes a single object that must be
constructed correctly at startup, which concentrates the configuration risk.

**The unresolved weakness.** `evaluate` returns a `Decision`; a caller can ignore
it. Keeping the send capability outside the governor makes the honouring
auditable — one return value, one dispatch site — but it is enforced by code
review, not by the type system.

The stronger design hands back a capability object that *is* the only way to
send:

```python
permit = governor.evaluate(request)  # returns SendPermit | Denial
permit.dispatch(provider)  # Denial has no dispatch method
```

That was not adopted here because it couples the governor to the provider
interface, and for a reference implementation the simpler seam is more legible.
It is the first thing to change in a production adaptation, and the
[threat model](../security/THREAT_MODEL.md) names this as the weakest assumption
in the design.

## Alternatives considered

**Decorators on send functions.** Declarative and readable, but the decorator has
to be remembered, and the failure mode is silence — an undecorated function looks
completely normal.

**Middleware in the provider adapter.** Catches every send by construction, which
is genuinely better on that axis. Rejected because there is one adapter per
provider, so the policy fragments across them, and because the adapter has
already committed to sending by the time it runs.

**Policy engine (OPA/Rego).** Externalized, hot-reloadable, expressive. The right
answer at organizational scale where policy authors are not the engineers.
Rejected here because it adds a runtime dependency to the one component that
should not have one (see [ADR-0005](0005-zero-runtime-dependencies.md)) and moves
the logic somewhere a reviewer cannot see it in the same file as its tests.

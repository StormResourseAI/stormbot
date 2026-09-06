# ADR-0006 — Budget state is in memory, and that is a known defect

**Status:** Accepted, with a named limitation · **Date:** 2026-09-06

## Context

The daily budget turns a runaway loop into 25 wasted messages instead of 10,000.
It is the control that bounds the worst case, and the worst case is the one that
makes the news.

Implementing it requires a counter. A counter requires storage. Storage means a
database, a Redis instance, or a file — each of which brings a dependency, a
failure mode, a configuration surface, and a decision about what to do when it is
unavailable.

For a reference implementation whose purpose is to be read, that is a large
amount of infrastructure standing between a reader and the idea.

## Decision

Budget state lives in a dict on the governor instance:

```python
self._spend: dict[tuple[str, str], int] = {}  # (action_type, local_date) -> count
```

Spend is recorded in `commit`, after a real send, so a denial or a rehearsal does
not consume quota.

This ADR exists to record the limitation rather than to leave it implicit in the
code.

## Consequences

**Good.** The budget logic is eight lines and reads correctly. There is no
storage dependency, no configuration, and no "what if the store is down" branch.
The interface — `spend_today`, `commit` — is the same interface a durable
implementation would have.

**The defects, precisely.**

**It does not survive a restart.** A process restart resets the counter to zero.
An agent in a crash loop has an unbounded effective budget, which is exactly the
scenario the budget exists for. This is the worst of the three.

**It is per-process.** With four workers, the effective cap is four times the
configured value. Nothing warns about this; the number in the policy is simply
not the number that applies.

**It races.** The check is read-then-write with no lock. Two concurrent
evaluations can both observe 24 of 25 and both proceed.

## What a durable implementation needs

The fix is not a mutex. A lock makes the race disappear within one process and
leaves the other two defects untouched.

The correct shape is a database row per `(action_type, date)` with the increment
and the limit check in one atomic statement:

```sql
UPDATE budget_spend
   SET spent = spent + 1
 WHERE action_type = ? AND day = ? AND spent < ?
RETURNING spent;
```

No rows returned means the budget is exhausted. The database enforces the
invariant, so it holds across processes, restarts, and concurrent workers without
any coordination in application code.

Two further requirements follow. The store being unavailable must **deny**, not
default to allowing — which the existing error handling gives for free, since a
check that raises is a check that failed. And the increment must remain tied to a
confirmed send, so a provider timeout does not consume quota for a message that
never went out.

## Why publish it this way

Publishing the in-memory version with this ADR is more useful than publishing a
version with a database dependency, for two reasons.

The idea being demonstrated is *where the budget check sits in the pipeline and
when it is committed* — the ordering and the commit-after-send semantics. Both
survive the change to durable storage unchanged. The storage detail would add
setup for a reader without adding to the idea.

And a reference implementation that hides its limitations teaches the wrong
thing. Someone lifting this pattern into production needs to know that the
counter is the part to replace, and a paragraph in an ADR is more likely to reach
them than a code comment they will not scroll to.

## Alternatives considered

**A file-backed counter.** Survives restarts, still races, and adds file locking
and corruption handling. More code for a partial fix.

**Redis `INCR`.** Atomic, correct, and a service dependency plus a
connection-failure branch. This is the right answer in production; it is
infrastructure between a reader and a nine-line concept in a repository meant to
be read.

**Dropping the budget check entirely from the reference implementation.** Honest,
and it removes the most important bound on the worst case from a document about
bounding the worst case.

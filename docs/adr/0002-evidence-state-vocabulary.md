# ADR-0002 — A state vocabulary where words require proof

**Status:** Accepted · **Date:** 2026-09-06

## Context

"It's done" means at least six different things, and the speaker and the listener
routinely pick different ones. The code exists. It works with its neighbours. The
tests pass. A specific build was certified. That build shipped. It is running and
doing the thing.

The gap between "the tests pass" and "it is running in production and working" is
where most overclaiming lives, and almost none of it is deliberate. It is a
vocabulary problem: the language offers one word for six conditions, so people
use the one word.

A boolean `is_done` field has the same defect with worse ergonomics. A free-text
status field has it with more words.

## Decision

An explicit ladder, where each rung names the evidence kind that can promote a
subject onto it:

```
BUILT → INTEGRATED → TESTED → CERTIFIED → DEPLOYED → ACTIVE
```

Three rules:

1. **Contiguity.** A subject's state is the highest rung for which *every rung
   below it* also has evidence. Certification evidence with no test evidence
   proves nothing above `BUILT`.
2. **Build-specific evidence names the build.** `CERTIFICATION`, `DEPLOYMENT`,
   and `RUNTIME_PROBE` require a commit SHA, enforced in the constructor.
3. **Runtime evidence expires; source evidence does not.** A runtime probe is
   stale after 24 hours. A test run is a fact about a revision and does not decay
   on a clock.

Four states sit off the ladder — `UNKNOWN`, `PLANNED`, `BLOCKED`, `SUPERSEDED` —
and comparisons involving them return `False` rather than being ordered.

## Consequences

**Good.** `UNKNOWN` becomes a sayable answer rather than an admission, which is
most of the value: the vocabulary makes "we don't know" cheap. Status becomes
derived rather than asserted, so it cannot drift from reality without the
evidence drifting too. `ACTIVE` decays on its own, so a dashboard cannot claim
liveness on the strength of a week-old probe.

**Costs.** Every capability needs three evidence records to reach `TESTED`, which
is real bookkeeping — this repository carries 24 records for 8 capabilities. The
ladder is opinionated: a team that certifies before integrating has to either
reorder its process or fork the ladder. And contiguity produces results that look
wrong at first glance, since something genuinely deployed but untested reports as
`BUILT`. That is the intent, and it surprises people.

**The honest outcome.** Applied to this repository, every capability is `TESTED`
and nothing is higher, because there is no certification, deployment, or runtime
evidence. Applied to the private system in
[PRODUCTION_EVIDENCE.md](../PRODUCTION_EVIDENCE.md), four of six rows come back
`UNKNOWN` or `NEEDS_LATER_VERIFICATION`. A vocabulary that produced six "yes"es
would not have been worth building.

## Alternatives considered

**Semantic versioning.** Answers "what changed", not "how well is it known to
work". Orthogonal, not a substitute.

**Deployment-tool status.** Accurate about deployment and silent about everything
else. `DEPLOYED` is one rung of six, and it is not the one people overclaim.

**Test coverage percentage.** A number about lines, not about whether a specific
claim is supported. Coverage cannot tell you that the opt-out promise is tested;
an evidence record pointing at the test can.

**Free-text status in a spreadsheet.** The status quo almost everywhere. It works
until someone needs it to be true.

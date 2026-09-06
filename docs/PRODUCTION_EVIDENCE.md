# Production evidence

The patterns in this repository were extracted from a private production system.
This page records what that system measures, where the numbers come from, and —
more usefully for a reviewer — the several things they do **not** establish.

Every metric below is stated with its provenance. Where a number cannot support
a conclusion, the conclusion is not drawn.

---

## Provenance

| Field | Value |
| --- | --- |
| Source | Static, read-only analysis of a private repository snapshot |
| Method | `git ls-files`, `git log`, `git rev-list`, line counts, pattern counts |
| Date of measurement | 2026-09-06 |
| Code executed | None. No test run, no server, no provider call, no database access |
| Relationship to this repository | None of that code is here. This repository is a clean-room reimplementation of the patterns |

The distinction in the last row matters and is worth being blunt about: **no
production code, data, configuration, or commit history was copied into this
repository.** Everything under `src/` and `tests/` here was written from scratch
for publication. The numbers below are context for why these patterns exist, not
a description of the files you are reading.

---

## Scale

| Metric | Value |
| --- | --- |
| Tracked files | 1,785 |
| Python files | 1,204 |
| Total tracked Python lines | 382,807 |
| Application code | 218,763 lines across 443 files |
| Test code | 128,540 lines across 594 files |
| Files matching `test_*.py` | 549 |
| Discrete test functions | 5,816 |
| Shell scripts | 95 |
| Markdown documentation | 317 files, 37,771 lines |
| Commits on `HEAD` | 522 |
| Merge commits | 68 |
| Active window | 2026-02-16 → 2026-09-06 (~6.7 months) |

**What this supports:** roughly one line of test code for every 1.7 lines of
application code, sustained across a six-month window. That ratio is the single
most defensible quality signal in the measurement, because it is hard to fake
incidentally.

**What it does not support:** any statement about whether those 5,816 tests
pass. See [the honest gap](#the-honest-gap), below.

---

## Cadence

| Month | Commits |
| --- | --- |
| 2026-02 | 82 |
| 2026-03 | 54 |
| 2026-04 | 92 |
| 2026-05 | 5 |
| 2026-06 | 26 |
| 2026-07 | 60 |
| 2026-08 | 131 |
| 2026-09 (partial) | 72 |

The shape is the interesting part, not the total. A visible dip in May and
re-acceleration through August reads as work that competed with other work and
then resumed — the pattern of a system being used, rather than a repository
assembled for display, which tends to show one burst and a flat line.

---

## Architecture

The service layer dominates, with a separate cross-cutting layer for the
concerns that do not belong to any single feature:

| Layer | Share of application files | Role |
| --- | --- | --- |
| Services | ~50% | Business logic |
| Cross-cutting runtime ("OS") layer | ~17% | Evaluations, agent supervision, security, workflows, memory, lifecycle, telemetry |
| API routers | ~12% | Transport, cleanly separated from services |
| Persistence | ~9% | Includes numbered migrations |
| Agents | ~4% | Including a dedicated safety module |
| Execution plumbing | remainder | Tools, workers, scheduler, executor |

Two observations a reviewer can draw from the distribution:

**The layering is real, not incidental.** A router layer, a large service layer,
a migration-managed persistence layer, and a separate cross-cutting layer is a
coherent structure rather than a flat directory that grew.

**The AI components were treated as things requiring measurement and policy.**
The cross-cutting layer's largest subdirectory is evaluations, and it contains a
policy-as-code security area. That is a different posture from calling a model
API and shipping the response.

---

## What became this repository

| Production pattern | Reimplemented here as |
| --- | --- |
| Go-live gate and execution governor | [`governance/governor.py`](../src/stormbot/governance/governor.py) |
| Operator approval gateway | [`governance/approvals.py`](../src/stormbot/governance/approvals.py) |
| Contact suppression service | [`governance/suppression.py`](../src/stormbot/governance/suppression.py) |
| Outbound credential scanning | [`governance/redaction.py`](../src/stormbot/governance/redaction.py) |
| Test/production database guard | [`governance/db_guard.py`](../src/stormbot/governance/db_guard.py) |
| Capability and product-claim registries | [`assurance/`](../assurance/) |
| Release gate and CI policy tooling | [`assurance/release_gate.py`](../src/stormbot/assurance/release_gate.py), [`ci_policy.py`](../src/stormbot/assurance/ci_policy.py) |
| Evidence-state vocabulary | [`assurance/evidence.py`](../src/stormbot/assurance/evidence.py) |

The reimplementations are smaller, more opinionated, and better tested per line
than their originals. That is what a reference implementation is for: it exists
to make the idea legible, not to carry six months of production requirements.

---

## The honest gap

The private system's CI runs a **focused subset** of its test suite — roughly
fifteen files out of 549 — chosen as contract tests plus release-assurance lanes
to fit a bounded CI budget. That is a defensible engineering trade, and it is
also a hard limit on what may be claimed.

| Permitted | Not permitted |
| --- | --- |
| "Focused contract and release-assurance gates are enforced in CI" | "The test suite runs in CI" |
| "5,816 test functions exist as tracked source" | "5,816 tests pass" |
| "A certification process exists and is attested to exact SHAs" | "The system is certified" |

**In this repository the stronger statement is available:** 141 test functions
across 14 modules, and CI runs all of them on three interpreter versions. That is
achievable because this repository is 2,374 lines, and it is stated as a fact
about this repository rather than an implication about the other one.

---

## Evidence-state ledger for the private system

Applying [the same vocabulary](assurance/EVIDENCE_STATES.md) this repository
uses, to the measured facts:

| State | Verdict | Basis |
| --- | --- | --- |
| `BUILT` | **Yes** | 1,785 tracked files, 522 commits, 382,807 tracked Python lines |
| `INTEGRATED` | **Yes** | 68 merge commits across dated feature branches |
| `TESTED` | **Not established** | 5,816 test functions exist as source. No test was executed during measurement. The existence of a test is not evidence that it passes |
| `CERTIFIED` | **Not established** | A certification process and certified branch class exist, but certification is an attestation to an exact SHA, not a property of a repository listing |
| `DEPLOYED` | **Unknown** | Requires runtime evidence, which static analysis cannot produce |
| `ACTIVE` | **Unknown** | Same |

Three of six rows are "not established" or "unknown", and they stay that way
until someone produces the evidence. That is the vocabulary working. A summary
that rounded these up to "production system, fully tested and certified" would be
the exact failure mode the ladder exists to prevent — and it would be
indistinguishable, to a reader, from every other portfolio claim that does the
same thing.

# Architecture decision records

Seven decisions, each with the alternatives that were rejected and the cost that
was accepted. An ADR with no cost section is a sales page — if a decision had no
downside it did not need a record.

| # | Decision | The cost |
| --- | --- | --- |
| [0001](0001-fail-closed-execution-governor.md) | One fail-closed governor that decides but cannot act | Callers must honour the verdict, and nothing forces them to |
| [0002](0002-evidence-state-vocabulary.md) | A state vocabulary where words require proof | Three evidence records per capability, and results that look wrong at first glance |
| [0003](0003-product-claims-gated-in-ci.md) | Product claims are registry entries gated in CI | Registry maintenance, plus the temptation to fix the registry instead of the code |
| [0004](0004-scoped-approval-tokens.md) | Approvals are scoped, signed, expiring tokens | No revocation — a leaked token is valid until it expires |
| [0005](0005-zero-runtime-dependencies.md) | Zero runtime dependencies | A hand-rolled JSON Schema validator, and `unittest` instead of `pytest` |
| [0006](0006-in-memory-budget-state.md) | Budget state is in memory | It does not survive a restart, is per-process, and races |
| [0007](0007-keyed-digest-suppression.md) | Keyed digests for the do-not-contact list | Rotating the key invalidates the whole list |

ADR-0005 and ADR-0006 are the two worth reading if you only read two. ADR-0005 is
a choice that does not generalize and says so; ADR-0006 documents a defect rather
than hiding it.

## Format

Context, Decision, Consequences (including costs), Alternatives considered.
Status is `Accepted`, `Superseded by ADR-NNNN`, or `Rejected`. Superseded records
stay in place — the reasoning that turned out to be wrong is usually the more
instructive half.

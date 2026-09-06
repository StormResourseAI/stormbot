# Release assurance

How a claim about the system becomes something CI can check, and what happens
when it stops being true.

---

## The registries

Three documents under [`assurance/`](../../assurance/), each validated against a
JSON Schema on every run.

### `ai_capabilities.json` — what the system can do

```json
{
  "id": "governance.execution_governor",
  "title": "Fail-closed action authorization",
  "description": "Evaluates every proposed real-world action against an ordered policy pipeline...",
  "risk_tier": "high",
  "human_in_the_loop": "required",
  "approval_gate": "operator.scoped_approval_token",
  "evidence_state": "TESTED",
  "owner": "platform",
  "last_reviewed": "2026-09-06"
}
```

`evidence_state` is a *declaration*, and the gate does not trust it. The
`declared-state-honesty` check compares it against the ledger and fails if the
declaration is higher. Without that check the registry could promote itself and
the mechanism would be decorative.

### `product_claims.json` — what the system says about itself

```json
{
  "id": "claim.opt_out_is_enforced",
  "statement": "Once someone opts out, the system will not contact them again, regardless of how their phone number or email address is formatted on a later import.",
  "customer_facing": true,
  "capability_refs": ["governance.contact_suppression", "governance.execution_governor"],
  "evidence_refs": ["ev.contact_suppression.tests", "ev.execution_governor.tests"],
  "required_state": "TESTED",
  "status": "active",
  "last_reviewed": "2026-09-06"
}
```

`statement` is written in the words a customer would read, not implementation
terms. That is enforced:
`test_every_customer_facing_claim_is_written_in_plain_language` fails a claim
containing `src/`, `.py`, `HMAC`, or similar. A claim a customer cannot read is a
claim nobody will notice going stale.

`customer_facing` raises the evidence floor. Internal claims are held to
`required_state`; customer-facing ones are additionally held to the policy floor.

### `evidence/*.json` — dated proof

```json
{
  "id": "ev.contact_suppression.tests",
  "kind": "TEST_RUN",
  "subject": "governance.contact_suppression",
  "recorded_at": "2026-09-06T00:00:00Z",
  "detail": "Tests asserting normalization equivalence and that no raw identifier appears in an export.",
  "artifact_uri": "tests/governance/test_contact_suppression.py"
}
```

`CERTIFICATION`, `DEPLOYMENT`, and `RUNTIME_PROBE` records additionally require
`commit_sha`, enforced in `EvidenceRecord.__post_init__` rather than in the
schema: a claim about a build that does not identify the build is not evidence.

`artifact_uri` must resolve to a real path —
`test_every_evidence_artifact_actually_exists_in_the_repository` fails when a
file is renamed and the evidence pointer is left dangling. An evidence pointer
into a deleted file is worse than no pointer, because it looks like proof.

---

## The ten checks

| # | Check | Severity | Fails when |
| --- | --- | --- | --- |
| 1 | `registry-schema` | blocking | A registry violates its JSON Schema |
| 2 | `capability-refs-resolve` | blocking | A claim names a capability that does not exist |
| 3 | `evidence-refs-resolve` | blocking | A claim names an evidence record that does not exist |
| 4 | `claim-evidence-sufficiency` | blocking | An active claim's `required_state` exceeds what the ledger supports |
| 5 | `customer-facing-floor` | blocking | A customer-facing claim falls below the policy's floor |
| 6 | `declared-state-honesty` | blocking | A capability declares a state the ledger cannot support |
| 7 | `hitl-approval-gate` | blocking | A capability requires a human but names no approval gate |
| 8 | `no-blocked-capabilities` | blocking | An active claim depends on a `BLOCKED` capability |
| 9 | `review-recency` | advisory | A registry entry has not been reviewed in 180 days |
| 10 | `orphan-capabilities` | advisory | A capability is referenced by no claim |

Checks 4, 5, and 6 are the substance. The rest are referential integrity, which
matters mainly because without it the substantive checks can be defeated by a
typo.

---

## Policies

| Policy | Customer-facing floor | Blocking enforced | Used for |
| --- | --- | --- | --- |
| `advisory` | `BUILT` | No — everything downgraded to a warning | Local development; seeing the full finding set without being blocked |
| `deployment` | `TESTED` | Yes | Every push and pull request |
| `certification` | `CERTIFIED` | Yes | Promoting a build to certified |

The same ten checks, judged at different strictness. **`certification` currently
fails in this repository, by design** — nothing here has evidence bound to an
exact commit SHA, so nothing is certified, and the gate says so rather than
rounding up. `make certify` demonstrates it.

A gate that only ever passes teaches everyone to ignore it.

---

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | pass |
| `1` | warn — advisory findings only |
| `2` | fail — at least one blocking violation |
| `3` | **the gate failed to run** — this is not a verdict |

The workflow handles this explicitly rather than relying on `set -e`:

```bash
set +e
python -m stormbot.assurance.release_gate --policy deployment ... 
code=$?
set -e

if [ "$code" -gt 2 ]; then
  echo "::error::release gate failed to execute (exit ${code})"
  exit "$code"
fi
```

A missing registry file, unparseable JSON, or a schema file that has been deleted
all produce exit 3. A schema *violation* produces a verdict, because that is a
policy finding about a document the gate successfully read. The distinction is
maintained in [`registry.py`](../../src/stormbot/assurance/registry.py): parse
failures raise `RegistryLoadError`; schema errors are collected and returned.

---

## The report

The gate emits JSON conforming to
[`release_gate.schema.json`](../../assurance/schemas/release_gate.schema.json),
uploaded as a CI artifact with `if-no-files-found: error`:

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-09-06T12:00:00Z",
  "policy": "deployment",
  "target": "9f1c2ab...",
  "compare_to": "3d4e5f6...",
  "verdict": "pass",
  "summary": { "total_checks": 10, "passed": 10, "warned": 0, "failed": 0 },
  "checks": [ { "id": "registry-schema", "status": "pass", "severity": "blocking", "detail": "...", "subjects": [] } ]
}
```

A verdict that only exists in log scrollback cannot be audited three months
later, which is exactly when someone asks. `test_the_published_artifact_conforms_to_its_own_schema`
validates the artifact against the published schema, so the audit trail is
guaranteed parseable by whatever reads it next.

---

## Merge policy

The gate answers "is the registry consistent with the evidence?". That is not
"should this pull request merge?", and conflating them produces a gate that is
too loud on a typo fix and too quiet on a change to the code that decides whether
to text a stranger.

[`ci_policy.py`](../../src/stormbot/assurance/ci_policy.py) reads the verdict
alongside the changed-file set:

```
governed  = src/stormbot/governance/ · src/stormbot/assurance/ · assurance/ · .github/workflows/
tests     = tests/
docs      = docs/ · examples/ · *.md · *.rst · *.txt
```

| Situation | Decision |
| --- | --- |
| Gate `fail` | Block, always |
| Gate `warn`, governed surface touched | Block — advisory findings escalate on governed changes |
| Gate `warn`, documentation only | Allow, with a note |
| Gate `pass`, governed surface touched, no test change | **Block** |
| Gate `pass`, governed surface touched, tests changed | Allow |

That fourth row is the opinionated one. A green gate is not permission to edit
safety-critical code without touching a test. The rule classifies `tests/` before
`src/stormbot/governance/`, so adding a test for governance code never blocks
itself — see `test_a_test_file_under_a_governed_name_still_counts_as_a_test`.

Exit codes are `0` (allow) and `1` (block); a gate report that cannot be read
exits `2`, because "I could not evaluate the policy" is not "the policy passed".

---

## Adding a claim

1. Add the capability to `ai_capabilities.json` with the state you can *prove*,
   not the state you expect to reach.
2. Add evidence records to `assurance/evidence/`, one per rung, each with an
   `artifact_uri` pointing at something that exists.
3. Add the claim to `product_claims.json`, in plain language, referencing both.
4. Run `make gate`.

If the gate fails, the claim is ahead of the work. That is the mechanism doing
its job, and the fix is to write the test rather than to lower `required_state`.

---

## Where this stops

The gate checks that a claim has evidence of a given *kind*. It cannot check that
the evidence is *good* — that a `TEST_RUN` record points at a test that
meaningfully exercises the capability rather than asserting `True`. That gap is
covered by human review, and pretending otherwise would be exactly the kind of
overclaiming this whole mechanism exists to prevent.

What it does buy: the claim, the capability, and the evidence move together or
not at all, and the failure is loud.

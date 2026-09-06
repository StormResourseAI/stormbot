# Reviewer guide

A guided path for someone evaluating this repository as engineering evidence.
Each stop names the question the file answers and what would make you doubt it.

---

## Before anything else: make it run

```console
make test     # 141 tests, ~0.15s, nothing to install
make gate     # release gate, deployment policy — passes
make certify  # release gate, certification policy — fails, by design
make audit    # lockfile drift
```

If `make test` needs a `pip install`, something is wrong: the runtime and the
suite are standard-library only, and
[`tests/contract/test_hermeticity.py`](../tests/contract/test_hermeticity.py)
enforces it by parsing every import in the tree.

---

## Five minutes: the two ideas

**1. [`src/stormbot/governance/governor.py`](../src/stormbot/governance/governor.py)**

The question: *how do you stop an autonomous agent from doing something
irreversible?*

Read the module docstring, then `evaluate` and `_run_checks`. Four properties to
verify for yourself:

- The allowlist is checked first and an unknown action type is denied. Adding a
  tool does not add a capability.
- The pipeline runs every check rather than short-circuiting, so a denial comes
  with a complete trail.
- `_run_checks` wraps each check and converts an exception into `CheckOutcome.ERROR`,
  which is blocking. There is no path from a raise to an allow.
- The module imports no provider client. It returns a `Decision`; it cannot send.

**2. [`src/stormbot/assurance/release_gate.py`](../src/stormbot/assurance/release_gate.py)**

The question: *how do you stop the description of a system from drifting away
from the system?*

Read the docstring and the `CHECKS` tuple. The claim registry
([`assurance/product_claims.json`](../assurance/product_claims.json)) holds the
sentences the product says about itself; the gate refuses to ship when a sentence
outruns its evidence.

Note `_check_declared_state_honesty`: a capability cannot declare a state the
ledger does not support. Without that check, the registry could promote itself
and the whole mechanism would be decorative.

---

## Fifteen minutes: the guided path

### 1. The negative tests — [`tests/governance/test_execution_governor.py`](../tests/governance/test_execution_governor.py)

Skip the happy path. Read:

- `test_a_check_that_raises_denies_rather_than_allows` — the single most
  important property in the runtime half. It monkey-patches the suppression
  backend to raise and asserts the verdict is `DENY`.
- `test_approval_for_a_different_recipient_is_denied_not_merely_unapproved` — a
  wrong-target token is an attempted bypass, so it blocks rather than falling
  back to "needs approval".
- `test_log_record_contains_no_raw_target_and_no_payload` — the audit trail
  cannot become the leak.

### 2. Approval as a cryptographic object — [`approvals.py`](../src/stormbot/governance/approvals.py)

Ask: *could the agent mint its own approval?* The token is HMAC-signed over
`(action_type, target_digest, approver, expiry)` with a secret belonging to the
approval surface, not the agent runtime. Verification checks the signature before
expiry and scope, so a forged token and an expired one are not distinguishable by
response timing.

[`tests/governance/test_approval_tokens.py`](../tests/governance/test_approval_tokens.py)
is eight negative tests and two positive ones. That ratio is the intended shape.

### 3. Privacy by construction — [`suppression.py`](../src/stormbot/governance/suppression.py)

The do-not-contact list stores keyed HMAC digests. Membership tests still work; a
leaked file is not a marketing list. Two details worth noticing:

- The key is mandatory. An unsalted hash of a 10-digit phone number is reversible
  by brute force in seconds, so an unkeyed digest would be theatre.
- `is_suppressed` returns `True` for an identifier it cannot normalize. An
  identifier that cannot be checked is one that cannot be cleared.

### 4. The ladder — [`evidence.py`](../src/stormbot/assurance/evidence.py)

Read `state_of`. A subject's state is the highest rung with an *unbroken chain*
below it, so certification evidence with no test evidence proves nothing above
`BUILT`.

Then read `_DEFAULT_MAX_AGE` and the comment above it. Runtime evidence expires
in 24 hours; source evidence never expires. The asymmetry is the argument:
`ACTIVE` is a claim about the present tense, `TESTED` is a claim about a revision.

### 5. Composition — [`tests/integration/test_governed_send_pipeline.py`](../tests/integration/test_governed_send_pipeline.py)

Unit tests prove each control works. This proves they compose, and that the
provider is reachable only through a dispatch table behind the governor.

`test_opt_out_survives_a_reformatted_import_of_the_same_number` is the one to
read: the opt-out was recorded as `(813) 555-0199` and the send targets
`+18135550199`. This is the mistake that produces real regulatory complaints.

### 6. Where CI stops — [`.github/workflows/release-assurance.yml`](../.github/workflows/release-assurance.yml)

Read the `Run the release gate` step. Exit codes 0–2 are policy verdicts and pass
through to the next step; anything above 2 is an execution failure and is
re-raised. Confusing the two would let a crashed gate read as approval.

---

## Questions worth asking, with honest answers

**Is this the production system?**

No. It is a clean-room reimplementation of its patterns, written for publication.
No production code, data, configuration, or commit history was copied. Metrics
about the private system are in
[`PRODUCTION_EVIDENCE.md`](PRODUCTION_EVIDENCE.md) with their provenance and
limits stated.

**Does green CI here mean the suite passes?**

Yes, in this repository — 141 test functions, all of them, on three interpreters.
It is a small repository and that is achievable. `PRODUCTION_EVIDENCE.md` is
explicit that the same statement does not hold for the private system, where CI
runs a focused subset.

**Is anything here `CERTIFIED` or `ACTIVE`?**

No, and `make certify` demonstrates it. Certification requires evidence bound to
an exact commit SHA; `ACTIVE` requires a runtime probe less than 24 hours old.
Neither exists here, so the ladder tops out at `TESTED`.

**Why zero dependencies?**

Code whose job is to refuse actions should not inherit a supply chain. It also
makes the suite trivially reproducible — no lockfile, no cache, no index outage.
The cost is a hand-rolled JSON Schema validator
([`schema.py`](../src/stormbot/assurance/schema.py)), which is why it rejects
unsupported keywords loudly instead of ignoring them, and why it has its own
test module.

**What is deliberately missing?**

Persistence, concurrency, an HTTP surface, and provider integrations. The
governor holds budget state in memory, which is correct for a reference
implementation and wrong for a multi-process deployment;
[ADR-0006](adr/0006-in-memory-budget-state.md) says so and names the fix.

---

## If you only read three files

1. [`src/stormbot/governance/governor.py`](../src/stormbot/governance/governor.py) — the safety argument
2. [`src/stormbot/assurance/release_gate.py`](../src/stormbot/assurance/release_gate.py) — the honesty argument
3. [`tests/contract/test_repository_hygiene.py`](../tests/contract/test_repository_hygiene.py) — the repository checking itself for the failure that would discredit both

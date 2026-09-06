# Evidence states

## Why a vocabulary

"It's done" collapses six genuinely different conditions into one word, and the
gap between "the tests pass" and "it is running in production and doing the
thing" is exactly where overclaiming lives. Not usually as a lie — as a
compression artifact, where someone says "done", someone else hears "shipped",
and nobody notices for a month.

The fix is a ladder where each rung names its own evidence:

```
BUILT → INTEGRATED → TESTED → CERTIFIED → DEPLOYED → ACTIVE
```

Plus four states that are not on the ladder, because they are honest non-answers:
`UNKNOWN`, `PLANNED`, `BLOCKED`, `SUPERSEDED`.

---

## The rungs

| State | Required evidence | Means | Does **not** mean |
| --- | --- | --- | --- |
| `BUILT` | `SOURCE_TREE` | The code exists and is committed | It runs |
| `INTEGRATED` | `INTEGRATION_RUN` | It works alongside the components it touches | Anyone tested its behaviour |
| `TESTED` | `TEST_RUN` | A test run covers the claimed behaviour | It is deployed anywhere |
| `CERTIFIED` | `CERTIFICATION` (+ exact SHA) | A human attested a specific build against a policy | It was deployed |
| `DEPLOYED` | `DEPLOYMENT` (+ exact SHA) | That exact SHA reached an environment | It is working |
| `ACTIVE` | `RUNTIME_PROBE` (+ exact SHA) | A probe within the last 24 hours observed it working | It will still be true tomorrow |

### The non-ladder states

| State | Means |
| --- | --- |
| `UNKNOWN` | No evidence. Not "probably fine" — genuinely unknown |
| `PLANNED` | Intended, not started |
| `BLOCKED` | Cannot advance; an active claim depending on one fails the gate |
| `SUPERSEDED` | Replaced by something else |

`UNKNOWN` is the default and it is deliberately uncomfortable. A system that
defaults to `BUILT` invites someone to leave it there.

---

## Contiguity

```python
state = EvidenceState.UNKNOWN
for rung in _LADDER:
    if REQUIRED_EVIDENCE[rung] not in available:
        break
    state = rung
```

A subject's state is the highest rung for which **every rung below it** also has
evidence. Certification evidence with no test evidence proves nothing above
`BUILT`, and the ledger says `BUILT`.

This is the rule that stops the ladder being a set of independent checkboxes. In
practice the shortcut it prevents is: a deploy happened, so someone marks it
`DEPLOYED`, and the fact that nobody wrote a test disappears.

See `test_the_ladder_is_contiguous_so_a_gap_caps_the_state`.

---

## Freshness

| Evidence kind | Expires after | Why |
| --- | --- | --- |
| `SOURCE_TREE` | never | The code either is or is not in the tree |
| `INTEGRATION_RUN` | never | A fact about a revision |
| `TEST_RUN` | never | A fact about a revision |
| `CERTIFICATION` | 180 days | An attestation about a build, which ages |
| `DEPLOYMENT` | 90 days | Environments get rebuilt |
| `RUNTIME_PROBE` | **24 hours** | `ACTIVE` is a claim about the present tense |

The asymmetry is the argument. A passing test run does not become false because
time passed — if the revision has not moved, neither has the fact. A runtime
probe from last week says nothing whatsoever about whether the service is up now.

A stale runtime probe silently demotes a subject from `ACTIVE` to `DEPLOYED`. It
does not error, because a demotion is the correct answer rather than a fault.
See `test_runtime_evidence_expires_because_it_is_a_present_tense_claim`.

---

## Evidence records

```python
EvidenceRecord(
    id="ev.contact_suppression.tests",
    kind=EvidenceKind.TEST_RUN,
    subject="governance.contact_suppression",
    recorded_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
    detail="Tests asserting normalization equivalence and that no raw identifier appears in an export.",
    artifact_uri="tests/governance/test_contact_suppression.py",
)
```

Two constructor-time rules:

**Build-specific evidence must name a SHA.** `CERTIFICATION`, `DEPLOYMENT`, and
`RUNTIME_PROBE` all raise without `commit_sha`. A claim about a build that does
not identify the build is not evidence, and "we certified it last Tuesday" is not
a statement anyone can verify.

**Timestamps must be timezone-aware.** A naive datetime is not a point in time,
and freshness arithmetic on one is guesswork.

The ledger is append-only in the sense that matters: reusing an id for different
content raises. Evidence is superseded by a newer record, never edited to make a
failing claim pass.

---

## Common misuses

**"CI is green, so it's `TESTED`."** Only if CI ran a test covering *that
capability*. Green CI on a repository where the relevant suite is excluded proves
the excluded suite was excluded.

**"There's a branch called `certified/...`, so it's `CERTIFIED`."** A branch name
is a string. Certification is an attestation about an exact SHA, recorded in
`assurance/evidence/`.

**"It deployed, so it's `ACTIVE`."** Deployment means the artifact arrived.
`ACTIVE` means something observed it working, recently. Most outages live in that
gap.

**"It's `TESTED` because I ran it locally."** Then record a `TEST_RUN` with an
`artifact_uri` somebody else can run. If it is not reproducible it is not
evidence, it is recollection.

---

## Using it in a pull request

The [PR template](../../.github/pull_request_template.md) asks for the highest
state the change has actually earned. Most changes are `TESTED`. Very few are
`CERTIFIED`, and none are `ACTIVE` at merge time, because nothing is running yet.

If that feels like it undersells the work, that is the vocabulary functioning
correctly. The alternative — a word that means everything from "I wrote it" to
"customers depend on it" — is the one that eventually gets someone burned in
front of a client.

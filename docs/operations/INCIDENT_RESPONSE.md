# Incident response

Four playbooks for the failures this system can actually produce. Each one starts
with the action to take before understanding the cause, because in every one of
these the cost of the incident grows while you diagnose it.

**Universal first step:** engage the kill switch. It applies to every action type
and blocks even already-approved requests.

```python
policy = replace(current_policy, kill_switch_engaged=True)
```

---

## P1 — A credential may have been exposed

**Triggers:** `payload_safety` blocked a send; a credential-shaped string appears
in a log; the repository-hygiene check fails; a third party reports a leak.

1. **Rotate first, investigate second.** Rotation is cheap and reversible;
   exposure time is not. Do not wait to confirm the credential was real, or that
   anyone saw it.
2. Identify the credential class from the detector name in the finding — the
   finding does not contain the value, by design.
3. Determine reach: was it in an outbound payload (blocked, so the exposure is
   internal), a log (exposure equals log retention and log access), or the
   repository (exposure equals repository visibility and clone history)?
4. If it reached a repository: rotation is necessary but not sufficient. A
   deleted file is still in history, and any existing clone or fork retains it.
5. Add a detector if the shape was not covered, with a test, and record the
   evidence.

**Do not** paste the credential into the incident ticket while investigating. The
ticket is read by more people than the log was.

---

## P2 — Someone was contacted who should not have been

The most serious failure this system can produce, because it is irreversible and
the harm lands on someone who did not consent.

1. Kill switch.
2. Establish scope from the decision log. Every attempt is recorded with a target
   digest, so count the distinct digests with `ALLOW` verdicts in the window —
   without reading a single phone number.
3. Determine which control failed:

| Symptom | Likely cause |
| --- | --- |
| Suppression check shows `PASS` for a contact who had opted out | Normalization mismatch — the opt-out and the send used different formats and one did not normalize |
| Suppression check shows `ERROR` | Backend failure. The system denied, so this is not the cause of a send |
| No suppression check in the trail | The action was not classified as consequential in policy |
| Opt-out was never recorded | The failure is upstream, in whatever ingests `STOP` replies |

4. Record the suppression correctly, in every format the contact may appear in.
5. Write a regression test with the *exact* pair of formats that failed. Not a
   representative pair — the exact one.
6. Add the evidence record and re-run the gate.

The normalization mismatch is the common one, and it is silent: nothing errors,
the check passes, and the message goes out. That is why
`test_opt_out_applies_to_every_format_of_the_same_number` enumerates five
formats rather than asserting on one.

---

## P3 — The agent is proposing things it should not

**Triggers:** a spike in `DENY` verdicts; proposals for action types nobody
expected; a budget exhausted early in the day.

1. Kill switch — the proposals are being denied, but the cause is unresolved and
   an allowlisted action may be next.
2. Check what is being proposed. `known_action` blocks are the loud, safe case:
   the agent wanted something it was never permitted to have, and default deny
   did its job.
3. Look upstream for the injection vector. A field in a lead record, an inbound
   reply, a scraped page. The content that changed the agent's behaviour is
   usually recent and usually attacker-supplied.
4. **Do not widen policy to make the errors stop.** The denials are the system
   working. The problem is upstream.
5. Before restoring, confirm the injected content is out of the working set —
   including out of any memory, cache, or retrieval index the agent reads.

---

## P4 — The release gate is failing

Lower urgency, but it means a claim and its evidence have diverged, and the
correct response depends on which one is wrong.

| Failing check | What it means | Fix |
| --- | --- | --- |
| `claim-evidence-sufficiency` | A claim outran its evidence — often a deleted or renamed test | Restore the evidence, or retire the claim |
| `declared-state-honesty` | A capability declares more than the ledger supports | Correct the declaration, or add the evidence |
| `evidence-refs-resolve` | A claim points at an evidence record that does not exist | Add the record, or remove the reference |
| `registry-schema` | A registry violates its schema | The error names the exact path |
| `hitl-approval-gate` | A high-risk capability lost its approval gate | Restore it — this one is a live safety gap |
| Exit code 3 | The gate could not run | A broken tool run, **not** a verdict. Fix the tooling; do not interpret it |

**Never** resolve this by making the check advisory, deleting the claim from the
registry without deciding whether it is still true, or adding an evidence record
that does not correspond to a real artifact. All three convert a visible problem
into an invisible one, and the third one is the worst because it leaves behind
something that looks like proof.

---

## After any incident

1. Write the regression test first, and confirm it fails against the unfixed
   code. A regression test that has never failed is an assertion, not a test.
2. Fix the cause.
3. Add or update the evidence record.
4. If a product claim was falsified, update `assurance/product_claims.json` in
   the same change. A claim that was untrue during the incident is worth
   re-reading now that you know how it failed.
5. `make gate` and `make test`.

The evidence record is the step most likely to be skipped and the one that
matters six months on, when someone asks whether this failure mode is covered and
the answer needs to be a file path rather than a memory.

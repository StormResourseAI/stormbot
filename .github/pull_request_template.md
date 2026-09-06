# What this changes

<!-- One paragraph. What is different after this merges, and why. -->

# Evidence state

Pick the highest state this change has actually earned. The ladder is defined in
[`docs/assurance/EVIDENCE_STATES.md`](../docs/assurance/EVIDENCE_STATES.md), and
"the tests pass" is `TESTED`, not `CERTIFIED` and not `ACTIVE`.

- [ ] `BUILT` — the code exists
- [ ] `INTEGRATED` — it works alongside the components it touches
- [ ] `TESTED` — a test run covers the behaviour this change claims
- [ ] `CERTIFIED` — certified against an exact SHA, recorded in `assurance/evidence/`

# Governed surface

- [ ] This change touches `src/stormbot/governance/`, `src/stormbot/assurance/`,
      `assurance/`, or `.github/workflows/`

If checked, the CI policy requires an accompanying test change, and any advisory
release-gate finding becomes blocking. Both are enforced automatically; this box
is here so the author has thought about it before CI does.

# Claims

- [ ] No product claim changed
- [ ] A claim changed, and `assurance/product_claims.json` plus the supporting
      evidence record were updated in this PR

# Safety checklist

- [ ] No credential, database, log, backup, or real contact data is added
- [ ] No safety check was weakened, skipped, or made non-blocking to get green
- [ ] New failure modes fail closed

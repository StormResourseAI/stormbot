# Threat model

Scope: the two subsystems in this repository — runtime governance and release
assurance. The agent, the providers, and the hosting environment are upstream and
downstream of it, and are named here only where the boundary matters.

Threats are grouped by the actor, because the mitigation differs sharply
depending on who is trying.

---

## T1 — A compromised or misled agent

**The realistic case.** Not a malicious agent; a manipulated one. An LLM
processing a lead record whose notes field contains instructions, or an inbound
reply crafted to steer the next action.

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Invoke an unreviewed capability | `known_action`: allowlist, default deny | An allowlisted action misused within its bounds |
| Contact an opted-out person | `suppression`, checked per recipient | Suppression store unavailable → check errors → **denies** |
| Mass-message | `budget`, per action type per day | Up to the daily cap is within policy |
| Self-approve | `approval`: HMAC token, secret held by the operator surface | Agent-side compromise of the operator surface |
| Exfiltrate a credential in message text | `payload_safety`: fourteen detectors | A novel credential format |
| Send at 3am | `quiet_hours` | Fixed UTC offset, not per-recipient timezone |
| Widen its own policy | Frozen dataclass, not in the request path | Process-level code execution |

**Design position.** Injection is not detected, it is contained. A successful
injection buys the attacker exactly the authority the agent already had, which is
policy-bounded and human-gated. Betting on detection means betting there will be
no false negatives, and one false negative is an incident.

---

## T2 — An operator, by mistake

Most real incidents in this class of system are not attacks.

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Ship a new tool that immediately starts sending | Default deny; adding a tool does not add a permission | Adding it to the allowlist *and* opening the gate in one change |
| Point a test run at the production database | `assert_test_database` refuses in a test process | A process that does not identify itself as a test |
| Approve the wrong recipient | Token is scoped to a target digest; a wrong-target token is a `DENY`, not merely unapproved | Approving the correct recipient for the wrong reason |
| Leave the go-live gate open in staging | Gate is explicit policy, closed by default | Configuration drift |
| Forget a daily budget | A consequential action with no budget is **denied** | — |
| Publish a claim that is not true | Release gate fails on `evidence-refs-resolve` before the claim can ship | A true-but-misleading statement |

**Design position.** Every default is the safe one, and the unsafe configuration
requires typing something. The absence of a budget is a denial rather than an
unlimited allowance, because forgetting to configure a limit is the most likely
way to end up without one.

---

## T3 — Someone who obtains repository or artifact access

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Harvest contact data from the repository | Keyed digests only; hygiene test fails the build on any non-fictional phone or email | A digest plus the key is reversible |
| Harvest contact data from a suppression export | `export()` emits digests, never identifiers | Same |
| Read credentials from logs | Decision records carry no payload; findings carry no matched value | A caller logging the raw request themselves |
| Read credentials from error messages | Guard errors omit the connection string | An unhandled exception elsewhere |
| Find a secret in git history | Nothing was ever imported from a private repository — the history starts clean | — |
| Substitute a dependency | `--require-hashes` install, platform-split locks, drift check in CI | Compromise of PyPI *and* the lockfile in one PR |

**Design position.** The suppression key is a genuine asset — with it, the digest
list becomes reversible for any candidate identifier. It belongs in a secret
manager and should be rotatable, which means the registry must support rekeying,
which this reference implementation does not.

---

## T4 — Someone attacking the assurance pipeline

The gate is a control, so it is also a target — usually by someone who just wants
the build green.

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Declare a higher state in the registry | `declared-state-honesty` compares declaration to ledger | — |
| Point a claim at evidence that does not exist | `evidence-refs-resolve` | — |
| Point evidence at a deleted test file | `test_every_evidence_artifact_actually_exists_in_the_repository` | Evidence pointing at a file that exists but no longer tests the thing |
| Add a fake evidence record | Schema-validated, requires a SHA for build-specific kinds | A fabricated `TEST_RUN` record naming a real file |
| Weaken a safety check to get green | CI policy blocks a governed change with no test change | A change that also weakens the test |
| Make a crashed gate look like a pass | Exit 3 is not a verdict; the workflow re-raises anything above 2 | — |
| Silently drop the report artifact | `if-no-files-found: error` | — |

**Design position.** The pipeline resists carelessness, not a determined
committer. Someone with merge rights who is willing to edit the tests, the
registry, and the evidence together can produce a green build for a false claim.
The control makes that require deliberate, visible, reviewable effort rather than
one field edit — which is the realistic bar for a process control.

---

## Explicitly out of scope

Named rather than omitted, because an unstated limit reads as an unnoticed one.

- **Authentication and authorization of the operator.** Who is allowed to hold
  the approval secret, and how they prove who they are, is upstream.
- **Provider-side compromise.** If the SMS provider is compromised, nothing here
  helps.
- **Model behaviour and output quality.** This repository governs what happens to
  a proposed action; it has no opinion on whether the message is any good.
- **Denial of service.** An agent that floods the governor with proposals wastes
  CPU. It sends nothing.
- **Physical and host security,** key management infrastructure, network
  policy, and transport security.
- **Regulatory compliance.** Quiet hours and suppression are ingredients of
  TCPA-style compliance, not a compliance program, and nothing here is legal
  advice.

---

## Assumptions, and what happens if each is wrong

| Assumption | If wrong |
| --- | --- |
| The approval secret is not readable by the agent runtime | Human-in-the-loop is theatre; the agent approves itself |
| The suppression key is protected | The digest list becomes a reversible contact list |
| Policy is constructed at startup from a trusted source | Every runtime control is bypassable |
| The caller only sends on `ALLOW` | Every runtime control is bypassable |
| CI runs on every merge path | The release gate never executes |

The fourth is the weakest link and it is worth being blunt about it. The governor
returns a `Decision`; it cannot force the caller to honour it. Keeping the send
capability out of the governor is what makes the honouring auditable — one
function's return value, one dispatch site — but it is a discipline enforced by
code review, not by the type system. A stronger design would hand back a
capability object that *is* the only way to send, and that is the most valuable
thing this reference implementation does not do.

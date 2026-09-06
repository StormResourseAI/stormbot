# Security Policy

## Reporting a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/StormResourseAI/stormbot/security/advisories/new)
rather than opening a public issue.

Useful reports include the affected file and version, the impact you believe it
has, and the smallest reproduction you can manage. If you found a way to make
[`ExecutionGovernor`](src/stormbot/governance/governor.py) return `ALLOW` for
something it should have denied, that reproduction is the whole report and
everything else is optional.

Expect an acknowledgement within three business days. This is a
solo-maintained repository, so please size your disclosure timeline accordingly.

## Scope

**In scope** — anything that breaks a safety property this repository claims:

- A path through the governor that reaches `ALLOW` while a blocking check should
  have fired, or that turns an exception into an allow.
- Forging, replaying, or extending the lifetime of an
  [approval token](src/stormbot/governance/approvals.py).
- Recovering a raw contact identifier from a
  [suppression export](src/stormbot/governance/suppression.py), or defeating
  normalization so an opted-out contact is reachable under a different format.
- A credential shape that survives
  [redaction](src/stormbot/governance/redaction.py), or a finding that leaks the
  value it matched.
- Causing the [release gate](src/stormbot/assurance/release_gate.py) to report
  `pass` for a registry state that should fail, or an execution failure that
  reports as a verdict.
- Any credential, real contact record, or production artifact found in this
  repository or its history.

**Out of scope** — the demonstration secrets in `examples/` and `tests/`. They
are labelled, they protect nothing, and they exist so the examples run without
setup. Phone numbers in this repository are drawn from the `555-01xx` block
reserved for fictional use, and email addresses use `example.com`; a CI check
fails the build if that stops being true.

## What this repository contains

Only intentionally published material. There are no production credentials,
databases, customer or prospect records, runtime state, logs, or backups here,
and no code, data, configuration, or commit history was copied from the private
production system — the implementation was written from scratch for publication.

That claim is enforced rather than asserted.
[`tests/contract/test_repository_hygiene.py`](tests/contract/test_repository_hygiene.py)
fails the build when the tree contains a credential-shaped string outside the two
files whose job is to detect them, a phone number outside the reserved fictional
block, a non-documentation email domain, or a file type on the forbidden list
(databases, archives, key material, environment files, editor backups). It runs
as its own named check in [`ci.yml`](.github/workflows/ci.yml) so a hygiene
failure is visible without opening a log.

## Security design

- [Security model](docs/security/SECURITY_MODEL.md) — trust boundaries, secret
  handling, and the privacy-by-design choices in the suppression registry.
- [Threat model](docs/security/THREAT_MODEL.md) — what these controls defend
  against, and the several things they explicitly do not.
- [Incident response](docs/operations/INCIDENT_RESPONSE.md) — playbooks for
  credential exposure, wrongful contact, and a runaway agent.

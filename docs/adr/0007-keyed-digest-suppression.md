# ADR-0007 — Keyed digests for the do-not-contact list

**Status:** Accepted · **Date:** 2026-09-06

## Context

A do-not-contact list is the highest-value data a revenue-automation system
holds. It is a curated list of real people, their contact details, and the fact
that they engaged enough to opt out. It is more damaging to leak than an API key,
because a key can be rotated in a minute and a person's phone number cannot.

It is also the file most likely to be handled casually: exported for a vendor,
attached to a support ticket, copied into a spreadsheet during a migration,
committed while debugging an import.

Storing raw identifiers makes every one of those routine acts a potential
disclosure.

## Decision

Store keyed HMAC-SHA256 digests of normalized identifiers. Never store the
identifier.

```python
digest = hmac.new(key, normalize_contact(raw).encode(), sha256).hexdigest()
```

Two supporting decisions:

**Normalization happens before hashing.** `(813) 555-0142`, `813-555-0142`, and
`+18135550142` resolve to one key. Suppression that only matches the exact string
someone typed is not suppression — and the specific failure it permits is
contacting an opted-out person after a reformatted CRM export, which is the
version regulators hear about.

**The key is mandatory.** An unsalted SHA-256 of a 10-digit phone number is
reversible by brute force in seconds; the keyspace is 10 billion entries and a
laptop covers it. An unkeyed digest would be theatre.

## Alternatives rejected

**Store raw identifiers, encrypt at rest.** Rejected because it protects against
the wrong adversary. Encryption at rest defends against someone stealing a disk;
it does nothing about an export attached to a ticket, which is the realistic
failure. Keyed digests make the export itself harmless.

**Unkeyed hashes.** Rejected as reversible, per above.

**Store raw identifiers and rely on access control.** Rejected because access
control is a process control, and the file's whole life consists of being handed
to other processes.

## Consequences

**Good.** A leaked suppression export is not a marketing list. It carries digest,
reason, source, and timestamp — everything operationally useful, nothing
personally identifying. `test_export_contains_no_raw_contact_data` enforces it.

**Good.** The audit trail inherits the property. Decision records log the digest,
so the logs are not a second copy of the contact database.

**Cost — and this is a real one.** Key rotation invalidates the entire list.
Digests are keyed; a new key produces different digests, and previously
suppressed people become reachable. Rebuilding requires re-deriving from the
original identifiers, which by design this module does not retain.

That forces an operational discipline: **the system of record for opt-outs must
live outside this registry.** The registry is an enforcement index, not a
database. The [runbook](../operations/RUNBOOK.md#rotate-the-suppression-key) says
so, and the key must be backed up like the long-lived secret it is.

**Cost.** No enumeration and no reverse lookup. Answering "who is on the list?"
requires the source system. This is the intended property, and it is inconvenient
in exactly the moment someone wants an answer quickly.

**Residual risk.** An attacker holding both the export and the key can *confirm*
whether a number they already have is on the list. They cannot enumerate.

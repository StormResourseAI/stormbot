"""Loading and typing of the assurance registries.

Three documents describe what the system claims to do and what backs those
claims up:

``assurance/ai_capabilities.json``
    Every AI-driven capability, its risk tier, and whether a human must be in
    the loop.
``assurance/product_claims.json``
    Every statement made to a customer or in marketing, each one pointing at the
    capabilities it depends on and the evidence that supports it.
``assurance/evidence/*.json``
    Dated evidence records — test runs, certifications, runtime probes.

Schema violations are returned rather than raised, because the release gate
reports them as a failed check with a verdict. A document that cannot be parsed
as JSON at all *is* raised: that is a broken tool run, not a policy verdict, and
the two must not be confused in an exit code.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from stormbot.assurance.evidence import EvidenceKind, EvidenceLedger, EvidenceRecord, EvidenceState
from stormbot.assurance.schema import SchemaError, validate

__all__ = [
    "AssuranceBundle",
    "Capability",
    "ProductClaim",
    "RegistryLoadError",
    "default_registry_root",
    "load_bundle",
]

CAPABILITIES_FILE = "ai_capabilities.json"
CLAIMS_FILE = "product_claims.json"
EVIDENCE_DIR = "evidence"
SCHEMA_DIR = "schemas"

_SCHEMA_FOR = {
    CAPABILITIES_FILE: "ai_capability_registry.schema.json",
    CLAIMS_FILE: "product_claim_registry.schema.json",
    "evidence": "evidence_record.schema.json",
}


class RegistryLoadError(RuntimeError):
    """Raised when a registry file is missing or is not parseable JSON."""


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    description: str
    risk_tier: str
    human_in_the_loop: str
    declared_state: EvidenceState
    owner: str
    last_reviewed: date
    approval_gate: str | None = None

    @property
    def requires_human(self) -> bool:
        return self.human_in_the_loop == "required"


@dataclass(frozen=True)
class ProductClaim:
    id: str
    statement: str
    customer_facing: bool
    capability_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    required_state: EvidenceState
    status: str
    last_reviewed: date

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass
class AssuranceBundle:
    """Everything the release gate needs, already parsed and cross-linked."""

    capabilities: dict[str, Capability]
    claims: dict[str, ProductClaim]
    ledger: EvidenceLedger
    evidence_ids: frozenset[str]
    schema_errors: list[str] = field(default_factory=list)
    source_files: tuple[str, ...] = ()

    @property
    def schema_valid(self) -> bool:
        return not self.schema_errors


def default_registry_root(start: Path | None = None) -> Path:
    """Find the ``assurance/`` directory by walking up from ``start``."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        target = candidate / "assurance"
        if (target / CAPABILITIES_FILE).is_file():
            return target
    raise RegistryLoadError(f"could not locate an assurance/ directory above {here}")


def load_bundle(root: Path | None = None) -> AssuranceBundle:
    root = Path(root) if root is not None else default_registry_root()
    schema_dir = root / SCHEMA_DIR

    schema_errors: list[str] = []
    source_files: list[str] = []

    capabilities_doc = _read_json(root / CAPABILITIES_FILE)
    source_files.append(CAPABILITIES_FILE)
    schema_errors += _schema_errors(
        capabilities_doc, schema_dir / _SCHEMA_FOR[CAPABILITIES_FILE], CAPABILITIES_FILE
    )

    claims_doc = _read_json(root / CLAIMS_FILE)
    source_files.append(CLAIMS_FILE)
    schema_errors += _schema_errors(claims_doc, schema_dir / _SCHEMA_FOR[CLAIMS_FILE], CLAIMS_FILE)

    evidence_docs: list[tuple[str, Mapping[str, Any]]] = []
    evidence_root = root / EVIDENCE_DIR
    for path in sorted(evidence_root.glob("*.json")) if evidence_root.is_dir() else []:
        doc = _read_json(path)
        name = f"{EVIDENCE_DIR}/{path.name}"
        source_files.append(name)
        schema_errors += _schema_errors(doc, schema_dir / _SCHEMA_FOR["evidence"], name)
        evidence_docs.append((name, doc))

    capabilities = {
        entry["id"]: _capability(entry)
        for entry in capabilities_doc.get("capabilities", [])
        if isinstance(entry, dict) and "id" in entry
    }
    claims = {
        entry["id"]: _claim(entry)
        for entry in claims_doc.get("claims", [])
        if isinstance(entry, dict) and "id" in entry
    }

    ledger = EvidenceLedger()
    evidence_ids: set[str] = set()
    for _name, doc in evidence_docs:
        for entry in doc.get("records", []):
            record = _record(entry)
            ledger.record(record)
            evidence_ids.add(record.id)

    return AssuranceBundle(
        capabilities=capabilities,
        claims=claims,
        ledger=ledger,
        evidence_ids=frozenset(evidence_ids),
        schema_errors=schema_errors,
        source_files=tuple(source_files),
    )


# --------------------------------------------------------------------- internals


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise RegistryLoadError(f"required registry file is missing: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RegistryLoadError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise RegistryLoadError(f"{path} must contain a JSON object at the top level")
    return document


def _schema_errors(document: Mapping[str, Any], schema_path: Path, label: str) -> list[str]:
    if not schema_path.is_file():
        raise RegistryLoadError(f"schema not found for {label}: {schema_path}")
    schema = _read_json(schema_path)
    errors: list[SchemaError] = validate(document, schema)
    return [f"{label} {error}" for error in errors]


def _capability(entry: Mapping[str, Any]) -> Capability:
    return Capability(
        id=entry["id"],
        title=entry.get("title", ""),
        description=entry.get("description", ""),
        risk_tier=entry.get("risk_tier", "unknown"),
        human_in_the_loop=entry.get("human_in_the_loop", "none"),
        declared_state=_state(entry.get("evidence_state", "UNKNOWN")),
        owner=entry.get("owner", "unassigned"),
        last_reviewed=_date(entry.get("last_reviewed")),
        approval_gate=entry.get("approval_gate"),
    )


def _claim(entry: Mapping[str, Any]) -> ProductClaim:
    return ProductClaim(
        id=entry["id"],
        statement=entry.get("statement", ""),
        customer_facing=bool(entry.get("customer_facing", False)),
        capability_refs=tuple(entry.get("capability_refs", [])),
        evidence_refs=tuple(entry.get("evidence_refs", [])),
        required_state=_state(entry.get("required_state", "TESTED")),
        status=entry.get("status", "draft"),
        last_reviewed=_date(entry.get("last_reviewed")),
    )


def _record(entry: Mapping[str, Any]) -> EvidenceRecord:
    return EvidenceRecord(
        id=entry["id"],
        kind=EvidenceKind(entry["kind"]),
        subject=entry["subject"],
        recorded_at=_timestamp(entry["recorded_at"]),
        detail=entry.get("detail", ""),
        commit_sha=entry.get("commit_sha"),
        artifact_uri=entry.get("artifact_uri"),
    )


def _state(value: str) -> EvidenceState:
    try:
        return EvidenceState(value)
    except ValueError:
        return EvidenceState.UNKNOWN


def _date(value: Any) -> date:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return date.min


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

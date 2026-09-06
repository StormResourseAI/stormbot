"""Release assurance: claims that cannot outrun their evidence.

The pieces fit together in one direction:

``evidence``
    The state ladder (``BUILT`` -> ... -> ``ACTIVE``) and the ledger that decides
    which rung a subject has actually earned.
``schema``
    A minimal, dependency-free JSON Schema validator for the registries.
``registry``
    Loads ``assurance/*.json`` into typed capabilities, claims, and evidence.
``release_gate``
    Runs the checks and emits a verdict plus a machine-readable report.
``ci_policy``
    Turns that verdict, combined with what the change touched, into a merge
    decision.
"""

from __future__ import annotations

from stormbot.assurance.evidence import (
    EvidenceKind,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceState,
    UnprovenClaimError,
)
from stormbot.assurance.registry import (
    AssuranceBundle,
    Capability,
    ProductClaim,
    RegistryLoadError,
    load_bundle,
)

# ``release_gate`` and ``ci_policy`` are intentionally not re-exported here.
# Both are run as ``python -m``, and importing them from the package __init__
# makes the interpreter load them twice and warn about it.

__all__ = [
    "AssuranceBundle",
    "Capability",
    "EvidenceKind",
    "EvidenceLedger",
    "EvidenceRecord",
    "EvidenceState",
    "ProductClaim",
    "RegistryLoadError",
    "UnprovenClaimError",
    "load_bundle",
]

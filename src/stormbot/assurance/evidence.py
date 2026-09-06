"""Evidence states: a vocabulary where words cannot be used without proof.

The failure mode this exists to prevent is linguistic. "It's done" collapses six
genuinely different conditions into one word, and the gap between "the tests
pass" and "it is running in production and doing the thing" is exactly where
overclaiming lives.

So the ladder is explicit and each rung has a required evidence kind:

    BUILT -> INTEGRATED -> TESTED -> CERTIFIED -> DEPLOYED -> ACTIVE

A subject's state is the highest rung for which *every rung below it* also has
supporting evidence. You cannot be ``CERTIFIED`` without being ``TESTED``, and a
green CI run does not make anything ``ACTIVE`` — that requires a runtime probe,
and runtime probes expire.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

__all__ = [
    "EvidenceKind",
    "EvidenceLedger",
    "EvidenceRecord",
    "EvidenceState",
    "FreshnessPolicy",
    "UnprovenClaimError",
]


class EvidenceState(StrEnum):
    """Ladder states, plus the three honest non-answers."""

    UNKNOWN = "UNKNOWN"
    PLANNED = "PLANNED"
    BUILT = "BUILT"
    INTEGRATED = "INTEGRATED"
    TESTED = "TESTED"
    CERTIFIED = "CERTIFIED"
    DEPLOYED = "DEPLOYED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"

    @property
    def rank(self) -> int:
        """Position on the ladder, or -1 for states that are not on it."""
        return _LADDER.index(self) if self in _LADDER else -1

    @property
    def on_ladder(self) -> bool:
        return self in _LADDER

    def at_least(self, other: EvidenceState) -> bool:
        if not (self.on_ladder and other.on_ladder):
            return False
        return self.rank >= other.rank


class EvidenceKind(StrEnum):
    SOURCE_TREE = "SOURCE_TREE"
    INTEGRATION_RUN = "INTEGRATION_RUN"
    TEST_RUN = "TEST_RUN"
    CERTIFICATION = "CERTIFICATION"
    DEPLOYMENT = "DEPLOYMENT"
    RUNTIME_PROBE = "RUNTIME_PROBE"


_LADDER: tuple[EvidenceState, ...] = (
    EvidenceState.BUILT,
    EvidenceState.INTEGRATED,
    EvidenceState.TESTED,
    EvidenceState.CERTIFIED,
    EvidenceState.DEPLOYED,
    EvidenceState.ACTIVE,
)

#: The one evidence kind that can promote a subject onto each rung.
REQUIRED_EVIDENCE: Mapping[EvidenceState, EvidenceKind] = {
    EvidenceState.BUILT: EvidenceKind.SOURCE_TREE,
    EvidenceState.INTEGRATED: EvidenceKind.INTEGRATION_RUN,
    EvidenceState.TESTED: EvidenceKind.TEST_RUN,
    EvidenceState.CERTIFIED: EvidenceKind.CERTIFICATION,
    EvidenceState.DEPLOYED: EvidenceKind.DEPLOYMENT,
    EvidenceState.ACTIVE: EvidenceKind.RUNTIME_PROBE,
}

#: Rungs that are claims about a specific build and therefore require a SHA.
_SHA_REQUIRED = frozenset({EvidenceKind.CERTIFICATION, EvidenceKind.DEPLOYMENT, EvidenceKind.RUNTIME_PROBE})


class UnprovenClaimError(AssertionError):
    """Raised when a state is asserted that the ledger cannot support."""


@dataclass(frozen=True)
class FreshnessPolicy:
    """How long each kind of evidence stays meaningful.

    Runtime evidence expires fastest and for the most obvious reason: a probe
    from last week says nothing about whether the service is up now.
    """

    max_age: Mapping[EvidenceKind, timedelta | None] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.max_age is None:
            object.__setattr__(self, "max_age", dict(_DEFAULT_MAX_AGE))

    def is_fresh(self, record: EvidenceRecord, now: datetime) -> bool:
        limit = self.max_age.get(record.kind)
        if limit is None:
            return True
        return (now - record.recorded_at) <= limit


#: Evidence about source does not expire on a clock — a passing test run is a
#: fact about a revision, and if the revision has not moved neither has the
#: fact. Evidence about a *running system* does expire, quickly, because it is a
#: claim about the present tense.
_DEFAULT_MAX_AGE: Mapping[EvidenceKind, timedelta | None] = {
    EvidenceKind.SOURCE_TREE: None,
    EvidenceKind.INTEGRATION_RUN: None,
    EvidenceKind.TEST_RUN: None,
    EvidenceKind.CERTIFICATION: timedelta(days=180),
    EvidenceKind.DEPLOYMENT: timedelta(days=90),
    EvidenceKind.RUNTIME_PROBE: timedelta(hours=24),
}


@dataclass(frozen=True)
class EvidenceRecord:
    """One piece of proof about one subject."""

    id: str
    kind: EvidenceKind
    subject: str
    recorded_at: datetime
    detail: str
    commit_sha: str | None = None
    artifact_uri: str | None = None

    def __post_init__(self) -> None:
        if self.kind in _SHA_REQUIRED and not self.commit_sha:
            raise ValueError(
                f"{self.kind.value} evidence must name an exact commit SHA; "
                "a claim about a build that does not identify the build is not evidence"
            )
        if self.recorded_at.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")


class EvidenceLedger:
    """Append-only store that answers "what can we actually claim?"."""

    def __init__(self, *, freshness: FreshnessPolicy | None = None) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._freshness = freshness or FreshnessPolicy()

    def record(self, record: EvidenceRecord) -> None:
        existing = self._records.get(record.id)
        if existing is not None and existing != record:
            raise ValueError(f"evidence id {record.id!r} is already used by a different record")
        self._records[record.id] = record

    def extend(self, records: Iterable[EvidenceRecord]) -> None:
        for record in records:
            self.record(record)

    def get(self, record_id: str) -> EvidenceRecord | None:
        return self._records.get(record_id)

    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(sorted(self._records.values(), key=lambda r: r.id))

    def subjects(self) -> tuple[str, ...]:
        return tuple(sorted({r.subject for r in self._records.values()}))

    def state_of(self, subject: str, *, now: datetime | None = None) -> EvidenceState:
        """Highest rung supported by an unbroken chain of fresh evidence."""
        now = now or datetime.now(UTC)
        available = {
            record.kind
            for record in self._records.values()
            if record.subject == subject and self._freshness.is_fresh(record, now)
        }

        state = EvidenceState.UNKNOWN
        for rung in _LADDER:
            if REQUIRED_EVIDENCE[rung] not in available:
                break
            state = rung
        return state

    def supports(self, subject: str, state: EvidenceState, *, now: datetime | None = None) -> bool:
        if not state.on_ladder:
            return False
        return self.state_of(subject, now=now).at_least(state)

    def assert_state(self, subject: str, state: EvidenceState, *, now: datetime | None = None) -> None:
        if not self.supports(subject, state, now=now):
            actual = self.state_of(subject, now=now)
            raise UnprovenClaimError(
                f"cannot claim {state.value} for {subject!r}: ledger supports {actual.value}"
            )

    def __len__(self) -> int:
        return len(self._records)

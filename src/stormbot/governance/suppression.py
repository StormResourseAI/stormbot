"""Do-not-contact enforcement over identifiers the registry never stores.

The registry keeps a keyed HMAC digest of each normalized contact identifier
instead of the identifier itself. Membership tests still work, but a leaked
suppression file does not become a marketing list, and no raw phone number or
email address is ever written to disk by this module.

That property is the direct lesson from a real incident class: the most damaging
data a revenue-automation system holds is usually not its credentials, it is the
list of people it is allowed to contact.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

__all__ = ["SuppressionRecord", "SuppressionRegistry", "normalize_contact"]

_NON_DIGITS = re.compile(r"[^\d]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def normalize_contact(raw: str, default_country_code: str = "1") -> str:
    """Normalize a phone number or email into a stable comparison key.

    Suppression that only matches the exact string a user typed is not
    suppression. ``(813) 555-0142``, ``813-555-0142`` and ``+18135550142`` are
    the same person and must all resolve to the same key.
    """
    candidate = raw.strip()
    if not candidate:
        raise ValueError("contact identifier must not be empty")

    if _EMAIL.match(candidate):
        local, _, domain = candidate.partition("@")
        return f"email:{local.lower()}@{domain.lower()}"

    digits = _NON_DIGITS.sub("", candidate)
    if not digits:
        raise ValueError(f"unrecognized contact identifier shape: {len(raw)} chars")
    if candidate.startswith("+"):
        return f"tel:+{digits}"
    if len(digits) == 10:
        return f"tel:+{default_country_code}{digits}"
    if len(digits) == 11 and digits.startswith(default_country_code):
        return f"tel:+{digits}"
    return f"tel:+{digits}"


@dataclass(frozen=True)
class SuppressionRecord:
    """A suppression entry. ``digest`` is the only identifier retained."""

    digest: str
    reason: str
    source: str
    suppressed_at: datetime

    def as_export_row(self) -> dict[str, str]:
        return {
            "digest": self.digest,
            "reason": self.reason,
            "source": self.source,
            "suppressed_at": self.suppressed_at.astimezone(UTC).isoformat(),
        }


class SuppressionRegistry:
    """Keyed-digest do-not-contact list.

    The key is required. A plain unsalted hash of a 10-digit phone number is
    reversible by brute force in seconds, so an unkeyed digest would provide no
    real protection.
    """

    VALID_REASONS = frozenset(
        {"opt_out", "complaint", "bounce", "litigation_hold", "manual_operator", "regulatory"}
    )

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("suppression registry requires a non-empty key")
        self._key = key
        self._records: dict[str, SuppressionRecord] = {}

    def digest_for(self, contact: str) -> str:
        normalized = normalize_contact(contact)
        return hmac.new(self._key, normalized.encode("utf-8"), sha256).hexdigest()

    def suppress(
        self,
        contact: str,
        *,
        reason: str,
        source: str,
        at: datetime | None = None,
    ) -> SuppressionRecord:
        if reason not in self.VALID_REASONS:
            raise ValueError(f"unknown suppression reason: {reason!r}")
        record = SuppressionRecord(
            digest=self.digest_for(contact),
            reason=reason,
            source=source,
            suppressed_at=at or datetime.now(UTC),
        )
        self._records[record.digest] = record
        return record

    def is_suppressed(self, contact: str) -> bool:
        try:
            digest = self.digest_for(contact)
        except ValueError:
            # An identifier we cannot normalize is an identifier we cannot clear.
            return True
        return digest in self._records

    def reason_for(self, contact: str) -> str | None:
        record = self._records.get(self.digest_for(contact))
        return record.reason if record else None

    def export(self) -> list[dict[str, str]]:
        """Export rows safe to commit, ship to a vendor, or attach to a ticket."""
        return [record.as_export_row() for record in sorted(self._records.values(), key=lambda r: r.digest)]

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[SuppressionRecord]:
        return iter(self._records.values())

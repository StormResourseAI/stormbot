"""Outbound content scanning and redaction.

Two jobs, deliberately kept in one place so the pattern table has exactly one
owner:

1. Stop credential-shaped strings from leaving the process — in agent output,
   log lines, LLM prompts, or operator notifications.
2. Redact personal data (phone numbers, email addresses, street addresses) from
   anything that gets persisted to a log or an evidence artifact.

The patterns below are *detectors*. They are intentionally shaped like the
secrets they catch, which means this file will light up credential scanners. It
is the one place in the repository where that is expected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from re import Pattern

__all__ = ["PII_PATTERNS", "SECRET_PATTERNS", "Finding", "Redactor"]


@dataclass(frozen=True)
class _Detector:
    name: str
    category: str
    pattern: Pattern[str]
    placeholder: str


def _detector(name: str, category: str, regex: str, placeholder: str) -> _Detector:
    return _Detector(name=name, category=category, pattern=re.compile(regex), placeholder=placeholder)


#: Credential shapes. A hit is treated as fail-closed evidence, never as a warning.
SECRET_PATTERNS: Sequence[_Detector] = (
    _detector("authorization_bearer", "secret", r"\bBearer\s+[A-Za-z0-9\-._~+/]{16,}=*", "Bearer <REDACTED>"),
    _detector("stripe_live_key", "secret", r"\bsk_live_[A-Za-z0-9]{8,}", "sk_live_<REDACTED>"),
    _detector("stripe_test_key", "secret", r"\bsk_test_[A-Za-z0-9]{8,}", "sk_test_<REDACTED>"),
    _detector("stripe_publishable_key", "secret", r"\bpk_live_[A-Za-z0-9]{8,}", "pk_live_<REDACTED>"),
    _detector("github_token", "secret", r"\bgh[pousr]_[A-Za-z0-9]{16,}", "gh*_<REDACTED>"),
    _detector("slack_bot_token", "secret", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", "xox*-<REDACTED>"),
    _detector("aws_access_key_id", "secret", r"\bAKIA[0-9A-Z]{16}\b", "AKIA<REDACTED>"),
    _detector("google_api_key", "secret", r"\bAIza[0-9A-Za-z_\-]{20,}", "AIza<REDACTED>"),
    _detector("sendgrid_key", "secret", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}", "SG.<REDACTED>"),
    _detector("anthropic_key", "secret", r"\bsk-ant-[A-Za-z0-9\-_]{16,}", "sk-ant-<REDACTED>"),
    _detector("openai_project_key", "secret", r"\bsk-proj-[A-Za-z0-9\-_]{16,}", "sk-proj-<REDACTED>"),
    _detector(
        "telegram_bot_token", "secret", r"\b\d{8,12}:AA[A-Za-z0-9_\-]{30,}", "<REDACTED_TELEGRAM_TOKEN>"
    ),
    _detector("twilio_account_sid", "secret", r"\bAC[0-9a-fA-F]{32}\b", "AC<REDACTED>"),
    _detector("private_key_block", "secret", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "<REDACTED_PRIVATE_KEY>"),
)

#: Personal data shapes. A hit is redacted, and is a policy violation only when
#: the destination is a log, an evidence artifact, or a model prompt.
PII_PATTERNS: Sequence[_Detector] = (
    _detector(
        "email_address", "pii", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "<REDACTED_EMAIL>"
    ),
    _detector("e164_phone", "pii", r"\+\d{1,3}\d{9,13}\b", "<REDACTED_PHONE>"),
    _detector("us_phone", "pii", r"\b\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b", "<REDACTED_PHONE>"),
    _detector(
        "street_address",
        "pii",
        r"\b\d{1,6}\s+[A-Z][A-Za-z.\-]*(?:\s+[A-Z][A-Za-z.\-]*)*\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Ct|Court|Hwy|Highway)\b\.?",
        "<REDACTED_ADDRESS>",
    ),
)


@dataclass(frozen=True)
class Finding:
    """One detector hit. Never carries the matched value."""

    detector: str
    category: str
    start: int
    end: int

    @property
    def is_secret(self) -> bool:
        return self.category == "secret"


class Redactor:
    """Scans and redacts text without ever surfacing the matched value.

    ``scan`` returns offsets and detector names only. This matters: findings end
    up in logs and CI output, and a finding that echoed the secret it found
    would defeat the point of having a detector at all.
    """

    def __init__(self, detectors: Iterable[_Detector] | None = None) -> None:
        if detectors is None:
            detectors = tuple(SECRET_PATTERNS) + tuple(PII_PATTERNS)
        self._detectors = tuple(detectors)

    def scan(self, text: str) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for detector in self._detectors:
            for match in detector.pattern.finditer(text):
                findings.append(
                    Finding(
                        detector=detector.name,
                        category=detector.category,
                        start=match.start(),
                        end=match.end(),
                    )
                )
        findings.sort(key=lambda f: (f.start, f.detector))
        return tuple(findings)

    def contains_secret(self, text: str) -> bool:
        return any(f.is_secret for f in self.scan(text))

    def redact(self, text: str) -> str:
        """Return ``text`` with every detector hit replaced by its placeholder.

        Secrets are redacted before PII so that a token containing an
        address-shaped or phone-shaped substring is still removed whole.
        """
        redacted = text
        for detector in self._detectors:
            if detector.category != "secret":
                continue
            redacted = detector.pattern.sub(detector.placeholder, redacted)
        for detector in self._detectors:
            if detector.category == "secret":
                continue
            redacted = detector.pattern.sub(detector.placeholder, redacted)
        return redacted

    def summarize(self, text: str) -> dict[str, int]:
        """Detector-name -> hit count. Safe to log."""
        counts: dict[str, int] = {}
        for finding in self.scan(text):
            counts[finding.detector] = counts.get(finding.detector, 0) + 1
        return counts

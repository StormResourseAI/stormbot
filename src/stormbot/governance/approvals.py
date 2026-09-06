"""Scoped, expiring approval tokens for human-in-the-loop actions.

An operator approving "send this message to this prospect" in a chat client is
approving one action, for one target, for a bounded window. A token that is
merely a boolean flag on a request is not an approval — the agent can mint it
itself.

Tokens here are HMAC-signed over their own scope, so a token issued for one
action type and target cannot be replayed against another, and cannot be forged
by the process that requests it.
"""

from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

__all__ = ["ApprovalToken", "ApprovalTokenIssuer", "InvalidApprovalToken"]

_SEPARATOR = "."


class InvalidApprovalToken(Exception):
    """Raised when a token is malformed, forged, expired, or out of scope."""


@dataclass(frozen=True)
class ApprovalToken:
    """A parsed, not-yet-verified token."""

    action_type: str
    target_digest: str
    approver: str
    expires_at: datetime
    signature: str

    def encode(self) -> str:
        payload = _payload(self.action_type, self.target_digest, self.approver, self.expires_at)
        return f"{payload}{_SEPARATOR}{self.signature}"


def _payload(action_type: str, target_digest: str, approver: str, expires_at: datetime) -> str:
    expiry = int(expires_at.astimezone(UTC).timestamp())
    raw = f"{action_type}|{target_digest}|{approver}|{expiry}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(payload: str) -> tuple[str, str, str, datetime]:
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        action_type, target_digest, approver, expiry = raw.split("|")
        expires_at = datetime.fromtimestamp(int(expiry), tz=UTC)
    except Exception as exc:  # any decode failure is the same failure mode
        raise InvalidApprovalToken("token payload is malformed") from exc
    return action_type, target_digest, approver, expires_at


class ApprovalTokenIssuer:
    """Issues and verifies approval tokens against a shared secret.

    The secret belongs to the approval surface (the operator bot), not to the
    agent runtime. Splitting them is what makes the token meaningful.
    """

    def __init__(self, secret: bytes, *, default_ttl: timedelta = timedelta(minutes=30)) -> None:
        if len(secret) < 16:
            raise ValueError("approval secret must be at least 16 bytes")
        self._secret = secret
        self._default_ttl = default_ttl

    def issue(
        self,
        *,
        action_type: str,
        target_digest: str,
        approver: str,
        now: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> str:
        now = now or datetime.now(UTC)
        expires_at = now + (ttl or self._default_ttl)
        payload = _payload(action_type, target_digest, approver, expires_at)
        return f"{payload}{_SEPARATOR}{self._sign(payload)}"

    def verify(
        self,
        token: str,
        *,
        action_type: str,
        target_digest: str,
        now: datetime | None = None,
    ) -> ApprovalToken:
        """Return the token if and only if it is authentic, in scope, and live.

        Signature verification happens before expiry and scope checks so that a
        forged token cannot be distinguished from an expired one by timing the
        response.
        """
        now = now or datetime.now(UTC)
        payload, separator, signature = token.partition(_SEPARATOR)
        if not separator or not signature:
            raise InvalidApprovalToken("token is not in payload.signature form")

        if not hmac.compare_digest(signature, self._sign(payload)):
            raise InvalidApprovalToken("token signature does not verify")

        token_action, token_target, approver, expires_at = _decode_payload(payload)
        if not hmac.compare_digest(token_action, action_type):
            raise InvalidApprovalToken("token was issued for a different action type")
        if not hmac.compare_digest(token_target, target_digest):
            raise InvalidApprovalToken("token was issued for a different target")
        if expires_at <= now:
            raise InvalidApprovalToken("token has expired")

        return ApprovalToken(
            action_type=token_action,
            target_digest=token_target,
            approver=approver,
            expires_at=expires_at,
            signature=signature,
        )

    def _sign(self, payload: str) -> str:
        digest = hmac.new(self._secret, payload.encode("ascii"), sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

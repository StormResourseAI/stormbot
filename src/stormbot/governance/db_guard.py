"""Structural guard preventing a test run from reaching production state.

"Don't point the tests at the real database" is a convention, and conventions
fail silently at 2am when an environment variable is inherited from a shell that
was set up for something else. This turns it into an import-time contract: a
process that believes it is running tests refuses to hand out a non-test
database handle at all.

The guard is deliberately allowlist-shaped. A URL it does not recognize as a
test target is rejected, so a new production host added next year fails closed
rather than sliding through a pattern that was never updated.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

__all__ = ["ProductionDatabaseError", "assert_test_database", "is_test_database", "under_test"]

#: Path/name shapes that identify a database as disposable test state.
_TEST_NAME_PATTERN = re.compile(r"(^|[/_\-.])(test|tests|testing|fixture|tmp|temp)([/_\-.]|$)", re.IGNORECASE)

#: Hosts that are never production, regardless of database name.
_LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})

#: Environment variables that mark the process as a test runner.
_TEST_ENV_MARKERS = ("STORMBOT_TEST_MODE", "PYTEST_CURRENT_TEST", "UNITTEST_RUNNING")


class ProductionDatabaseError(RuntimeError):
    """Raised when a test process attempts to bind to non-test state."""


def under_test(env: dict[str, str] | None = None) -> bool:
    environ = os.environ if env is None else env
    return any(environ.get(marker) for marker in _TEST_ENV_MARKERS)


def is_test_database(url: str) -> bool:
    """True only when ``url`` is unambiguously disposable test state."""
    if not url:
        return False

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme in {"sqlite", "sqlite3", ""} or url.startswith("file:"):
        target = parsed.path or url
        if ":memory:" in url or "mode=memory" in url:
            return True
        return bool(_TEST_NAME_PATTERN.search(target))

    if parsed.hostname not in _LOCAL_HOSTS:
        return False

    database = parsed.path.lstrip("/")
    return bool(database) and bool(_TEST_NAME_PATTERN.search(database))


def assert_test_database(url: str, *, env: dict[str, str] | None = None) -> str:
    """Return ``url`` unchanged, or raise if a test process would touch prod.

    Outside a test process this is a no-op passthrough, so production code paths
    are unaffected and there is no reason for anyone to route around it.
    """
    if not under_test(env):
        return url

    if not is_test_database(url):
        raise ProductionDatabaseError(
            "refusing to bind a test process to a database that is not recognized "
            "as test state; use an in-memory database or a *_test target"
        )
    return url

"""Hermeticity: the runtime has no dependencies and the tests touch no network.

Two properties, both worth enforcing rather than documenting.

A zero-dependency runtime means the supply chain for the governance and
assurance code is the Python standard library. That is a deliberate choice for
code whose job is to say no, and it is only true for as long as something checks.

A test suite that reaches the network is a test suite that fails for reasons
unrelated to the code. These tests assert the suite cannot.
"""

from __future__ import annotations

import ast
import socket
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"

FIRST_PARTY = {"stormbot", "tests"}

#: Modules that would let the runtime reach off-box. None of them belong in a
#: package whose entire purpose is to decide whether something is permitted.
#: Matched on the full dotted path, because ``urllib.parse`` is string handling
#: while ``urllib.request`` is a socket.
NETWORK_MODULES = (
    "socket",
    "ssl",
    "ftplib",
    "smtplib",
    "asyncio",
    "http.client",
    "urllib.request",
    "urllib.error",
    "requests",
    "httpx",
    "aiohttp",
)


def python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def imported_modules(path: Path) -> set[str]:
    """Every fully-qualified module name imported by ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def imported_roots(path: Path) -> set[str]:
    return {module.split(".")[0] for module in imported_modules(path)}


def network_imports(path: Path) -> list[str]:
    return sorted(
        module
        for module in imported_modules(path)
        if any(module == target or module.startswith(f"{target}.") for target in NETWORK_MODULES)
    )


class DependencyTests(unittest.TestCase):
    def test_the_runtime_imports_only_the_standard_library(self):
        allowed = set(sys.stdlib_module_names) | FIRST_PARTY
        violations = {
            path.relative_to(REPO_ROOT).as_posix(): sorted(imported_roots(path) - allowed)
            for path in python_files(SOURCE_ROOT)
            if imported_roots(path) - allowed
        }

        self.assertEqual(violations, {})

    def test_the_test_suite_imports_only_the_standard_library(self):
        """Tests that need a dependency to run are tests that stop running."""
        allowed = set(sys.stdlib_module_names) | FIRST_PARTY
        violations = {
            path.relative_to(REPO_ROOT).as_posix(): sorted(imported_roots(path) - allowed)
            for path in python_files(TESTS_ROOT)
            if imported_roots(path) - allowed
        }

        self.assertEqual(violations, {})

    def test_the_runtime_does_not_import_anything_that_can_reach_the_network(self):
        violations = {
            path.relative_to(REPO_ROOT).as_posix(): network_imports(path)
            for path in python_files(SOURCE_ROOT)
            if network_imports(path)
        }

        self.assertEqual(violations, {})

    def test_source_and_tests_are_both_non_empty(self):
        """Guards the three tests above against passing on an empty tree."""
        self.assertGreater(len(python_files(SOURCE_ROOT)), 5)
        self.assertGreater(len(python_files(TESTS_ROOT)), 5)


class NetworkIsolationTests(unittest.TestCase):
    def test_a_full_pipeline_run_opens_no_socket(self):
        opened: list[tuple] = []
        original = socket.socket

        def recording_socket(*args, **kwargs):
            opened.append(args)
            raise AssertionError("the test suite must not open a socket")

        socket.socket = recording_socket  # type: ignore[assignment]
        try:
            from stormbot.assurance import load_bundle
            from stormbot.assurance.registry import default_registry_root
            from stormbot.assurance.release_gate import POLICIES, evaluate

            evaluate(
                load_bundle(default_registry_root(Path(__file__))),
                policy=POLICIES["deployment"],
            )
        finally:
            socket.socket = original  # type: ignore[assignment]

        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()

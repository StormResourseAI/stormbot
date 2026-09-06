"""The repository checks itself for the things a public repository must not have.

This exists because reviewing for leaked material by eye is a control that works
until the one time it doesn't. A public repository holding real credentials or
real third-party contact data is not a cosmetic defect; it is the failure that
makes every other engineering claim in the repository unbelievable.

Three rules are enforced:

1. No file whose *type* is forbidden — databases, archives, key material,
   environment files, editor backups.
2. No credential-shaped string, except in the handful of files whose job is to
   detect or redact them. Those files are named here, so the exception is
   reviewable rather than implicit.
3. No contact data outside the ranges reserved for documentation — phone numbers
   must fall in the 555-01xx fictional block and email addresses must use an
   ``example.*`` domain.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from stormbot.governance.redaction import SECRET_PATTERNS

REPO_ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "artifacts", "node_modules"}

FORBIDDEN_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".bak",
    ".backup",
    ".log",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".tar",
    ".gz",
    ".zip",
    ".dump",
)

FORBIDDEN_NAMES = {".env", "credentials", "credentials.json", "secrets.json", "id_rsa"}

#: Files permitted to contain credential-shaped strings, and why.
DETECTOR_FILES = {
    "src/stormbot/governance/redaction.py": "owns the detector pattern table",
    "tests/contract/test_repository_hygiene.py": "this file, which names the exceptions",
}

TEXT_SUFFIXES = {".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini", ".in", ""}

#: Deliberately narrow. A loose phone pattern matches timestamps and version
#: strings, and a hygiene check that cries wolf gets deleted by the next person.
PHONE_PATTERNS = (
    re.compile(r"\+1\d{10}\b"),
    re.compile(r"\(\d{3}\)\s?\d{3}[.\-]\d{4}\b"),
    re.compile(r"\b\d{3}[.\-]\d{3}[.\-]\d{4}\b"),
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")

#: Reserved for fictional use, so a test fixture can never dial a real person.
FICTIONAL_PREFIX = "55501"
DOCUMENTATION_DOMAINS = ("example.com", "example.org", "example.net")


def repository_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_DIRECTORIES & set(path.relative_to(REPO_ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def text_files() -> list[Path]:
    return [path for path in repository_files() if path.suffix.lower() in TEXT_SUFFIXES]


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


class ForbiddenArtifactTests(unittest.TestCase):
    def test_no_database_archive_or_key_material_is_committed(self):
        offenders = [
            relative(path) for path in repository_files() if path.name.lower().endswith(FORBIDDEN_SUFFIXES)
        ]

        self.assertEqual(offenders, [])

    def test_no_environment_or_credential_file_is_committed(self):
        offenders = [relative(path) for path in repository_files() if path.name.lower() in FORBIDDEN_NAMES]

        self.assertEqual(offenders, [])

    def test_no_editor_backup_of_a_source_file_is_committed(self):
        """Timestamped .bak copies beside their originals read as distrust of git."""
        offenders = [
            relative(path)
            for path in repository_files()
            if re.search(r"\.(bak|orig|save|old)(\.|$)", path.name, re.IGNORECASE)
        ]

        self.assertEqual(offenders, [])

    def test_the_gitignore_covers_the_forbidden_classes(self):
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        for pattern in (".env", "*.db", "*.bak", "logs/", "backups/", "runtime/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignored)


class CredentialScanTests(unittest.TestCase):
    def test_no_credential_shaped_string_appears_outside_the_detector_files(self):
        offenders: dict[str, list[str]] = {}
        for path in text_files():
            name = relative(path)
            if name in DETECTOR_FILES:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            hits = sorted(detector.name for detector in SECRET_PATTERNS if detector.pattern.search(content))
            if hits:
                offenders[name] = hits

        self.assertEqual(offenders, {})

    def test_the_exception_list_only_names_files_that_exist(self):
        """An allowlist entry for a deleted file is a hole waiting to be reused."""
        missing = [name for name in DETECTOR_FILES if not (REPO_ROOT / name).is_file()]

        self.assertEqual(missing, [])


class ContactDataTests(unittest.TestCase):
    def test_every_phone_number_is_in_the_reserved_fictional_range(self):
        offenders: dict[str, list[str]] = {}
        for path in text_files():
            content = path.read_text(encoding="utf-8", errors="replace")
            bad = [
                match.group(0)
                for pattern in PHONE_PATTERNS
                for match in pattern.finditer(content)
                if not _is_fictional(match.group(0))
            ]
            if bad:
                offenders[relative(path)] = sorted(set(bad))

        self.assertEqual(offenders, {})

    def test_every_email_address_uses_a_documentation_domain(self):
        offenders: dict[str, list[str]] = {}
        for path in text_files():
            content = path.read_text(encoding="utf-8", errors="replace")
            bad = [
                match.group(0)
                for match in EMAIL.finditer(content)
                if not match.group(1).lower().endswith(DOCUMENTATION_DOMAINS)
            ]
            if bad:
                offenders[relative(path)] = sorted(set(bad))

        self.assertEqual(offenders, {})


def _is_fictional(candidate: str) -> bool:
    digits = re.sub(r"\D", "", candidate)
    if len(digits) < 10:
        return True  # not a full phone number; version strings and dates land here
    return digits[-7:].startswith(FICTIONAL_PREFIX)


if __name__ == "__main__":
    unittest.main()

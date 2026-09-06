#!/usr/bin/env python3
"""Verify the platform lockfiles still agree with requirements/dev.in.

The failure this prevents is quiet: someone bumps a pin in ``dev.in``, forgets
one of the two lockfiles, and CI keeps installing the old version on one
platform for months. Nothing breaks loudly, and the lockfiles stop meaning
anything.

Run with no arguments; exits non-zero and prints every mismatch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements"
SOURCE = REQUIREMENTS / "dev.in"
LOCKFILES = ("dev.linux.lock.txt", "dev.macos.lock.txt")

PIN = re.compile(r"^([A-Za-z0-9._\-]+)==([A-Za-z0-9._\-+!]+)")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def parse_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PIN.match(stripped)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def hashes_for(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PIN.match(stripped)
        if match:
            current = match.group(1).lower()
            counts.setdefault(current, 0)
        if current:
            counts[current] += len(HASH.findall(stripped))
    return counts


def main() -> int:
    problems: list[str] = []
    expected = parse_pins(SOURCE)

    if not expected:
        problems.append(f"{SOURCE.name} declares no pins")

    for name, version in expected.items():
        if not re.fullmatch(r"\d+(\.\d+)*", version):
            problems.append(f"{SOURCE.name}: {name} is not pinned to an exact version")

    for lockfile in LOCKFILES:
        path = REQUIREMENTS / lockfile
        if not path.is_file():
            problems.append(f"missing lockfile: {lockfile}")
            continue

        locked = parse_pins(path)
        counts = hashes_for(path)

        for name, version in expected.items():
            if name not in locked:
                problems.append(f"{lockfile}: {name} is missing")
            elif locked[name] != version:
                problems.append(f"{lockfile}: {name}=={locked[name]} but dev.in pins {version}")
            elif counts.get(name, 0) == 0:
                problems.append(f"{lockfile}: {name} is pinned without any --hash entry")

        for name in sorted(set(locked) - set(expected)):
            problems.append(f"{lockfile}: {name} is locked but not declared in dev.in")

    if problems:
        print("lockfile drift detected:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"lockfiles agree with {SOURCE.name}: {len(expected)} pinned package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

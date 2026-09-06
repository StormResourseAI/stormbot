#!/usr/bin/env python3
"""Run the release gate over the committed registries under all three policies.

    PYTHONPATH=src python3 examples/release_gate_walkthrough.py

The interesting output is the third one. Nothing in this repository is
`CERTIFIED`, because certification requires evidence bound to an exact commit
SHA, and no such record exists. The gate says so rather than rounding up.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stormbot.assurance import load_bundle
from stormbot.assurance.release_gate import POLICIES, evaluate

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def main() -> int:
    bundle = load_bundle()
    print(
        f"loaded {len(bundle.capabilities)} capabilities, "
        f"{len(bundle.claims)} claims, {len(bundle.evidence_ids)} evidence records\n"
    )

    for name in ("advisory", "deployment", "certification"):
        report = evaluate(bundle, policy=POLICIES[name], now=NOW)
        counts = report.counts
        print(
            f"{name:<14} verdict={report.verdict.value:<5} exit={report.exit_code}  "
            f"({counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail)"
        )
        for check in report.checks:
            if check.status.value != "pass":
                print(f"    {check.status.value}: {check.id} — {check.detail}")

    print("\nEvidence state of each capability, as the ledger sees it:")
    for capability_id in sorted(bundle.capabilities):
        state = bundle.ledger.state_of(capability_id, now=NOW)
        print(f"    {capability_id:<38} {state.value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

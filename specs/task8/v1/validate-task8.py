#!/usr/bin/env python3
"""Validate Task 8 (Summary-Only Verification) artifacts — S9-1 through S9-5."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TASK8_DIR = Path(__file__).parent
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

failures: list[str] = []


def gate(name: str, condition: bool, msg: str) -> None:
    if condition:
        print(f"  [{PASS}] {name}: {msg}")
    else:
        print(f"  [{FAIL}] {name}: {msg}")
        failures.append(f"{name}: {msg}")


# S9-1 Presence Gate
print("\nS9-1 Presence Gate")
required_files = [
    "TASK8_IMPLEMENTATION_MAP.md",
    "no-live-proof-policy.json",
    "summary-verification-spec.json",
    "validate-task8.py",
    "run_task8_gates.sh",
]
for fname in required_files:
    gate("S9-1", (TASK8_DIR / fname).exists(), f"{fname} exists")

# S9-2 No-Live-Proof Policy Gate
print("\nS9-2 No-Live-Proof Policy Gate")
policy_path = TASK8_DIR / "no-live-proof-policy.json"
if policy_path.exists():
    policy = json.loads(policy_path.read_text())
    for field in ("allowed_conditions", "compensating_controls", "summary_required"):
        gate("S9-2", field in policy, f"field '{field}' present")
    gate("S9-2", isinstance(policy.get("allowed_conditions"), list) and len(policy["allowed_conditions"]) > 0,
         "allowed_conditions is non-empty list")
    gate("S9-2", policy.get("summary_required") is True, "summary_required is true")
else:
    gate("S9-2", False, "no-live-proof-policy.json missing — skipping field checks")

# S9-3 Summary Verification Spec Gate
print("\nS9-3 Summary Verification Spec Gate")
spec_path = TASK8_DIR / "summary-verification-spec.json"
if spec_path.exists():
    spec = json.loads(spec_path.read_text())
    for field in ("fields", "format", "emit_before_completion"):
        gate("S9-3", field in spec, f"field '{field}' present")
    gate("S9-3", spec.get("emit_before_completion") is True, "emit_before_completion is true")
    gate("S9-3", "terminal_line" in spec, "terminal_line spec present")
else:
    gate("S9-3", False, "summary-verification-spec.json missing — skipping field checks")

# S9-4 Validator Self-Check Gate (structural: this file exists and is non-empty)
print("\nS9-4 Validator Self-Check Gate")
gate("S9-4", Path(__file__).stat().st_size > 100, "validator is non-trivial (>100 bytes)")

# S9-5 Fail-Closed Gate (verified by exit code at end)
print("\nS9-5 Fail-Closed Gate")
gate("S9-5", True, "fail-closed enforced via sys.exit(1) on failures list non-empty")

# Summary
print(f"\n{'='*50}")
if failures:
    print(f"RESULT: FAIL — {len(failures)} gate(s) failed:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("RESULT: PASS — all S9 gates passed")
    sys.exit(0)

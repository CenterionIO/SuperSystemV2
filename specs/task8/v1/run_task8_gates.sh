#!/usr/bin/env bash
# Run Task 8 gates with fail-closed exit behavior.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=== Task 8 Gates (Summary-Only Verification) ==="
python3 "$SCRIPT_DIR/validate-task8.py"
EXIT=$?

if [ $EXIT -ne 0 ]; then
  echo "GATES FAILED — exit $EXIT" >&2
  exit $EXIT
fi

echo "GATES PASSED"
exit 0

#!/bin/zsh
set -euo pipefail

ROOT="/Users/ai/SuperSystemV2"
VENV_PY="$ROOT/.venv/bin/python"

echo "[1/6] Task 1 gates"
"$VENV_PY" "$ROOT/specs/task1/v1/validate_task1.py"

echo "[2/6] Stage 2 policy gates"
"$VENV_PY" "$ROOT/tools/validate_policy_v1.py"

echo "[3/6] Stage 3 runtime policy smoke"
python3 "$ROOT/tools/runtime_policy_smoke.py"

echo "[4/8] Stage 3 artifact gates"
python3 "$ROOT/specs/task3/v1/validate_task3.py"

echo "[5/8] Stage 4 runtime state-machine smoke"
python3 "$ROOT/tools/runtime_state_machine_smoke.py"

echo "[6/8] Stage 4 runtime orchestrator API smoke"
python3 "$ROOT/tools/runtime_orchestrator_mcp_smoke.py"

echo "[7/8] Stage 4 worker heartbeat/stall smoke"
python3 "$ROOT/tools/runtime_worker_smoke.py"

echo "[8/8] Stage 4 verification backbone artifact gates"
python3 "$ROOT/specs/task4/v1/validate_task4.py"

echo "All Stage 1-4 gates: PASS"

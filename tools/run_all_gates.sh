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

echo "[4/6] Stage 4 runtime state-machine smoke"
python3 "$ROOT/tools/runtime_state_machine_smoke.py"

echo "[5/6] Stage 4 runtime orchestrator API smoke"
python3 "$ROOT/tools/runtime_orchestrator_mcp_smoke.py"

echo "[6/6] Stage 4 worker heartbeat/stall smoke"
python3 "$ROOT/tools/runtime_worker_smoke.py"

echo "All Stage 1-4 gates: PASS"

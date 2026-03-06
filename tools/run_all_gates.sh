#!/bin/zsh
set -euo pipefail

ROOT="/Users/ai/SuperSystemV2"
VENV_PY="$ROOT/.venv/bin/python"

echo "[1/11] Task 1 gates"
"$VENV_PY" "$ROOT/specs/task1/v1/validate_task1.py"

echo "[2/11] Stage 2 policy gates"
"$VENV_PY" "$ROOT/tools/validate_policy_v1.py"

echo "[3/11] Boundary validator"
python3 "$ROOT/tools/validate_boundaries.py"

echo "[4/11] Stage 3 runtime policy smoke"
python3 "$ROOT/tools/runtime_policy_smoke.py"

echo "[5/11] Stage 3 artifact gates"
python3 "$ROOT/specs/task3/v1/validate_task3.py"

echo "[6/11] Stage 4 runtime state-machine smoke"
python3 "$ROOT/tools/runtime_state_machine_smoke.py"

echo "[7/11] Stage 4 runtime orchestrator API smoke"
python3 "$ROOT/tools/runtime_orchestrator_mcp_smoke.py"

echo "[8/11] Stage 4 worker heartbeat/stall smoke"
python3 "$ROOT/tools/runtime_worker_smoke.py"

echo "[9/11] Stage 4 verification backbone artifact gates"
python3 "$ROOT/specs/task4/v1/validate_task4.py"

echo "[10/11] Stage 5 execution and golden-path gates"
python3 "$ROOT/specs/task5/v1/validate_task5.py"

echo "[11/11] Stage 5 verification backbone smoke"
python3 "$ROOT/tools/runtime_verification_backbone_smoke.py"

echo "All Stage 1-5 gates: PASS"

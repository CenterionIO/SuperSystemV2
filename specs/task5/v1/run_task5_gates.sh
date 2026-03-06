#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
python3 "$ROOT/specs/task5/v1/validate_task5.py"
python3 "$ROOT/tools/runtime_verification_backbone_smoke.py"

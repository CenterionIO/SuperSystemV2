#!/bin/zsh
set -euo pipefail
python3 /Users/ai/SuperSystemV2/specs/task5/v1/validate_task5.py
python3 /Users/ai/SuperSystemV2/tools/runtime_verification_backbone_smoke.py

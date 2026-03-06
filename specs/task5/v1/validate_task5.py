#!/usr/bin/env python3
"""Stage 5 validator for verification backbone execution wiring."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path('/Users/ai/SuperSystemV2')


def main() -> int:
    errors: list[str] = []

    runtime_file = ROOT / 'runtime' / 'verification_backbone.py'
    orchestrator_file = ROOT / 'mcp_verify_orchestrator.py'
    engine = ROOT / 'specs' / 'task4' / 'v1' / 'verify-mcp-engine.json'
    abi = ROOT / 'specs' / 'task4' / 'v1' / 'verifier-plugin-abi.json'
    registry = ROOT / 'specs' / 'task4' / 'v1' / 'evidence-registry.json'

    for p in (runtime_file, orchestrator_file, engine, abi, registry):
        if not p.exists():
            errors.append(f'S5-1 missing file: {p}')

    if not errors:
        engine_data = json.loads(engine.read_text())
        if 'supported_check_types' not in engine_data:
            errors.append('S5-1 verify-mcp-engine missing supported_check_types')

    if runtime_file.exists():
        text = runtime_file.read_text()
        if 'apply_fail_closed' not in text:
            errors.append('S5-2 runtime backbone does not call apply_fail_closed')
        if 'verification_artifact' not in text:
            errors.append('S5-3 runtime backbone does not emit verification_artifact')

    if orchestrator_file.exists():
        text = orchestrator_file.read_text()
        if 'VerificationBackbone' not in text:
            errors.append('S5-4 verify orchestrator missing VerificationBackbone import/wiring')
        if 'run(job_id, domain, request)' not in text:
            errors.append('S5-4 verify_run not routing to backbone for non-truth domains')

    if errors:
        print('Stage 5 execution gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 5 execution gates: PASS')
    print('- S5-1: Spec binding')
    print('- S5-2: Fail-closed runtime')
    print('- S5-3: Artifact contract')
    print('- S5-4: Orchestrator integration')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

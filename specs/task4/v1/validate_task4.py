#!/usr/bin/env python3
"""Stage 4 artifact validator for SSV2 verification backbone specs."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path('/Users/ai/SuperSystemV2')
TASK4 = ROOT / 'specs' / 'task4' / 'v1'
POLICY = ROOT / 'policy' / 'v1'


def _load(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    errors: list[str] = []

    engine = _load(TASK4 / 'verify-mcp-engine.json')
    abi = _load(TASK4 / 'verifier-plugin-abi.json')
    registry = _load(TASK4 / 'evidence-registry.json')
    taxonomy = _load(POLICY / 'workflow_taxonomy.json')

    # V1: engine-contract style alignment
    required_steps = {
        'validate_inputs', 'resolve_evidence', 'select_plugins',
        'execute_plugins', 'evaluate_criteria', 'compute_overall_status', 'produce_artifact'
    }
    steps = {s.get('name') for s in engine.get('scoring_algorithm', {}).get('steps', [])}
    missing_steps = required_steps - steps
    if missing_steps:
        errors.append(f'V1 missing engine steps: {sorted(missing_steps)}')
    if engine.get('overall_status_aggregation', {}).get('precedence') != ['blocked', 'fail', 'warn', 'pass']:
        errors.append('V1 invalid overall status precedence')

    # V2: ladder/check coverage against taxonomy required checks
    check_types = set(engine.get('supported_check_types', []))
    for cls, cfg in taxonomy.get('classes', {}).items():
        for check in cfg.get('required_checks', []):
            if check not in check_types:
                errors.append(f'V2 class {cls} check missing in engine: {check}')

    # V3: plugin ABI completeness
    req_in = set(abi.get('input_schema', {}).get('required_fields', []))
    req_out = set(abi.get('output_schema', {}).get('required_fields', []))
    for f in ('invocation_id', 'correlation_id', 'criteria_id', 'check_type', 'evidence_refs'):
        if f not in req_in:
            errors.append(f'V3 missing ABI input field: {f}')
    for f in ('invocation_id', 'correlation_id', 'criteria_id', 'status', 'rationale'):
        if f not in req_out:
            errors.append(f'V3 missing ABI output field: {f}')
    status_enum = set(abi.get('output_schema', {}).get('status_enum', []))
    if 'error' not in status_enum:
        errors.append('V3 ABI output status_enum missing error')

    # V4: evidence registry integrity
    evidence_types = set(registry.get('evidence_types', []))
    required_evidence = set()
    for cfg in taxonomy.get('classes', {}).values():
        required_evidence.update(cfg.get('required_evidence_types', []))
    missing_evidence = required_evidence - evidence_types
    if missing_evidence:
        errors.append(f'V4 missing evidence types: {sorted(missing_evidence)}')
    if registry.get('hash_algorithm') != 'sha256':
        errors.append('V4 hash_algorithm must be sha256')

    # V5: cross-artifact binding sanity
    if not registry.get('id_format', '').startswith('ev_'):
        errors.append('V5 evidence id_format must start with ev_')
    if abi.get('error_handling', {}).get('plugin_errors'):
        for e in abi['error_handling']['plugin_errors']:
            if e.get('engine_response') != 'blocked':
                errors.append(f"V5 plugin error must map to blocked: {e.get('error_type')}")

    if errors:
        print('Stage 4 verification backbone gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 4 verification backbone gates: PASS')
    print('- V1: Engine-contract alignment')
    print('- V2: Ladder/check coverage')
    print('- V3: Plugin ABI completeness')
    print('- V4: Evidence registry integrity')
    print('- V5: Cross-artifact binding')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

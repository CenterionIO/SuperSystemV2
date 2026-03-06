#!/usr/bin/env python3
"""Stage 3 artifact validator for SSV2."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path('/Users/ai/SuperSystemV2')
TASK3 = ROOT / 'specs' / 'task3' / 'v1'
POLICY = ROOT / 'policy' / 'v1'


def _load(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    errors: list[str] = []

    runtime_modes = _load(TASK3 / 'runtime-modes.json')
    loop_cfg = _load(TASK3 / 'loop-control-config.json')
    gate_seq = _load(TASK3 / 'gate-sequence.json')
    enforce = _load(TASK3 / 'enforcement-adapter.json')
    runbook = _load(TASK3 / 'error-lane-runbook.json')

    taxonomy = _load(POLICY / 'workflow_taxonomy.json')
    routing = _load(POLICY / 'routing_policy.json')
    permissions = _load(POLICY / 'permissions_policy.json')

    # R1: enforcement adapter coverage
    required_points = {
        'tool_allowlist',
        'path_scope_guard',
        'network_scope_guard',
        'runtime_guard',
        'verifier_gate',
        'policy_engine',
    }
    points = set(enforce.get('enforcement_points', {}).keys())
    missing = required_points - points
    if missing:
        errors.append(f'R1 missing enforcement points: {sorted(missing)}')
    for p in required_points & points:
        ep = enforce['enforcement_points'][p]
        if not ep.get('intercept_at'):
            errors.append(f'R1 {p} missing intercept_at')
        if not ep.get('check_logic'):
            errors.append(f'R1 {p} missing check_logic')

    # R2: mode/workflow mapping
    classes = set(taxonomy['classes'].keys())
    covered: set[str] = set()
    for mode_name, mode in runtime_modes.get('modes', {}).items():
        wf = set(mode.get('workflow_classes', []))
        covered |= wf
        unknown = wf - classes
        if unknown:
            errors.append(f'R2 {mode_name} unknown workflow classes: {sorted(unknown)}')
    if classes - covered:
        errors.append(f'R2 uncovered workflow classes: {sorted(classes - covered)}')

    # R3: runbook coverage
    rule_classes = {r.get('classification') for r in runbook.get('error_classification', {}).get('rules', [])}
    for c in ('workflow_error', 'platform_error'):
        if c not in rule_classes:
            errors.append(f'R3 missing error classification: {c}')
    for action in runbook.get('recovery_runbook', {}).get('actions', []):
        if 'max_attempts' not in action:
            errors.append(f"R3 action {action.get('action_id')} missing max_attempts")

    # R4: gate sequence alignment
    valid_states = {
        'research', 'research_rework', 'planning', 'plan_rework', 'implementation',
        'verifying', 'build_rework', 'blocked_evidence', 'completed', 'escalation'
    }
    for gate_id, gate in gate_seq.get('gates', {}).items():
        fire = gate.get('fires_at_state')
        if fire not in valid_states:
            errors.append(f'R4 {gate_id} invalid fires_at_state: {fire}')
        routing_obj = gate.get('routing', {})
        for key in ('pass', 'fail', 'blocked'):
            if routing_obj.get(key) not in valid_states:
                errors.append(f'R4 {gate_id} invalid routing.{key}: {routing_obj.get(key)}')
        if not gate.get('required_artifacts'):
            errors.append(f'R4 {gate_id} missing required_artifacts')

    # R5: loop control completeness
    hb = loop_cfg.get('heartbeat_policy', {})
    if int(hb.get('interval_seconds', 0)) <= 0:
        errors.append('R5 heartbeat interval_seconds invalid')
    if int(hb.get('stall_threshold_missed_beats', 0)) <= 0:
        errors.append('R5 heartbeat stall_threshold_missed_beats invalid')
    if hb.get('stall_action') != 'blocked_platform':
        errors.append('R5 heartbeat stall_action must be blocked_platform')

    # Small consistency checks against policy
    if set(routing.get('classes', {}).keys()) != classes:
        errors.append('Consistency: routing_policy classes mismatch workflow_taxonomy')
    if 'Orchestrator' not in permissions.get('roles', {}):
        errors.append('Consistency: permissions missing Orchestrator role')

    if errors:
        print('Stage 3 runtime gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 3 runtime gates: PASS')
    print('- R1: Enforcement adapter coverage')
    print('- R2: Mode-workflow mapping')
    print('- R3: Error runbook coverage')
    print('- R4: Gate sequence alignment')
    print('- R5: Loop control completeness')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

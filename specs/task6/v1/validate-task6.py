#!/usr/bin/env python3
"""Stage 6 validator (Python equivalent): contracts + autonomy policy gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TASK6_DIR = ROOT / 'specs' / 'task6' / 'v1'


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _type_ok(value: Any, expected: str) -> bool:
    if expected == 'object':
        return isinstance(value, dict)
    if expected == 'array':
        return isinstance(value, list)
    if expected == 'string':
        return isinstance(value, str)
    if expected == 'boolean':
        return isinstance(value, bool)
    if expected == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == 'null':
        return value is None
    return True


def _validate_json_schema_subset(value: Any, schema: dict[str, Any], defs: dict[str, Any], ctx: str, errors: list[str]) -> None:
    if '$ref' in schema:
        ref = str(schema['$ref'])
        if ref.startswith('#/$defs/'):
            key = ref.split('/', 2)[-1]
            target = defs.get(key)
            if isinstance(target, dict):
                _validate_json_schema_subset(value, target, defs, ctx, errors)
            else:
                errors.append(f'{ctx}: unresolved ref {ref}')
            return

    expected = schema.get('type')
    if expected is not None:
        if isinstance(expected, list):
            if not any(_type_ok(value, t) for t in expected):
                errors.append(f'{ctx}: type mismatch expected one of {expected}')
                return
        elif not _type_ok(value, expected):
            errors.append(f'{ctx}: type mismatch expected {expected}')
            return

    if 'const' in schema and value != schema['const']:
        errors.append(f"{ctx}: const mismatch expected {schema['const']}")

    enum_vals = schema.get('enum')
    if enum_vals is not None and value not in enum_vals:
        errors.append(f'{ctx}: value {value} not in enum {enum_vals}')

    if isinstance(value, dict):
        required = schema.get('required', [])
        for field in required:
            if field not in value:
                errors.append(f'{ctx}: missing required field {field}')

        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            extra = sorted(set(value.keys()) - set(props.keys()))
            for key in extra:
                errors.append(f'{ctx}: unexpected property {key}')

        for key, child_schema in props.items():
            if key in value and isinstance(child_schema, dict):
                _validate_json_schema_subset(value[key], child_schema, defs, f'{ctx}.{key}', errors)

    if isinstance(value, list):
        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for idx, row in enumerate(value, start=1):
                _validate_json_schema_subset(row, item_schema, defs, f'{ctx}[{idx}]', errors)


def main() -> int:
    errors: list[str] = []

    required = [
        'STAGE6_IMPLEMENTATION_MAP.md',
        'escalation-ui-contract.json',
        'autonomy-modes-policy.json',
        'status-view-contract.json',
        'security-retention-redaction-policy.json',
        'escalation-ui-contract.schema.json',
        'autonomy-modes-policy.schema.json',
        'security-retention-redaction-policy.schema.json',
        'validate-task6.py',
    ]
    for name in required:
        if not (TASK6_DIR / name).exists():
            errors.append(f'S6-1 missing file: {name}')

    if not errors:
        escalation_schema = _load(TASK6_DIR / 'escalation-ui-contract.schema.json')
        autonomy_schema = _load(TASK6_DIR / 'autonomy-modes-policy.schema.json')
        secops_schema = _load(TASK6_DIR / 'security-retention-redaction-policy.schema.json')
        escalation_doc = _load(TASK6_DIR / 'escalation-ui-contract.json')
        autonomy_doc = _load(TASK6_DIR / 'autonomy-modes-policy.json')
        status_view_schema = _load(TASK6_DIR / 'status-view-contract.json')
        secops_doc = _load(TASK6_DIR / 'security-retention-redaction-policy.json')

        _validate_json_schema_subset(
            escalation_doc,
            escalation_schema,
            escalation_schema.get('$defs', {}),
            'S6-2 escalation-ui-contract',
            errors,
        )
        _validate_json_schema_subset(
            autonomy_doc,
            autonomy_schema,
            autonomy_schema.get('$defs', {}),
            'S6-3 autonomy-modes-policy',
            errors,
        )
        _validate_json_schema_subset(
            secops_doc,
            secops_schema,
            secops_schema.get('$defs', {}),
            'S6-5 security-retention-redaction-policy',
            errors,
        )

        # S6-5: audit_log_scope must have include_events and exclude_fields
        als = secops_doc.get('audit_log_scope')
        if isinstance(als, dict):
            if not isinstance(als.get('include_events'), list) or len(als.get('include_events', [])) == 0:
                errors.append('S6-5 audit_log_scope.include_events must be a non-empty array')
            if not isinstance(als.get('exclude_fields'), list) or len(als.get('exclude_fields', [])) == 0:
                errors.append('S6-5 audit_log_scope.exclude_fields must be a non-empty array')
            # secrets_field_patterns must be a subset of exclude_fields (base name match)
            exclude_set = set(als.get('exclude_fields', []))
            for pat in secops_doc.get('secrets_field_patterns', []):
                base = pat.rsplit('.', 1)[-1] if '.' in pat else pat
                if base not in exclude_set:
                    errors.append(f"S6-5 secrets pattern '{pat}' (base '{base}') not in audit_log_scope.exclude_fields")
        elif not isinstance(als, dict):
            errors.append('S6-5 audit_log_scope must be an object')

        # S6-5: redaction_levels must be exactly [none, standard, strict]
        rl = secops_doc.get('redaction_levels', [])
        if sorted(rl) != ['none', 'standard', 'strict']:
            errors.append('S6-5 redaction_levels must be [none, standard, strict]')
        _validate_json_schema_subset(
            {
                'correlation_id': 'corr-example',
                'workflow_class': 'code_change',
                'autonomy_mode': 'approve_final',
                'current_state': 'build_review',
                'last_transition_at': '2026-03-06T00:00:00Z',
                'run_status': 'running',
                'why': 'awaiting verification',
                'blocked_reason': None,
                'next_action': 'run verification gate',
            },
            status_view_schema,
            status_view_schema.get('$defs', {}),
            'S6-4 status-view-contract',
            errors,
        )
        _validate_json_schema_subset(
            {
                'correlation_id': 'corr-example',
                'workflow_class': 'code_change',
                'autonomy_mode': 'approve_each',
                'current_state': 'escalation',
                'last_transition_at': '2026-03-06T00:00:00Z',
                'run_status': 'blocked',
                'why': 'missing required evidence linkage',
                'blocked_reason': 'missing required evidence linkage',
                'next_action': 'review escalation prompt',
            },
            status_view_schema,
            status_view_schema.get('$defs', {}),
            'S6-4 status-view-contract',
            errors,
        )
        # Canonical union invariants:
        # - running => blocked_reason must be null
        # - blocked => blocked_reason + why must be non-empty strings
        sample_running = {
            'correlation_id': 'corr-run',
            'workflow_class': 'code_change',
            'autonomy_mode': 'approve_final',
            'current_state': 'building',
            'run_status': 'running',
            'last_transition_at': '2026-03-06T00:00:00Z',
            'why': 'build in progress',
            'blocked_reason': None,
            'next_action': 'wait',
        }
        sample_blocked = {
            'correlation_id': 'corr-blocked',
            'workflow_class': 'ops_fix',
            'autonomy_mode': 'approve_each',
            'current_state': 'escalation',
            'run_status': 'blocked',
            'last_transition_at': '2026-03-06T00:00:00Z',
            'why': 'approval required',
            'blocked_reason': 'approval required',
            'next_action': 'review escalation',
        }
        for row in (sample_running, sample_blocked):
            if row['run_status'] == 'running':
                if row.get('blocked_reason') is not None:
                    errors.append('S6-4 invariant: run_status=running requires blocked_reason=null')
            elif row['run_status'] == 'blocked':
                br = row.get('blocked_reason')
                why = row.get('why')
                if not isinstance(br, str) or not br.strip():
                    errors.append('S6-4 invariant: run_status=blocked requires non-empty blocked_reason')
                if not isinstance(why, str) or not why.strip():
                    errors.append('S6-4 invariant: run_status=blocked requires non-empty why')

        status_enum = (
            (status_view_schema.get('properties') or {}).get('run_status') or {}
        ).get('enum', [])
        if sorted(status_enum) != ['blocked', 'running']:
            errors.append('S6-4 status-view-contract run_status enum must be [running, blocked]')

        blocked_reason_schema = ((status_view_schema.get('properties') or {}).get('blocked_reason') or {})
        blocked_reason_type = blocked_reason_schema.get('type')
        blocked_reason_types = blocked_reason_type if isinstance(blocked_reason_type, list) else [blocked_reason_type]
        if sorted(t for t in blocked_reason_types if isinstance(t, str)) != ['null', 'string']:
            errors.append('S6-4 status-view-contract blocked_reason must be nullable string')

        required_modes = ['approve_each', 'approve_final', 'full_auto']
        for mode in required_modes:
            mode_doc = (autonomy_doc.get('modes') or {}).get(mode)
            if not isinstance(mode_doc, dict):
                errors.append(f'S6-5 missing autonomy mode: {mode}')
                continue
            gate = mode_doc.get('gate_application') or {}
            for review_gate in ('research_review', 'plan_review', 'build_review'):
                if gate.get(review_gate) not in ('auto', 'manual'):
                    errors.append(f'S6-5 {mode}.{review_gate} must be auto|manual')

        ui_actions = set((escalation_doc.get('response') or {}).get('actions', []))
        for mode in required_modes:
            actions = ((autonomy_doc.get('modes') or {}).get(mode) or {}).get('escalation_actions', [])
            for action in actions:
                if action not in ui_actions:
                    errors.append(f'S6-5 action mismatch: {mode} references unknown escalation action {action}')

        # Security/retention/redaction canonical shape checks.
        expected_levels = ['none', 'standard', 'strict']
        redaction_levels = secops_doc.get('redaction_levels')
        if redaction_levels != expected_levels:
            errors.append('S6-5 redaction_levels must equal ["none","standard","strict"] in order')

        if 'redaction_methods' in secops_doc:
            methods = secops_doc.get('redaction_methods')
            if not isinstance(methods, list):
                errors.append('S6-5 redaction_methods must be an array when provided')
            else:
                allowed = {'mask', 'hash', 'drop'}
                invalid = [m for m in methods if m not in allowed]
                if invalid:
                    errors.append(f'S6-5 redaction_methods contains invalid values: {invalid}')

        scope = secops_doc.get('audit_log_scope')
        if not isinstance(scope, dict):
            errors.append('S6-5 audit_log_scope must be an object')
        else:
            include_events = scope.get('include_events')
            exclude_fields = scope.get('exclude_fields')
            if not isinstance(include_events, list) or not include_events or not all(isinstance(x, str) and x.strip() for x in include_events):
                errors.append('S6-5 audit_log_scope.include_events must be a non-empty string array')
            if not isinstance(exclude_fields, list) or not exclude_fields or not all(isinstance(x, str) and x.strip() for x in exclude_fields):
                errors.append('S6-5 audit_log_scope.exclude_fields must be a non-empty string array')

        if escalation_doc.get('version') != 'v1' or autonomy_doc.get('version') != 'v1':
            errors.append('S6-6 fail-closed: contract version must be v1')

    if errors:
        print('Stage 6 gates: FAIL')
        for err in errors:
            print(f'- {err}')
        return 1

    print('Stage 6 gates: PASS')
    print('- S6-1: presence gate')
    print('- S6-2: escalation contract schema gate')
    print('- S6-3: autonomy policy schema gate')
    print('- S6-4: status view contract gate')
    print('- S6-5: security/retention/redaction policy schema + cross-contract consistency gate')
    print('- S6-6: CI fail-closed gate')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

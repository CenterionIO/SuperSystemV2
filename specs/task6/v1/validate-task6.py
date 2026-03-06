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
        'escalation-ui-contract.schema.json',
        'autonomy-modes-policy.schema.json',
        'validate-task6.py',
    ]
    for name in required:
        if not (TASK6_DIR / name).exists():
            errors.append(f'S6-1 missing file: {name}')

    if not errors:
        escalation_schema = _load(TASK6_DIR / 'escalation-ui-contract.schema.json')
        autonomy_schema = _load(TASK6_DIR / 'autonomy-modes-policy.schema.json')
        escalation_doc = _load(TASK6_DIR / 'escalation-ui-contract.json')
        autonomy_doc = _load(TASK6_DIR / 'autonomy-modes-policy.json')

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

        required_modes = ['approve_each', 'approve_final', 'full_auto']
        for mode in required_modes:
            mode_doc = (autonomy_doc.get('modes') or {}).get(mode)
            if not isinstance(mode_doc, dict):
                errors.append(f'S6-4 missing autonomy mode: {mode}')
                continue
            gate = mode_doc.get('gate_application') or {}
            for review_gate in ('research_review', 'plan_review', 'build_review'):
                if gate.get(review_gate) not in ('auto', 'manual'):
                    errors.append(f'S6-4 {mode}.{review_gate} must be auto|manual')

        ui_actions = set((escalation_doc.get('response') or {}).get('actions', []))
        for mode in required_modes:
            actions = ((autonomy_doc.get('modes') or {}).get(mode) or {}).get('escalation_actions', [])
            for action in actions:
                if action not in ui_actions:
                    errors.append(f'S6-4 action mismatch: {mode} references unknown escalation action {action}')

        if escalation_doc.get('version') != 'v1' or autonomy_doc.get('version') != 'v1':
            errors.append('S6-5 fail-closed: contract version must be v1')

    if errors:
        print('Stage 6 gates: FAIL')
        for err in errors:
            print(f'- {err}')
        return 1

    print('Stage 6 gates: PASS')
    print('- S6-1: presence gate')
    print('- S6-2: escalation contract schema gate')
    print('- S6-3: autonomy policy schema gate')
    print('- S6-4: cross-contract consistency gate')
    print('- S6-5: CI fail-closed gate')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stage 8 (task7) production hardening validator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TASK7_DIR = ROOT / 'specs' / 'task7' / 'v1'


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

    map_file = TASK7_DIR / 'STAGE8_IMPLEMENTATION_MAP.md'
    versioning_path = TASK7_DIR / 'versioning-migration-policy.json'
    replay_path = TASK7_DIR / 'replayability-spec.json'
    risk_path = TASK7_DIR / 'risk-tiers-policy.json'
    ci_path = TASK7_DIR / 'policy-as-code-ci-requirements.json'
    validator_path = TASK7_DIR / 'validate-task7.py'
    runner_path = TASK7_DIR / 'run_task7_gates.sh'

    required = [map_file, versioning_path, replay_path, risk_path, ci_path, validator_path, runner_path]
    for path in required:
        if not path.exists():
            errors.append(f'S8-1 missing required file: {path.name}')

    if not errors:
        # a) versioning-migration-policy.json
        versioning = _load(versioning_path)
        _validate_json_schema_subset(
            versioning,
            {
                'type': 'object',
                'required': ['version', 'semver_policy', 'backward_compat_window', 'migration_strategy'],
                'properties': {
                    'version': {'type': 'string'},
                    'semver_policy': {'type': 'object'},
                    'backward_compat_window': {'type': 'object'},
                    'migration_strategy': {'type': 'object'}
                },
                'additionalProperties': True
            },
            {},
            'S8-2 versioning-migration-policy',
            errors,
        )

        # b) replayability-spec.json
        replay = _load(replay_path)
        _validate_json_schema_subset(
            replay,
            {
                'type': 'object',
                'required': ['version', 'required_artifacts', 'replay_inputs', 'determinism_requirements'],
                'properties': {
                    'version': {'type': 'string'},
                    'required_artifacts': {'type': 'array', 'items': {'type': 'string'}},
                    'replay_inputs': {'type': 'object'},
                    'determinism_requirements': {'type': 'object'}
                },
                'additionalProperties': True
            },
            {},
            'S8-3 replayability-spec',
            errors,
        )

        # c) risk-tiers-policy.json
        risk = _load(risk_path)
        _validate_json_schema_subset(
            risk,
            {
                'type': 'object',
                'required': ['version', 'tiers', 'tier_rules'],
                'properties': {
                    'version': {'type': 'string'},
                    'tiers': {'type': 'array', 'items': {'type': 'string'}},
                    'tier_rules': {'type': 'object'}
                },
                'additionalProperties': True
            },
            {},
            'S8-4 risk-tiers-policy',
            errors,
        )
        tiers = risk.get('tiers', []) if isinstance(risk, dict) else []
        if sorted(tiers) != ['high', 'low', 'med']:
            errors.append('S8-4 risk-tiers-policy tiers must be exactly [low, med, high]')
        tier_rules = risk.get('tier_rules', {}) if isinstance(risk, dict) else {}
        for tier in ('low', 'med', 'high'):
            row = tier_rules.get(tier)
            if not isinstance(row, dict):
                errors.append(f'S8-4 missing tier_rules entry for {tier}')
                continue
            if 'autonomy' not in row or 'required_gates' not in row:
                errors.append(f'S8-4 tier_rules.{tier} must include autonomy + required_gates')
            if not isinstance(row.get('required_gates'), list):
                errors.append(f'S8-4 tier_rules.{tier}.required_gates must be array')

        low_gates = set((tier_rules.get('low') or {}).get('required_gates', []))
        med_gates = set((tier_rules.get('med') or {}).get('required_gates', []))
        high_gates = set((tier_rules.get('high') or {}).get('required_gates', []))
        if not low_gates.issubset(med_gates):
            errors.append('S8-4 gate hierarchy violation: low.required_gates must be subset of med.required_gates')
        if not med_gates.issubset(high_gates):
            errors.append('S8-4 gate hierarchy violation: med.required_gates must be subset of high.required_gates')
        if not (len(low_gates) < len(med_gates)):
            errors.append('S8-4 gate cardinality violation: low.required_gates must be strictly fewer than med.required_gates')
        if not (len(med_gates) <= len(high_gates)):
            errors.append('S8-4 gate cardinality violation: med.required_gates must be fewer or equal to high.required_gates')

        # d) policy-as-code-ci-requirements.json
        ci = _load(ci_path)
        _validate_json_schema_subset(
            ci,
            {
                'type': 'object',
                'required': ['version', 'required_workflows', 'required_commands', 'fail_conditions'],
                'properties': {
                    'version': {'type': 'string'},
                    'required_workflows': {'type': 'array', 'items': {'type': 'string'}},
                    'required_commands': {'type': 'array', 'items': {'type': 'string'}},
                    'fail_conditions': {'type': 'array', 'items': {'type': 'string'}}
                },
                'additionalProperties': True
            },
            {},
            'S8-5 policy-as-code-ci-requirements',
            errors,
        )

    if errors:
        print('Stage 8 gates: FAIL')
        for err in errors:
            print(f'- {err}')
        return 1

    print('Stage 8 gates: PASS')
    print('- S8-1: presence gate')
    print('- S8-2: versioning/migration gate')
    print('- S8-3: replayability gate')
    print('- S8-4: risk tier gate')
    print('- S8-5: policy-as-code CI gate')
    print('- S8-6: fail-closed gate')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

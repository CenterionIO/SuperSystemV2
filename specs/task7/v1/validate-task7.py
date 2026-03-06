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


def _require_non_empty_string(value: Any, ctx: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f'{ctx} must be a non-empty string')


def _require_non_empty_array(value: Any, ctx: str, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) == 0:
        errors.append(f'{ctx} must be a non-empty array')


def _enforce_no_additional_properties(obj: Any, allowed: set[str], ctx: str, errors: list[str]) -> None:
    if not isinstance(obj, dict):
        errors.append(f'{ctx} must be an object')
        return
    extras = sorted(set(obj.keys()) - allowed)
    for key in extras:
        errors.append(f'{ctx} has disallowed additional property: {key}')


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

    versioning: dict[str, Any] = {}
    replay: dict[str, Any] = {}
    risk: dict[str, Any] = {}
    ci: dict[str, Any] = {}

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
                    'semver_policy': {
                        'type': 'object',
                        'required': ['format', 'breaking_change_triggers', 'minor_change_triggers', 'patch_change_triggers'],
                        'properties': {
                            'format': {'type': 'string'},
                            'breaking_change_triggers': {'type': 'array', 'items': {'type': 'string'}},
                            'minor_change_triggers': {'type': 'array', 'items': {'type': 'string'}},
                            'patch_change_triggers': {'type': 'array', 'items': {'type': 'string'},
                            },
                        },
                        'additionalProperties': False,
                    },
                    'backward_compat_window': {
                        'type': 'object',
                        'required': ['duration_days', 'strategy', 'deprecation_notice_required'],
                        'properties': {
                            'duration_days': {'type': 'integer'},
                            'strategy': {'type': 'string'},
                            'deprecation_notice_required': {'type': 'boolean'},
                        },
                        'additionalProperties': False,
                    },
                    'migration_strategy': {
                        'type': 'object',
                        'required': ['approach', 'rollback_supported', 'data_migration_required', 'validation_before_cutover'],
                        'properties': {
                            'approach': {'type': 'string'},
                            'rollback_supported': {'type': 'boolean'},
                            'data_migration_required': {'type': 'boolean'},
                            'validation_before_cutover': {'type': 'boolean'},
                        },
                        'additionalProperties': False,
                    },
                },
                'additionalProperties': False
            },
            {},
            'S8-2 versioning-migration-policy',
            errors,
        )
        semver = versioning.get('semver_policy') if isinstance(versioning.get('semver_policy'), dict) else {}
        if semver.get('format') != 'major.minor.patch':
            errors.append('S8-2 semver_policy.format must be "major.minor.patch"')
        _require_non_empty_array(semver.get('breaking_change_triggers'), 'S8-2 semver_policy.breaking_change_triggers', errors)
        _require_non_empty_array(semver.get('minor_change_triggers'), 'S8-2 semver_policy.minor_change_triggers', errors)
        _require_non_empty_array(semver.get('patch_change_triggers'), 'S8-2 semver_policy.patch_change_triggers', errors)

        bc = versioning.get('backward_compat_window') if isinstance(versioning.get('backward_compat_window'), dict) else {}
        if not isinstance(bc.get('duration_days'), int) or bc.get('duration_days', 0) < 1:
            errors.append('S8-2 backward_compat_window.duration_days must be a positive integer')
        _require_non_empty_string(bc.get('strategy'), 'S8-2 backward_compat_window.strategy', errors)
        if not isinstance(bc.get('deprecation_notice_required'), bool):
            errors.append('S8-2 backward_compat_window.deprecation_notice_required must be boolean')

        ms = versioning.get('migration_strategy') if isinstance(versioning.get('migration_strategy'), dict) else {}
        _require_non_empty_string(ms.get('approach'), 'S8-2 migration_strategy.approach', errors)
        if not isinstance(ms.get('rollback_supported'), bool):
            errors.append('S8-2 migration_strategy.rollback_supported must be boolean')
        if not isinstance(ms.get('data_migration_required'), bool):
            errors.append('S8-2 migration_strategy.data_migration_required must be boolean')
        if not isinstance(ms.get('validation_before_cutover'), bool):
            errors.append('S8-2 migration_strategy.validation_before_cutover must be boolean')

        # b) replayability-spec.json
        replay = _load(replay_path)
        _validate_json_schema_subset(
            replay,
            {
                'type': 'object',
                'required': [
                    'version',
                    'hash_algorithm',
                    'timestamp_handling',
                    'random_seed_policy',
                    'required_artifacts',
                    'replay_inputs',
                    'determinism_requirements'
                ],
                'properties': {
                    'version': {'type': 'string'},
                    'hash_algorithm': {'type': 'string'},
                    'timestamp_handling': {'type': 'string'},
                    'random_seed_policy': {'type': 'string'},
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
        if replay.get('hash_algorithm') != 'sha256':
            errors.append('S8-3 hash_algorithm must be sha256')
        if replay.get('timestamp_handling') not in {'capture_not_replay', 'replay_from_trace'}:
            errors.append('S8-3 timestamp_handling must be capture_not_replay|replay_from_trace')
        if replay.get('random_seed_policy') not in {'not_used', 'fixed'}:
            errors.append('S8-3 random_seed_policy must be not_used|fixed')
        det_req = replay.get('determinism_requirements') if isinstance(replay.get('determinism_requirements'), dict) else {}
        if det_req.get('stable_gate_outcomes_given_same_inputs') is not True:
            errors.append('S8-3 determinism_requirements.stable_gate_outcomes_given_same_inputs must be true')
        _require_non_empty_string(
            det_req.get('stable_gate_outcomes_mechanism_notes'),
            'S8-3 determinism_requirements.stable_gate_outcomes_mechanism_notes',
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

        # S8-6 fail-closed checks: explicit version pin + no additional properties + non-empty required values.
        for name, doc in (
            ('versioning-migration-policy.json', versioning),
            ('replayability-spec.json', replay),
            ('risk-tiers-policy.json', risk),
            ('policy-as-code-ci-requirements.json', ci),
        ):
            if str(doc.get('version', '')) != 'v1':
                errors.append(f'S8-6 {name} version must be exactly v1')

        _enforce_no_additional_properties(
            versioning,
            {'version', 'semver_policy', 'backward_compat_window', 'migration_strategy'},
            'S8-6 versioning-migration-policy',
            errors,
        )
        _enforce_no_additional_properties(
            replay,
            {
                'version',
                'hash_algorithm',
                'timestamp_handling',
                'random_seed_policy',
                'required_artifacts',
                'replay_inputs',
                'determinism_requirements'
            },
            'S8-6 replayability-spec',
            errors,
        )
        _enforce_no_additional_properties(
            risk,
            {'version', 'tiers', 'tier_rules'},
            'S8-6 risk-tiers-policy',
            errors,
        )
        _enforce_no_additional_properties(
            ci,
            {'version', 'required_workflows', 'required_commands', 'fail_conditions'},
            'S8-6 policy-as-code-ci-requirements',
            errors,
        )

        _require_non_empty_string(versioning.get('version'), 'S8-6 versioning.version', errors)
        _require_non_empty_string(replay.get('version'), 'S8-6 replayability.version', errors)
        _require_non_empty_string(risk.get('version'), 'S8-6 risk.version', errors)
        _require_non_empty_string(ci.get('version'), 'S8-6 ci.version', errors)
        _require_non_empty_array(replay.get('required_artifacts'), 'S8-6 replayability.required_artifacts', errors)
        _require_non_empty_array(ci.get('required_workflows'), 'S8-6 ci.required_workflows', errors)
        _require_non_empty_array(ci.get('required_commands'), 'S8-6 ci.required_commands', errors)
        _require_non_empty_array(ci.get('fail_conditions'), 'S8-6 ci.fail_conditions', errors)

        # Nested strictness for core objects.
        _enforce_no_additional_properties(
            versioning.get('semver_policy'),
            {'format', 'breaking_change_triggers', 'minor_change_triggers', 'patch_change_triggers'},
            'S8-6 versioning.semver_policy',
            errors,
        )
        _enforce_no_additional_properties(
            versioning.get('backward_compat_window'),
            {'duration_days', 'strategy', 'deprecation_notice_required'},
            'S8-6 versioning.backward_compat_window',
            errors,
        )
        _enforce_no_additional_properties(
            versioning.get('migration_strategy'),
            {'approach', 'rollback_supported', 'data_migration_required', 'validation_before_cutover'},
            'S8-6 versioning.migration_strategy',
            errors,
        )
        _enforce_no_additional_properties(
            replay.get('replay_inputs'),
            {'required', 'optional'},
            'S8-6 replayability.replay_inputs',
            errors,
        )
        _enforce_no_additional_properties(
            replay.get('determinism_requirements'),
            {
                'stable_evidence_ids',
                'stable_artifact_paths',
                'stable_gate_outcomes_given_same_inputs',
                'stable_gate_outcomes_mechanism_notes'
            },
            'S8-6 replayability.determinism_requirements',
            errors,
        )

        semver = versioning.get('semver_policy') if isinstance(versioning.get('semver_policy'), dict) else {}
        if semver.get('format') != 'major.minor.patch':
            errors.append('S8-6 semver_policy.format must be "major.minor.patch"')
        _require_non_empty_array(semver.get('breaking_change_triggers'), 'S8-6 semver_policy.breaking_change_triggers', errors)
        _require_non_empty_array(semver.get('minor_change_triggers'), 'S8-6 semver_policy.minor_change_triggers', errors)
        _require_non_empty_array(semver.get('patch_change_triggers'), 'S8-6 semver_policy.patch_change_triggers', errors)

        bc = versioning.get('backward_compat_window') if isinstance(versioning.get('backward_compat_window'), dict) else {}
        if not isinstance(bc.get('duration_days'), int) or bc.get('duration_days', 0) < 1:
            errors.append('S8-6 backward_compat_window.duration_days must be positive integer')
        _require_non_empty_string(bc.get('strategy'), 'S8-6 backward_compat_window.strategy', errors)
        if not isinstance(bc.get('deprecation_notice_required'), bool):
            errors.append('S8-6 backward_compat_window.deprecation_notice_required must be boolean')

        mig = versioning.get('migration_strategy') if isinstance(versioning.get('migration_strategy'), dict) else {}
        _require_non_empty_string(mig.get('approach'), 'S8-6 migration_strategy.approach', errors)
        if not isinstance(mig.get('rollback_supported'), bool):
            errors.append('S8-6 migration_strategy.rollback_supported must be boolean')
        if not isinstance(mig.get('data_migration_required'), bool):
            errors.append('S8-6 migration_strategy.data_migration_required must be boolean')
        if not isinstance(mig.get('validation_before_cutover'), bool):
            errors.append('S8-6 migration_strategy.validation_before_cutover must be boolean')

        replay_inputs = replay.get('replay_inputs') if isinstance(replay.get('replay_inputs'), dict) else {}
        _require_non_empty_array(replay_inputs.get('required'), 'S8-6 replay_inputs.required', errors)
        if not isinstance(replay_inputs.get('optional'), list):
            errors.append('S8-6 replay_inputs.optional must be array')
        if replay.get('hash_algorithm') != 'sha256':
            errors.append('S8-6 hash_algorithm must be sha256')
        if replay.get('timestamp_handling') not in {'capture_not_replay', 'replay_from_trace'}:
            errors.append('S8-6 timestamp_handling must be capture_not_replay|replay_from_trace')
        if replay.get('random_seed_policy') not in {'not_used', 'fixed'}:
            errors.append('S8-6 random_seed_policy must be not_used|fixed')

        det = replay.get('determinism_requirements') if isinstance(replay.get('determinism_requirements'), dict) else {}
        for key in ('stable_evidence_ids', 'stable_artifact_paths', 'stable_gate_outcomes_given_same_inputs'):
            if not isinstance(det.get(key), bool):
                errors.append(f'S8-6 determinism_requirements.{key} must be boolean')
        _require_non_empty_string(
            det.get('stable_gate_outcomes_mechanism_notes'),
            'S8-6 determinism_requirements.stable_gate_outcomes_mechanism_notes',
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

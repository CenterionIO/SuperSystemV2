#!/usr/bin/env python3
"""Stage 5 validator: executable golden flows + artifact/contract conformance."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.policy_engine import load_policy_bundle
from runtime.verification_backbone import VerificationBackbone


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
    if expected == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == 'null':
        return value is None
    return True


def _validate_json_schema_subset(value: Any, schema: dict[str, Any], ctx: str, errors: list[str]) -> None:
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
                _validate_json_schema_subset(value[key], child_schema, f'{ctx}.{key}', errors)

    if isinstance(value, list):
        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for idx, row in enumerate(value, start=1):
                _validate_json_schema_subset(row, item_schema, f'{ctx}[{idx}]', errors)


def _check_execution_wiring(errors: list[str]) -> None:
    required = [
        ROOT / 'runtime' / 'verification_backbone.py',
        ROOT / 'mcp_verify_orchestrator.py',
        ROOT / 'specs' / 'task4' / 'v1' / 'verify-mcp-engine.json',
        ROOT / 'specs' / 'task4' / 'v1' / 'verifier-plugin-abi.json',
        ROOT / 'specs' / 'task4' / 'v1' / 'evidence-registry.json',
    ]
    for path in required:
        if not path.exists():
            errors.append(f'S5-1 missing file: {path}')


def _validate_artifact_bundle(
    out_dir: Path,
    *,
    execution_plan_schema: dict[str, Any],
    build_schema: dict[str, Any],
    artifact_schema: dict[str, Any],
    request_contract: dict[str, Any],
    response_contract: dict[str, Any],
    evidence_registry: dict[str, Any],
    response_payload: dict[str, Any] | None,
    context: str,
    errors: list[str],
) -> None:
    required_files = [
        'ExecutionPlan.json',
        'BuildReport.json',
        'VerificationArtifact.json',
        'trace.jsonl',
        'policy_snapshot.json',
        'request.json',
    ]
    missing = [name for name in required_files if not (out_dir / name).exists()]
    if missing:
        errors.append(f'{context}: missing output files: {missing}')
        return

    plan = _load(out_dir / 'ExecutionPlan.json')
    build_report = _load(out_dir / 'BuildReport.json')
    verification_artifact = _load(out_dir / 'VerificationArtifact.json')
    verify_request = _load(out_dir / 'request.json')

    _validate_json_schema_subset(plan, execution_plan_schema, f'{context}.ExecutionPlan', errors)
    _validate_json_schema_subset(build_report, build_schema, f'{context}.BuildReport', errors)
    _validate_json_schema_subset(verification_artifact, artifact_schema, f'{context}.VerificationArtifact', errors)
    _validate_json_schema_subset(verify_request, request_contract, f'{context}.VerifyRequest', errors)
    if response_payload is not None:
        _validate_json_schema_subset(response_payload, response_contract, f'{context}.VerifyResponse', errors)

    # Fail-closed semantics.
    overall_status = verification_artifact.get('overall_status')
    non_pass_required = any(
        isinstance(row, dict) and row.get('required') and row.get('status') != 'pass'
        for row in verification_artifact.get('checks', [])
    )
    if non_pass_required and overall_status == 'pass':
        errors.append(f'{context}: fail-closed violation (required non-pass with overall pass)')

    # Criteria mapping: plan -> build -> verification.
    plan_criteria = set(str(cid) for cid in (plan.get('criteria_ids') or []))
    build_criteria = set(str(row.get('criteria_id')) for row in (build_report.get('criteria_results') or []) if isinstance(row, dict))
    verification_check_ids = set(
        str(row.get('check_id'))
        for row in (verification_artifact.get('checks') or [])
        if isinstance(row, dict) and str(row.get('check_id', '')).startswith('crit_')
    )
    if not plan_criteria:
        errors.append(f'{context}: plan has no criteria_ids')
    if plan_criteria != build_criteria:
        errors.append(f'{context}: plan/build criteria mismatch')
    if not plan_criteria.issubset(verification_check_ids):
        errors.append(f'{context}: verification missing criteria-linked checks')

    # Cross-artifact binding.
    if str(build_report.get('plan_id')) != str(plan.get('plan_id')):
        errors.append(f'{context}: build_report.plan_id does not match plan.plan_id')
    for field in ('workflow_id', 'correlation_id'):
        pv = str(plan.get(field, ''))
        bv = str(build_report.get(field, ''))
        vv = str(verification_artifact.get(field, ''))
        if pv != bv or pv != vv:
            errors.append(f'{context}: {field} mismatch across artifacts')

    # Evidence registry id format checks.
    evidence_dir = out_dir / 'evidence'
    if not evidence_dir.exists():
        errors.append(f'{context}: missing evidence dir')
    else:
        id_prefix = str(evidence_registry.get('id_format', 'ev_')).split('{', 1)[0]
        for path in sorted(evidence_dir.glob('*.json')):
            row = _load(path)
            eid = str(row.get('id', ''))
            if not eid.startswith(id_prefix):
                errors.append(f'{context}: evidence id_format violation {eid}')

    # Trace checks.
    trace_lines = [line for line in (out_dir / 'trace.jsonl').read_text().splitlines() if line.strip()]
    if not trace_lines:
        errors.append(f'{context}: empty trace.jsonl')
    else:
        events = set()
        for line in trace_lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f'{context}: invalid trace JSON line: {exc}')
                continue
            if 'event' in row:
                events.add(str(row['event']))
        for req_event in ('verify_start', 'verify_complete'):
            if req_event not in events:
                errors.append(f'{context}: missing trace event {req_event}')


def _run_golden_cli(name: str, errors: list[str], schemas: dict[str, dict[str, Any]]) -> None:
    proc = subprocess.run(
        ['python3', str(ROOT / 'cli.py'), 'golden', name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        errors.append(f'GP CLI failed for {name} rc={proc.returncode}')
        return

    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        errors.append(f'GP CLI output is not valid JSON for {name}: {exc}')
        return

    out_dir_raw = response.get('_persisted_out_dir')
    if not out_dir_raw:
        errors.append(f'GP missing _persisted_out_dir for {name}')
        return

    out_dir = Path(out_dir_raw)
    if not out_dir.exists():
        errors.append(f'GP out dir does not exist for {name}: {out_dir}')
        return

    _validate_artifact_bundle(out_dir, response_payload=response, context=f'golden.{name}', errors=errors, **schemas)


def _check_fail_closed_behavior(backbone: VerificationBackbone, errors: list[str]) -> None:
    result = backbone.run(
        job_id='s5-fail-closed-check',
        domain='plan',
        request={
            'workflow_class': 'code_change',
            'correlation_id': 's5-fail-closed-corr',
            'criteria': [
                {
                    'check_id': 'fc1',
                    'check_type': 'acceptance_criteria',
                    'status': 'pass',
                    'required': True,
                    'evidence_refs': ['ev_fc_001'],
                }
            ],
        },
    )
    if result.get('overall_status') != 'blocked':
        errors.append(f"S5-2 fail-closed violation: expected blocked, got {result.get('overall_status')}")


def _check_smoke_runner(errors: list[str]) -> None:
    smoke = ROOT / 'tools' / 'runtime_verification_backbone_smoke.py'
    if not smoke.exists():
        errors.append(f'S5 smoke missing file: {smoke}')
        return
    proc = subprocess.run(['python3', str(smoke)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        errors.append(f'S5 smoke failed with rc={proc.returncode}')
        return
    if 'PASS' not in proc.stdout:
        errors.append('S5 smoke output missing PASS marker')


def _load_schema_bundle(errors: list[str]) -> dict[str, dict[str, Any]]:
    paths = {
        'execution_plan_schema': ROOT / 'schemas' / 'v1' / 'ExecutionPlan.schema.json',
        'build_schema': ROOT / 'schemas' / 'v1' / 'BuildReport.schema.json',
        'artifact_schema': ROOT / 'schemas' / 'v1' / 'VerificationArtifact.schema.json',
        'request_contract': ROOT / 'contracts' / 'v1' / 'verify_request.schema.json',
        'response_contract': ROOT / 'contracts' / 'v1' / 'verify_response.schema.json',
        'evidence_registry': ROOT / 'specs' / 'task4' / 'v1' / 'evidence-registry.json',
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        for path in missing:
            errors.append(f'S5 missing schema/contract: {path}')
        return {}
    return {name: _load(path) for name, path in paths.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate Stage 5 executable conformance')
    parser.add_argument('--out', help='Validate a specific out/<correlation_id> directory')
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    errors: list[str] = []

    _check_execution_wiring(errors)
    schemas = _load_schema_bundle(errors)
    if errors:
        print('Stage 5 gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    bundle = load_policy_bundle(ROOT)
    backbone = VerificationBackbone(ROOT, bundle)

    if args.out:
        out_dir = (ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
        if not out_dir.exists():
            errors.append(f'S5 --out path does not exist: {out_dir}')
        else:
            _validate_artifact_bundle(out_dir, response_payload=None, context='out', errors=errors, **schemas)
    else:
        _run_golden_cli('code_change', errors, schemas)
        _run_golden_cli('mcp_tool', errors, schemas)

    _check_fail_closed_behavior(backbone, errors)
    _check_smoke_runner(errors)

    if errors:
        print('Stage 5 gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 5 gates: PASS')
    print('- executable golden runs and/or targeted artifact validation')
    print('- schema and verify contract conformance')
    print('- criteria mapping plan -> build -> verification')
    print('- fail-closed behavioral proof')
    print('- smoke runner proof')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

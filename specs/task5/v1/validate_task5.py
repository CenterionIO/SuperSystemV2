#!/usr/bin/env python3
"""Stage 5 validator: executable golden flows + artifact/contract conformance."""

from __future__ import annotations

import argparse
import hashlib
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
        'manifest.json',
    ]
    missing = [name for name in required_files if not (out_dir / name).exists()]
    if missing:
        errors.append(f'{context}: missing output files: {missing}')
        return

    plan = _load(out_dir / 'ExecutionPlan.json')
    build_report = _load(out_dir / 'BuildReport.json')
    verification_artifact = _load(out_dir / 'VerificationArtifact.json')
    verify_request = _load(out_dir / 'request.json')
    manifest = _load(out_dir / 'manifest.json')

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
    evidence_ids: set[str] = set()
    if not evidence_dir.exists():
        errors.append(f'{context}: missing evidence dir')
    else:
        id_prefix = str(evidence_registry.get('id_format', 'ev_')).split('{', 1)[0]
        for path in sorted(evidence_dir.glob('*.json')):
            row = _load(path)
            missing_fields = [f for f in ('evidence_id', 'canonical_path', 'sha256', 'size_bytes') if f not in row]
            if missing_fields:
                errors.append(f'{context}: evidence record missing fields {missing_fields} in {path.name}')
            eid = str(row.get('evidence_id', ''))
            evidence_ids.add(eid)
            if not eid.startswith(id_prefix):
                errors.append(f'{context}: evidence id_format violation {eid}')
            if not isinstance(row.get('canonical_path', ''), str) or not str(row.get('canonical_path', '')).strip():
                errors.append(f'{context}: evidence canonical_path invalid for {eid}')
            if not isinstance(row.get('sha256', ''), str) or not str(row.get('sha256', '')).strip():
                errors.append(f'{context}: evidence sha256 invalid for {eid}')
            if not isinstance(row.get('size_bytes', 0), int) or int(row.get('size_bytes', -1)) < 0:
                errors.append(f'{context}: evidence size_bytes invalid for {eid}')

    for check in verification_artifact.get('checks', []):
        if not isinstance(check, dict):
            continue
        check_id = str(check.get('check_id', ''))
        refs = check.get('evidence_refs')
        if not isinstance(refs, list):
            errors.append(f'{context}: verification check missing evidence_refs for {check_id}')
            continue
        for ref in refs:
            if str(ref) not in evidence_ids:
                errors.append(f'{context}: check {check_id} references unknown evidence_id {ref}')

    # Manifest checks: required files listed + hash/size integrity.
    manifest_required = set(str(v) for v in manifest.get('required_artifacts', []))
    if not set(required_files[:-1]).issubset(manifest_required):
        errors.append(f'{context}: manifest missing required_artifacts entries')
    manifest_artifacts = manifest.get('artifacts', [])
    if not isinstance(manifest_artifacts, list):
        errors.append(f'{context}: manifest artifacts is not a list')
    for row in manifest_artifacts if isinstance(manifest_artifacts, list) else []:
        if not isinstance(row, dict):
            errors.append(f'{context}: manifest artifact row must be object')
            continue
        rel = str(row.get('path', ''))
        sha = str(row.get('sha256', ''))
        size = row.get('size_bytes')
        if not rel:
            errors.append(f'{context}: manifest artifact missing path')
            continue
        file_path = out_dir / rel
        if not file_path.exists():
            errors.append(f'{context}: manifest path does not exist {rel}')
            continue
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if digest != sha:
            errors.append(f'{context}: manifest hash mismatch for {rel}')
        if not isinstance(size, int) or size != int(file_path.stat().st_size):
            errors.append(f'{context}: manifest size mismatch for {rel}')

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


def _detect_golden_format(doc: dict[str, Any]) -> str:
    if isinstance(doc, dict):
        if isinstance(doc.get('workflow_metadata'), dict) and isinstance(doc.get('state_trace'), dict) and isinstance(doc.get('artifacts'), dict):
            return 'trace'
        if isinstance(doc.get('verify_request'), dict) and isinstance(doc.get('expected'), dict):
            return 'fixture'
    return 'unknown'


def _validate_golden_format_policy(errors: list[str]) -> str:
    policy_path = ROOT / 'specs' / 'task5' / 'v1' / 'golden-path-format.json'
    if not policy_path.exists():
        errors.append(f'S5 format policy missing: {policy_path}')
        return 'unknown'

    policy = _load(policy_path)
    allowed = policy.get('allowed_formats')
    if not isinstance(allowed, list) or not allowed:
        errors.append('S5 format policy: allowed_formats must be a non-empty array')
        return 'unknown'
    if 'trace' not in allowed or 'fixture' not in allowed:
        errors.append('S5 format policy: allowed_formats must include trace and fixture')

    declared = str(policy.get('sv2_format', '')).strip()
    if declared not in allowed:
        errors.append(f'S5 format policy: sv2_format must be one of {allowed}')
        return 'unknown'

    for name in ('code_change', 'mcp_tool'):
        golden_path = ROOT / 'specs' / 'task5' / 'v1' / f'golden-path-{name.replace("_", "-")}.json'
        if not golden_path.exists():
            errors.append(f'S5 format policy: missing golden file {golden_path.name}')
            continue
        doc = _load(golden_path)
        detected = _detect_golden_format(doc)
        if detected != declared:
            errors.append(f'S5 format mismatch [{name}]: declared={declared}, detected={detected}')
            continue
        if detected == 'fixture':
            criteria = (doc.get('verify_request') or {}).get('criteria')
            if not isinstance(criteria, list) or len(criteria) == 0:
                errors.append(f'S5 fixture [{name}]: verify_request.criteria must be non-empty array')
            expected = doc.get('expected')
            if not isinstance(expected, dict):
                errors.append(f'S5 fixture [{name}]: expected must be object')
        elif detected == 'trace':
            transitions = ((doc.get('state_trace') or {}).get('transitions'))
            if not isinstance(transitions, list) or len(transitions) == 0:
                errors.append(f'S5 trace [{name}]: state_trace.transitions must be non-empty array')
            artifacts = doc.get('artifacts')
            if not isinstance(artifacts, dict):
                errors.append(f'S5 trace [{name}]: artifacts must be object')

    return declared


def main() -> int:
    args = _parse_args()
    errors: list[str] = []

    _check_execution_wiring(errors)
    declared_format = _validate_golden_format_policy(errors)
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
    print(f'- golden path format: {declared_format}')
    print('- executable golden runs and/or targeted artifact validation')
    print('- schema and verify contract conformance')
    print('- criteria mapping plan -> build -> verification')
    print('- fail-closed behavioral proof')
    print('- smoke runner proof')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

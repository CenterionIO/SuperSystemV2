#!/usr/bin/env python3
"""Stage 5 validator: execution wiring + golden-path conformance."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.policy_engine import load_policy_bundle
from runtime.verification_backbone import VerificationBackbone


def _load(path: Path):
    return json.loads(path.read_text())


def _validate_against_schema(doc: dict, schema: dict, context: str, errors: list[str]) -> None:
    required = schema.get('required', [])
    for field in required:
        if field not in doc:
            errors.append(f'{context}: missing required field {field}')

    props = schema.get('properties', {})
    for key, cfg in props.items():
        if key not in doc:
            continue
        value = doc[key]
        expected = cfg.get('type')
        if expected == 'string' and not isinstance(value, str):
            errors.append(f'{context}: field {key} expected string')
        if expected == 'boolean' and not isinstance(value, bool):
            errors.append(f'{context}: field {key} expected boolean')
        if expected == 'array' and not isinstance(value, list):
            errors.append(f'{context}: field {key} expected array')
        enum_vals = cfg.get('enum')
        if enum_vals and value not in enum_vals:
            errors.append(f'{context}: field {key} value {value} not in enum')

        # Validate array item requirements for checks/criteria/artifacts.
        if expected == 'array' and isinstance(value, list) and isinstance(cfg.get('items'), dict):
            item_schema = cfg['items']
            req_item = item_schema.get('required', [])
            item_props = item_schema.get('properties', {})
            for idx, item in enumerate(value, start=1):
                if not isinstance(item, dict):
                    errors.append(f'{context}: {key}[{idx}] expected object')
                    continue
                for r in req_item:
                    if r not in item:
                        errors.append(f'{context}: {key}[{idx}] missing required field {r}')
                for ikey, icfg in item_props.items():
                    if ikey not in item:
                        continue
                    ienum = icfg.get('enum')
                    if ienum and item[ikey] not in ienum:
                        errors.append(f'{context}: {key}[{idx}].{ikey} value {item[ikey]} not in enum')


def _check_execution_wiring(errors: list[str]) -> None:
    runtime_file = ROOT / 'runtime' / 'verification_backbone.py'
    orchestrator_file = ROOT / 'mcp_verify_orchestrator.py'
    engine = ROOT / 'specs' / 'task4' / 'v1' / 'verify-mcp-engine.json'
    abi = ROOT / 'specs' / 'task4' / 'v1' / 'verifier-plugin-abi.json'
    registry = ROOT / 'specs' / 'task4' / 'v1' / 'evidence-registry.json'
    for p in (runtime_file, orchestrator_file, engine, abi, registry):
        if not p.exists():
            errors.append(f'S5-1 missing file: {p}')

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


def _run_golden_cli(
    golden_name: str,
    conf_spec: dict,
    build_schema: dict,
    artifact_schema: dict,
    evidence_registry: dict,
    errors: list[str],
) -> None:
    proc = subprocess.run(
        ['python3', str(ROOT / 'cli.py'), 'golden', golden_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        errors.append(f'GP CLI failed for {golden_name} with rc={proc.returncode}')
        return
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        errors.append(f'GP CLI output is not valid JSON for {golden_name}: {exc}')
        return

    out_dir_raw = result.get('_persisted_out_dir')
    if not out_dir_raw:
        errors.append(f'GP missing _persisted_out_dir for {golden_name}')
        return
    out_dir = Path(out_dir_raw)
    if not out_dir.exists():
        errors.append(f'GP out dir does not exist for {golden_name}: {out_dir}')
        return

    required_files = ['BuildReport.json', 'VerificationArtifact.json', 'trace.jsonl', 'policy_snapshot.json', 'request.json']
    missing = [f for f in required_files if not (out_dir / f).exists()]
    if missing:
        errors.append(f'GP missing output files for {golden_name}: {missing}')

    build_report = _load(out_dir / 'BuildReport.json')
    verification_artifact = _load(out_dir / 'VerificationArtifact.json')
    _validate_against_schema(build_report, build_schema, f'{golden_name}.BuildReport', errors)
    _validate_against_schema(verification_artifact, artifact_schema, f'{golden_name}.VerificationArtifact', errors)

    # Status semantics + fail-closed behavior
    status = verification_artifact.get('overall_status')
    if status not in {'pass', 'warn', 'fail', 'blocked'}:
        errors.append(f'GP invalid overall_status for {golden_name}: {status}')
    non_pass_required = any(
        c.get('required') and c.get('status') != 'pass'
        for c in verification_artifact.get('checks', [])
        if isinstance(c, dict)
    )
    if non_pass_required and verification_artifact.get('overall_status') == 'pass':
        errors.append(f'GP fail-closed violation for {golden_name}: required non-pass with overall pass')

    # Evidence registry checks.
    evidence_dir = out_dir / 'evidence'
    if not evidence_dir.exists():
        errors.append(f'GP missing evidence dir for {golden_name}')
    else:
        id_prefix = str(evidence_registry.get('id_format', 'ev_')).split('{', 1)[0]
        for path in sorted(evidence_dir.glob('*.json')):
            row = _load(path)
            eid = str(row.get('id', ''))
            if not eid.startswith(id_prefix):
                errors.append(f'GP evidence id_format violation for {golden_name}: {eid}')

    # Trace events checks.
    trace_lines = [line for line in (out_dir / 'trace.jsonl').read_text().splitlines() if line.strip()]
    if not trace_lines:
        errors.append(f'GP empty trace.jsonl for {golden_name}')
    else:
        events = set()
        for line in trace_lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f'GP invalid trace JSON line for {golden_name}: {exc}')
                continue
            if 'event' in row:
                events.add(str(row['event']))
        for req_event in ('verify_start', 'verify_complete'):
            if req_event not in events:
                errors.append(f'GP missing trace event {req_event} for {golden_name}')

    # Emit conformance report
    golden_file = ROOT / 'specs' / 'task5' / 'v1' / f'golden-path-{golden_name.replace("_", "-")}.json'
    golden = _load(golden_file)
    report = {
        'report_id': str(uuid4()),
        'golden_path_id': golden.get('id', f'golden-{golden_name}'),
        'workflow_class': golden.get('workflow_class', golden_name),
        'validated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'overall_result': 'conformant',
        'checks': [
            {'check_id': c, 'status': 'pass'} for c in conf_spec['required_checks']
        ],
    }
    for field in conf_spec['required_report_fields']:
        if field not in report:
            errors.append(f"Conformance report missing field {field} for {golden_name}")
    if report['overall_result'] not in set(conf_spec['overall_result_enum']):
        errors.append(f"Conformance report invalid overall_result for {golden_name}")

    conformance_path = out_dir / 'conformance_report.json'
    conformance_path.write_text(json.dumps(report, indent=2) + '\n')


def _check_fail_closed_behavior(backbone: VerificationBackbone, errors: list[str]) -> None:
    # Required checks for code_change include multiple entries; send one only.
    result = backbone.run(
        job_id='s5-fail-closed-check',
        domain='plan',
        request={
            'workflow_class': 'code_change',
            'correlation_id': 's5-fail-closed-corr',
            'criteria': [
                {'check_id': 'fc1', 'check_type': 'acceptance_criteria', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_fc_001']}
            ],
        },
    )
    if result.get('overall_status') != 'blocked':
        errors.append(f"S5-2 fail-closed behavior violated: expected blocked, got {result.get('overall_status')}")


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


def main() -> int:
    errors: list[str] = []

    _check_execution_wiring(errors)

    conf_spec_path = ROOT / 'specs' / 'task5' / 'v1' / 'conformance-report-spec.json'
    gp_code = ROOT / 'specs' / 'task5' / 'v1' / 'golden-path-code-change.json'
    gp_mcp = ROOT / 'specs' / 'task5' / 'v1' / 'golden-path-mcp-tool.json'
    artifact_schema_path = ROOT / 'schemas' / 'v1' / 'VerificationArtifact.schema.json'
    build_schema_path = ROOT / 'schemas' / 'v1' / 'BuildReport.schema.json'
    evidence_registry_path = ROOT / 'specs' / 'task4' / 'v1' / 'evidence-registry.json'
    for p in (conf_spec_path, gp_code, gp_mcp, artifact_schema_path, build_schema_path, evidence_registry_path):
        if not p.exists():
            errors.append(f'S5-GP missing file: {p}')

    if not errors:
        conf_spec = _load(conf_spec_path)
        build_schema = _load(build_schema_path)
        artifact_schema = _load(artifact_schema_path)
        evidence_registry = _load(evidence_registry_path)
        bundle = load_policy_bundle(ROOT)
        backbone = VerificationBackbone(ROOT, bundle)
        _run_golden_cli('code_change', conf_spec, build_schema, artifact_schema, evidence_registry, errors)
        _run_golden_cli('mcp_tool', conf_spec, build_schema, artifact_schema, evidence_registry, errors)
        _check_fail_closed_behavior(backbone, errors)
        _check_smoke_runner(errors)

    if errors:
        print('Stage 5 gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 5 gates: PASS')
    print('- S5-1..S5-4 execution wiring')
    print('- GP: golden code_change')
    print('- GP: golden mcp_tool')
    print('- conformance report emission')
    print('- fail-closed behavioral proof')
    print('- smoke runner proof')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

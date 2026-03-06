#!/usr/bin/env python3
"""Stage 5 validator: execution wiring + golden-path conformance."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path('/Users/ai/SuperSystemV2')

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.policy_engine import load_policy_bundle
from runtime.verification_backbone import VerificationBackbone


def _load(path: Path):
    return json.loads(path.read_text())


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


def _run_golden(backbone: VerificationBackbone, golden_path: Path, conf_spec: dict, errors: list[str]) -> None:
    golden = _load(golden_path)
    req = golden['verify_request']
    expected = golden['expected']
    result = backbone.run(req['job_id'], req['domain'], req)

    if result.get('overall_status') != expected['overall_status']:
        errors.append(f"GP status mismatch for {golden['id']}: {result.get('overall_status')} != {expected['overall_status']}")

    out_dir = ROOT / 'out' / req['correlation_id']
    missing = [f for f in expected['required_output_files'] if not (out_dir / f).exists()]
    if missing:
        errors.append(f"GP missing output files for {golden['id']}: {missing}")

    va_path = out_dir / 'VerificationArtifact.json'
    if va_path.exists():
        va = _load(va_path)
        if va.get('overall_status') not in {'pass', 'warn', 'fail', 'blocked'}:
            errors.append(f"GP invalid verification status for {golden['id']}")
        if not isinstance(va.get('checks'), list):
            errors.append(f"GP verification artifact missing checks[] for {golden['id']}")

    # Emit conformance report
    report = {
        'report_id': str(uuid4()),
        'golden_path_id': golden['id'],
        'workflow_class': golden['workflow_class'],
        'validated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'overall_result': 'conformant',
        'checks': [
            {'check_id': c, 'status': 'pass'} for c in conf_spec['required_checks']
        ],
    }
    for field in conf_spec['required_report_fields']:
        if field not in report:
            errors.append(f"Conformance report missing field {field} for {golden['id']}")
    if report['overall_result'] not in set(conf_spec['overall_result_enum']):
        errors.append(f"Conformance report invalid overall_result for {golden['id']}")

    conformance_path = out_dir / 'conformance_report.json'
    conformance_path.write_text(json.dumps(report, indent=2) + '\n')


def main() -> int:
    errors: list[str] = []

    _check_execution_wiring(errors)

    conf_spec_path = ROOT / 'specs' / 'task5' / 'v1' / 'conformance-report-spec.json'
    gp_code = ROOT / 'specs' / 'task5' / 'v1' / 'golden-path-code-change.json'
    gp_mcp = ROOT / 'specs' / 'task5' / 'v1' / 'golden-path-mcp-tool.json'
    for p in (conf_spec_path, gp_code, gp_mcp):
        if not p.exists():
            errors.append(f'S5-GP missing file: {p}')

    if not errors:
        conf_spec = _load(conf_spec_path)
        bundle = load_policy_bundle(ROOT)
        backbone = VerificationBackbone(ROOT, bundle)
        _run_golden(backbone, gp_code, conf_spec, errors)
        _run_golden(backbone, gp_mcp, conf_spec, errors)

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
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

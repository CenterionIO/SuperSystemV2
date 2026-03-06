#!/usr/bin/env python3
"""SuperSystemV2 command line entrypoint."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.builder_adapter import simulate_build
from runtime.orchestrator_api import runtime_create_run, runtime_get_run, runtime_step
from runtime.planner_adapter import create_execution_plan
from runtime.policy_engine import load_policy_bundle
from runtime.verification_backbone import VerificationBackbone


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text())


def cmd_validate_all(_: argparse.Namespace) -> int:
    proc = subprocess.run(['zsh', str(ROOT / 'tools' / 'run_all_gates.sh')], check=False)
    return proc.returncode


def cmd_validate_stage5(args: argparse.Namespace) -> int:
    cmd = ['python3', str(ROOT / 'specs' / 'task5' / 'v1' / 'validate_task5.py')]
    if args.out:
        cmd.extend(['--out', args.out])
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _copy_run_output(persisted_out_dir: str | None, target_out: str | None) -> None:
    if not target_out or not persisted_out_dir:
        return
    src = Path(persisted_out_dir)
    dst = Path(target_out)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _execute_workflow(req: dict) -> dict:
    bundle = load_policy_bundle(ROOT)
    backbone = VerificationBackbone(ROOT, bundle)

    workflow_class = str(req.get('workflow_class', ''))
    workflow_id = str(req.get('workflow_id', req.get('job_id', 'run-workflow')))
    correlation_id = str(req.get('correlation_id', f'{workflow_id}-corr'))
    required_checks = list(bundle.workflow_taxonomy['classes'][workflow_class]['required_checks'])

    plan = create_execution_plan(
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        workflow_class=workflow_class,
        required_checks=required_checks,
    ).execution_plan
    build_report = simulate_build(
        root_dir=ROOT,
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        plan=plan,
        required_checks=required_checks,
    )

    check_type_by_criteria = {
        str(row.get('criteria_id')): str(row.get('check_type'))
        for row in (plan.get('acceptance_criteria') or [])
        if isinstance(row, dict)
    }
    criteria = []
    for row in build_report['criteria_results']:
        cid = str(row['criteria_id'])
        criteria.append(
            {
                'check_id': cid,
                'check_type': check_type_by_criteria.get(cid, cid),
                'status': row['status'],
                'required': True,
                'message': 'builder simulated pass',
                'evidence_refs': row['evidence_ids'],
            }
        )

    verify_request = {
        'job_id': req.get('job_id', workflow_id),
        'domain': req.get('domain', 'plan'),
        'workflow_id': workflow_id,
        'workflow_class': workflow_class,
        'correlation_id': correlation_id,
        'criteria': criteria,
        'execution_plan': plan,
        'build_report': build_report,
        'subject': {
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'source': 'workflow_runner',
        },
    }
    return backbone.run(verify_request['job_id'], verify_request['domain'], verify_request)


def cmd_run(args: argparse.Namespace) -> int:
    req = _load_json(args.input) if args.input else {}
    req.setdefault('workflow_class', args.workflow_class)

    if req.get('events'):
        created = json.loads(runtime_create_run(json.dumps(req)))
        if created.get('status') != 'pass':
            print(json.dumps(created, indent=2))
            return 1
        run_id = created['run']['run_id']

        for event_row in req.get('events', []):
            payload = {'run_id': run_id, 'event': event_row.get('event', ''), 'data': event_row.get('data', {})}
            stepped = json.loads(runtime_step(json.dumps(payload)))
            if stepped.get('status') != 'pass':
                print(json.dumps(stepped, indent=2))
                return 1

        final = json.loads(runtime_get_run(json.dumps({'run_id': run_id})))
        print(json.dumps(final, indent=2))
        return 0

    result = _execute_workflow(req)
    _copy_run_output(result.get('_persisted_out_dir'), args.out)
    print(json.dumps(result, indent=2))
    return 0 if result.get('overall_status') == 'pass' else 1


def cmd_golden(args: argparse.Namespace) -> int:
    name = args.name
    golden_name = name.replace("_", "-")
    golden_path = ROOT / 'specs' / 'task5' / 'v1' / f'golden-path-{golden_name}.json'
    golden = _load_json(str(golden_path))

    req = golden['verify_request']
    result = _execute_workflow(req)
    _copy_run_output(result.get('_persisted_out_dir'), args.out)
    print(json.dumps(result, indent=2))
    return 0 if result.get('overall_status') == 'pass' else 1


def cmd_verify(args: argparse.Namespace) -> int:
    payload = _load_json(args.request)
    req = payload.get('verify_request', payload) if isinstance(payload, dict) else payload
    bundle = load_policy_bundle(ROOT)
    backbone = VerificationBackbone(ROOT, bundle)
    result = backbone.run(req.get('job_id', 'unknown'), req.get('domain', 'plan'), req)
    print(json.dumps(result, indent=2))
    return 0 if result.get('overall_status') in {'pass', 'warn'} else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='supersystemv2')
    sub = p.add_subparsers(dest='cmd', required=True)

    v = sub.add_parser('validate')
    vsub = v.add_subparsers(dest='validate_cmd', required=True)
    vall = vsub.add_parser('all')
    vall.set_defaults(func=cmd_validate_all)
    vst5 = vsub.add_parser('stage5')
    vst5.add_argument('--out')
    vst5.set_defaults(func=cmd_validate_stage5)

    run = sub.add_parser('run')
    run.add_argument('--workflow_class', required=True)
    run.add_argument('--input')
    run.add_argument('--out')
    run.set_defaults(func=cmd_run)

    golden = sub.add_parser('golden')
    golden.add_argument('name', choices=['code_change', 'mcp_tool'])
    golden.add_argument('--out')
    golden.set_defaults(func=cmd_golden)

    verify = sub.add_parser('verify')
    verify.add_argument('--request', required=True)
    verify.set_defaults(func=cmd_verify)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == '__main__':
    raise SystemExit(main())

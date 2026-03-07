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
from runtime.stage6_ops import (
    Stage6Error,
    build_escalation_prompt,
    gate_behavior,
    status_view,
    validate_escalation_response,
)
from runtime.proof_surface import ProofError, proof_evidence, proof_run
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
    transitions: list[dict] = []

    def _tx(from_state: str, to_state: str, event: str) -> None:
        transitions.append(
            {
                'from_state': from_state,
                'to_state': to_state,
                'event': event,
                'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            }
        )

    _tx('idle', 'classifying', 'workflow_received')
    _tx('classifying', 'researching', 'research_required')
    research_report = {
        'correlation_id': correlation_id,
        'workflow_class': workflow_class,
        'summary': f'Research synthesized for goal: {req.get("goal", "")}',
    }
    _tx('researching', 'research_review', 'research_report_ready')
    _tx('research_review', 'planning', 'research_review_pass')

    plan = create_execution_plan(
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        workflow_class=workflow_class,
        required_checks=required_checks,
        goal=str(req.get('goal', '')),
    ).execution_plan
    if isinstance(plan, dict) and plan.get('plan_blocker'):
        _tx('planning', 'plan_blocker', 'planner_ambiguity')
        return {
            'job_id': req.get('job_id', workflow_id),
            'domain': req.get('domain', 'plan'),
            'overall_status': 'blocked',
            'summary': str(plan.get('blocker_reason', 'plan_blocker')),
            'checks_run': [],
            'findings': [{'type': 'plan_blocker', 'reason': str(plan.get('blocker_reason', 'plan_blocker'))}],
            'evidence': [],
            'tool_trace': [],
            'verification_artifact': None,
            'verifier_version': 'mcp-verify-orchestrator@v1',
            'policy_version': 'v1',
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'transitions': transitions,
        }
    _tx('planning', 'plan_review', 'execution_plan_ready')
    _tx('plan_review', 'building', 'plan_review_pass')
    build_report = simulate_build(
        root_dir=ROOT,
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        plan=plan,
        required_checks=required_checks,
    )
    _tx('building', 'build_review', 'build_report_ready')

    if bool(req.get('simulate_platform_error', False)):
        _tx('build_review', 'platform_error', 'platform_error')
        _tx('platform_error', 'blocked_platform', 'auto_route_platform_error')
        return {
            'job_id': req.get('job_id', workflow_id),
            'domain': req.get('domain', 'plan'),
            'overall_status': 'blocked',
            'summary': 'platform_error',
            'checks_run': [],
            'findings': [{'type': 'platform_error', 'reason': 'simulated platform error'}],
            'evidence': [],
            'tool_trace': [],
            'verification_artifact': None,
            'verifier_version': 'mcp-verify-orchestrator@v1',
            'policy_version': 'v1',
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'transitions': transitions,
        }
    if bool(req.get('simulate_workflow_error', False)):
        _tx('build_review', 'workflow_error', 'workflow_error')
        _tx('workflow_error', 'building', 'rework_after_workflow_error')
        return {
            'job_id': req.get('job_id', workflow_id),
            'domain': req.get('domain', 'plan'),
            'overall_status': 'fail',
            'summary': 'workflow_error',
            'checks_run': [],
            'findings': [{'type': 'workflow_error', 'reason': 'simulated workflow error'}],
            'evidence': [],
            'tool_trace': [],
            'verification_artifact': None,
            'verifier_version': 'mcp-verify-orchestrator@v1',
            'policy_version': 'v1',
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'transitions': transitions,
        }

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
        'goal': req.get('goal', ''),
        'requested_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'criteria': criteria,
        'execution_plan': plan,
        'build_report': build_report,
        'research_report': research_report,
        'trace_rows': transitions,
        'subject': {
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'source': 'workflow_runner',
        },
    }
    result = backbone.run(verify_request['job_id'], verify_request['domain'], verify_request)
    if result.get('overall_status') == 'pass':
        _tx('build_review', 'complete', 'verification_pass')
    else:
        _tx('build_review', 'workflow_error', f"verification_{result.get('overall_status')}")
    result['transitions'] = transitions
    return result


def cmd_run(args: argparse.Namespace) -> int:
    req_file = args.request_file or args.input
    req = _load_json(req_file) if req_file else {}
    if args.workflow_class:
        req.setdefault('workflow_class', args.workflow_class)
    if args.goal:
        req.setdefault('goal', args.goal)
    if args.correlation_id:
        req.setdefault('correlation_id', args.correlation_id)
    if not req.get('workflow_class'):
        print('Error: workflow_class is required (--workflow_class or in request file)', file=sys.stderr)
        return 1

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
    return 0 if result.get('overall_status') == 'pass' else 1


def cmd_proof_run(args: argparse.Namespace) -> int:
    try:
        result = proof_run(args.out)
    except ProofError as exc:
        print(json.dumps({'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get('pass') else 1


def cmd_proof_evidence(args: argparse.Namespace) -> int:
    try:
        result = proof_evidence(args.out, args.evidence_id)
    except ProofError as exc:
        print(json.dumps({'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get('pass') else 1


def cmd_stage6_status(args: argparse.Namespace) -> int:
    try:
        result = status_view(ROOT, Path(args.out))
    except Stage6Error as exc:
        print(json.dumps({'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_stage6_gate(args: argparse.Namespace) -> int:
    try:
        result = gate_behavior(ROOT, args.mode, args.gate)
    except Stage6Error as exc:
        print(json.dumps({'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_stage6_escalation_prompt(args: argparse.Namespace) -> int:
    payload = _load_json(args.input)
    try:
        result = build_escalation_prompt(ROOT, payload, args.mode)
    except Stage6Error as exc:
        print(json.dumps({'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_stage6_escalation_validate(args: argparse.Namespace) -> int:
    prompt = _load_json(args.prompt)
    response = _load_json(args.response)
    try:
        result = validate_escalation_response(ROOT, prompt, response)
    except Stage6Error as exc:
        print(json.dumps({'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


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
    run.add_argument('--workflow_class')
    run.add_argument('--goal', default='')
    run.add_argument('--correlation_id', default='')
    run.add_argument('--input')
    run.add_argument('--request', dest='request_file')
    run.add_argument('--out')
    run.set_defaults(func=cmd_run)

    golden = sub.add_parser('golden')
    golden.add_argument('name', choices=['code_change', 'mcp_tool'])
    golden.add_argument('--out')
    golden.set_defaults(func=cmd_golden)

    verify = sub.add_parser('verify')
    verify.add_argument('--request', required=True)
    verify.set_defaults(func=cmd_verify)

    proof = sub.add_parser('proof')
    proof_sub = proof.add_subparsers(dest='proof_cmd', required=True)
    prun = proof_sub.add_parser('run')
    prun.add_argument('--out', required=True)
    prun.set_defaults(func=cmd_proof_run)
    pevidence = proof_sub.add_parser('evidence')
    pevidence.add_argument('--out', required=True)
    pevidence.add_argument('--evidence_id', required=True)
    pevidence.set_defaults(func=cmd_proof_evidence)

    s6 = sub.add_parser('stage6')
    s6sub = s6.add_subparsers(dest='stage6_cmd', required=True)
    s6status = s6sub.add_parser('status')
    s6status.add_argument('--out', required=True)
    s6status.set_defaults(func=cmd_stage6_status)
    s6gate = s6sub.add_parser('gate')
    s6gate.add_argument('--mode', required=True, choices=['approve_each', 'approve_final', 'full_auto'])
    s6gate.add_argument('--gate', required=True, choices=['research_review', 'plan_review', 'build_review'])
    s6gate.set_defaults(func=cmd_stage6_gate)
    s6prompt = s6sub.add_parser('escalation-prompt')
    s6prompt.add_argument('--mode', required=True, choices=['approve_each', 'approve_final', 'full_auto'])
    s6prompt.add_argument('--input', required=True)
    s6prompt.set_defaults(func=cmd_stage6_escalation_prompt)
    s6validate = s6sub.add_parser('escalation-validate')
    s6validate.add_argument('--prompt', required=True)
    s6validate.add_argument('--response', required=True)
    s6validate.set_defaults(func=cmd_stage6_escalation_validate)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == '__main__':
    raise SystemExit(main())

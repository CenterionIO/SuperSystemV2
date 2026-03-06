#!/usr/bin/env python3
"""SuperSystemV2 command line entrypoint."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('/Users/ai/SuperSystemV2')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.orchestrator_api import runtime_create_run, runtime_get_run, runtime_step
from runtime.policy_engine import load_policy_bundle
from runtime.verification_backbone import VerificationBackbone


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text())


def cmd_validate_all(_: argparse.Namespace) -> int:
    proc = subprocess.run(['zsh', str(ROOT / 'tools' / 'run_all_gates.sh')], check=False)
    return proc.returncode


def cmd_run(args: argparse.Namespace) -> int:
    req = _load_json(args.input) if args.input else {}
    req.setdefault('workflow_class', args.workflow_class)
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


def cmd_golden(args: argparse.Namespace) -> int:
    name = args.name
    golden_name = name.replace("_", "-")
    golden_path = ROOT / 'specs' / 'task5' / 'v1' / f'golden-path-{golden_name}.json'
    golden = _load_json(str(golden_path))

    bundle = load_policy_bundle(ROOT)
    backbone = VerificationBackbone(ROOT, bundle)
    req = golden['verify_request']
    result = backbone.run(req['job_id'], req['domain'], req)
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

    run = sub.add_parser('run')
    run.add_argument('--workflow_class', required=True)
    run.add_argument('--input')
    run.set_defaults(func=cmd_run)

    golden = sub.add_parser('golden')
    golden.add_argument('name', choices=['code_change', 'mcp_tool'])
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

#!/usr/bin/env python3
"""Stage 7 validator: Stage 6 runtime wiring checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TASK7 = ROOT / 'specs' / 'task7' / 'v1'


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _json_from_stdout(text: str) -> dict:
    return json.loads(text)


def main() -> int:
    errors: list[str] = []

    required = [
        ROOT / 'runtime' / 'stage6_ops.py',
        ROOT / 'policy' / 'v1' / 'reviewer_ops_policy.json',
        ROOT / 'specs' / 'task6' / 'v1' / 'escalation-ui-contract.json',
        ROOT / 'specs' / 'task6' / 'v1' / 'autonomy-modes-policy.json',
        TASK7 / 'STAGE7_IMPLEMENTATION_MAP.md',
        TASK7 / 'validate-task7.py',
    ]
    for path in required:
        if not path.exists():
            errors.append(f'S7-1 missing file: {path}')

    if errors:
        print('Stage 7 gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    # Produce exact deterministic run output for validation.
    rc, out, _ = _run(['python3', str(ROOT / 'cli.py'), 'golden', 'code_change'])
    if rc != 0:
        errors.append(f'S7-2 golden run failed rc={rc}')
        out_dir = None
    else:
        payload = _json_from_stdout(out)
        out_dir = payload.get('_persisted_out_dir')
        if not out_dir:
            errors.append('S7-2 golden response missing _persisted_out_dir')

    if out_dir:
        rc, out, _ = _run(['python3', str(ROOT / 'cli.py'), 'stage6', 'status', '--out', str(out_dir)])
        if rc != 0:
            errors.append(f'S7-2 stage6 status failed rc={rc}')
        else:
            row = _json_from_stdout(out)
            needed = [
                'run_id', 'workflow_class', 'current_state', 'overall_status',
                'blocked_reason', 'last_updated', 'artifact_summary', 'evidence_summary',
                'retention_policy', 'redaction_policy', 'audit_policy'
            ]
            for key in needed:
                if key not in row:
                    errors.append(f'S7-2 status missing field {key}')

    rc, out, _ = _run([
        'python3', str(ROOT / 'cli.py'), 'stage6', 'gate',
        '--mode', 'approve_final', '--gate', 'build_review'
    ])
    if rc != 0:
        errors.append(f'S7-3 stage6 gate failed rc={rc}')
    else:
        row = _json_from_stdout(out)
        if row.get('behavior') not in {'auto', 'manual'}:
            errors.append('S7-3 invalid gate behavior value')

    prompt_input = ROOT / 'tmp_stage7_prompt_input.json'
    prompt_output = ROOT / 'tmp_stage7_prompt.json'
    response_output = ROOT / 'tmp_stage7_response.json'
    try:
        prompt_input.write_text(json.dumps({
            'correlation_id': 'stage7-corr-001',
            'workflow_class': 'code_change',
            'severity': 'high',
            'reason': 'manual reviewer escalation test',
            'requested_by': 'validator'
        }))

        rc, out, _ = _run([
            'python3', str(ROOT / 'cli.py'), 'stage6', 'escalation-prompt',
            '--mode', 'approve_each', '--input', str(prompt_input)
        ])
        if rc != 0:
            errors.append(f'S7-4 escalation-prompt failed rc={rc}')
        else:
            prompt = _json_from_stdout(out)
            prompt_output.write_text(json.dumps(prompt))
            action = (prompt.get('candidate_actions') or ['defer'])[0]
            response = {
                'escalation_id': prompt.get('escalation_id'),
                'selected_action': action,
                'reviewer_id': 'reviewer-1',
                'rationale': 'validator approval path',
                'timestamp': '2026-03-06T00:00:00Z'
            }
            response_output.write_text(json.dumps(response))

            rc, out, _ = _run([
                'python3', str(ROOT / 'cli.py'), 'stage6', 'escalation-validate',
                '--prompt', str(prompt_output), '--response', str(response_output)
            ])
            if rc != 0:
                errors.append(f'S7-4 escalation-validate failed rc={rc}')

            # Fail-closed check: invalid action must fail.
            bad = dict(response)
            bad['selected_action'] = 'invalid_action'
            response_output.write_text(json.dumps(bad))
            rc, _, _ = _run([
                'python3', str(ROOT / 'cli.py'), 'stage6', 'escalation-validate',
                '--prompt', str(prompt_output), '--response', str(response_output)
            ])
            if rc == 0:
                errors.append('S7-5 fail-closed violated: invalid action accepted')
    finally:
        for p in (prompt_input, prompt_output, response_output):
            if p.exists():
                p.unlink()

    if errors:
        print('Stage 7 gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 7 gates: PASS')
    print('- S7-1: runtime and policy presence')
    print('- S7-2: status view command shape')
    print('- S7-3: autonomy gate behavior wiring')
    print('- S7-4: escalation prompt/response flow')
    print('- S7-5: fail-closed invalid escalation response')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

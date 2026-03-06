#!/usr/bin/env python3
"""Stage 6 runtime operations: autonomy wiring, escalation contract, status view."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class Stage6Error(ValueError):
    pass


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_stage6_bundle(root_dir: Path) -> Dict[str, Any]:
    base = root_dir / 'specs' / 'task6' / 'v1'
    policy_path = root_dir / 'policy' / 'v1' / 'reviewer_ops_policy.json'
    required = {
        'escalation_contract': base / 'escalation-ui-contract.json',
        'autonomy_policy': base / 'autonomy-modes-policy.json',
        'reviewer_ops_policy': policy_path,
    }
    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        raise Stage6Error(f'missing stage6 runtime files: {missing}')
    return {key: _load_json(path) for key, path in required.items()}


def gate_behavior(root_dir: Path, mode: str, gate: str) -> Dict[str, Any]:
    bundle = load_stage6_bundle(root_dir)
    modes = bundle['autonomy_policy'].get('modes', {})
    mode_row = modes.get(mode)
    if not isinstance(mode_row, dict):
        raise Stage6Error(f'unknown autonomy mode: {mode}')
    gate_map = mode_row.get('gate_application', {})
    behavior = str(gate_map.get(gate, '')).strip()
    if behavior not in {'auto', 'manual'}:
        raise Stage6Error(f'unknown gate behavior for {mode}.{gate}')
    return {
        'mode': mode,
        'gate': gate,
        'behavior': behavior,
        'requires_user_approval': bool(mode_row.get('requires_user_approval', False)),
    }


def build_escalation_prompt(root_dir: Path, payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    bundle = load_stage6_bundle(root_dir)
    prompt_spec = bundle['escalation_contract'].get('prompt', {})
    response_spec = bundle['escalation_contract'].get('response', {})
    mode_row = (bundle['autonomy_policy'].get('modes') or {}).get(mode)
    if not isinstance(mode_row, dict):
        raise Stage6Error(f'unknown autonomy mode: {mode}')

    required_fields = list(prompt_spec.get('required_fields', []))
    missing = [k for k in required_fields if k not in payload and k not in {'candidate_actions', 'timestamp', 'escalation_id'}]
    if missing:
        raise Stage6Error(f'escalation prompt payload missing required fields: {missing}')

    requested_actions = set(mode_row.get('escalation_actions', []))
    allowed_actions = [a for a in response_spec.get('actions', []) if a in requested_actions]
    if not allowed_actions:
        raise Stage6Error('no allowed escalation actions for mode')

    correlation_id = str(payload.get('correlation_id'))
    escalation_id = str(payload.get('escalation_id') or f'esc_{correlation_id}')

    return {
        'escalation_id': escalation_id,
        'correlation_id': correlation_id,
        'workflow_class': str(payload.get('workflow_class')),
        'severity': str(payload.get('severity')),
        'reason': str(payload.get('reason')),
        'candidate_actions': allowed_actions,
        'requested_by': str(payload.get('requested_by')),
        'timestamp': str(payload.get('timestamp') or _now_iso()),
        'autonomy_mode': mode,
    }


def validate_escalation_response(root_dir: Path, prompt: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    bundle = load_stage6_bundle(root_dir)
    response_spec = bundle['escalation_contract'].get('response', {})
    required_fields = list(response_spec.get('required_fields', []))
    missing = [k for k in required_fields if k not in response]
    if missing:
        raise Stage6Error(f'escalation response missing required fields: {missing}')

    if str(response.get('escalation_id')) != str(prompt.get('escalation_id')):
        raise Stage6Error('escalation_id mismatch between prompt and response')

    selected = str(response.get('selected_action'))
    allowed_from_contract = set(response_spec.get('actions', []))
    allowed_from_prompt = set(prompt.get('candidate_actions', []))
    if selected not in allowed_from_contract or selected not in allowed_from_prompt:
        raise Stage6Error(f'selected_action not allowed: {selected}')

    return {
        'escalation_id': str(prompt.get('escalation_id')),
        'selected_action': selected,
        'reviewer_id': str(response.get('reviewer_id')),
        'accepted': True,
        'timestamp': str(response.get('timestamp')),
    }


def status_view(root_dir: Path, out_dir: Path) -> Dict[str, Any]:
    out = out_dir.resolve()
    if not out.exists() or not out.is_dir():
        raise Stage6Error(f'run out dir not found: {out}')

    va_path = out / 'VerificationArtifact.json'
    req_path = out / 'request.json'
    manifest_path = out / 'manifest.json'
    evidence_dir = out / 'evidence'
    for path in (va_path, req_path, manifest_path, evidence_dir):
        if not path.exists():
            raise Stage6Error(f'missing required run artifact: {path.name}')

    va = _load_json(va_path)
    request = _load_json(req_path)
    manifest = _load_json(manifest_path)
    bundle = load_stage6_bundle(root_dir)

    evidence_files = sorted(evidence_dir.glob('*.json'))
    evidence_total_size = sum(int(p.stat().st_size) for p in evidence_files)

    latest_mtime = 0.0
    for p in out.glob('**/*'):
        if p.is_file():
            latest_mtime = max(latest_mtime, p.stat().st_mtime)

    overall = str(va.get('overall_status', 'blocked'))
    current_state = 'complete' if overall in {'pass', 'warn'} else 'escalation'

    return {
        'run_id': out.name,
        'workflow_class': str(request.get('workflow_class', 'unknown')),
        'current_state': current_state,
        'overall_status': overall,
        'blocked_reason': str(va.get('blocker_reason', '')),
        'last_updated': datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat().replace('+00:00', 'Z') if latest_mtime else _now_iso(),
        'artifact_summary': {
            'required_artifacts': manifest.get('required_artifacts', []),
            'artifact_count': len(manifest.get('artifacts', [])),
        },
        'evidence_summary': {
            'evidence_record_count': len(evidence_files),
            'evidence_total_size_bytes': evidence_total_size,
        },
        'retention_policy': bundle['reviewer_ops_policy'].get('retention', {}),
        'redaction_policy': bundle['reviewer_ops_policy'].get('redaction', {}),
        'audit_policy': bundle['reviewer_ops_policy'].get('audit', {}),
    }

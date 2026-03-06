#!/usr/bin/env python3
"""Export a CanonicalConformanceBundle v1 for each run directory."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / 'specs' / 'task5' / 'v1' / 'canonical-conformance-bundle.schema.json'

ARTIFACT_MAP: dict[str, str] = {
    'verification_artifact': 'VerificationArtifact.json',
    'execution_plan': 'ExecutionPlan.json',
    'build_report': 'BuildReport.json',
    'evidence_registry': 'evidence_records.json',
    'proof': 'proof.json',
    'manifest': 'manifest.json',
    'trace': 'trace.jsonl',
    'run_state': 'run_state.json',
    'policy_snapshot': 'policy_snapshot.json',
    'request': 'request.json',
}


def _hash_file(file_path: Path) -> dict[str, Any]:
    data = file_path.read_bytes()
    return {
        'sha256': hashlib.sha256(data).hexdigest(),
        'size_bytes': len(data),
    }


def _validate_bundle(bundle: dict[str, Any]) -> list[str]:
    """Minimal inline schema validation (no external deps)."""
    errors: list[str] = []
    if bundle.get('version') != 'v1':
        errors.append('version must be "v1"')
    if not isinstance(bundle.get('workflow_class'), str) or not bundle['workflow_class']:
        errors.append('workflow_class must be non-empty string')
    if not isinstance(bundle.get('run_id'), str) or not bundle['run_id']:
        errors.append('run_id must be non-empty string')
    else:
        try:
            uuid.UUID(bundle['run_id'])
        except Exception:
            errors.append('run_id must be UUID-formatted')
    artifacts = bundle.get('artifacts')
    if not isinstance(artifacts, dict):
        errors.append('artifacts must be object')
        return errors
    required_keys = set(ARTIFACT_MAP.keys())
    for key in required_keys:
        if key not in artifacts:
            errors.append(f'artifacts missing key: {key}')
            continue
        val = artifacts[key]
        if val is None:
            continue
        if not isinstance(val, dict):
            errors.append(f'artifacts.{key} must be object or null')
            continue
        if not isinstance(val.get('sha256'), str) or len(val.get('sha256', '')) != 64:
            errors.append(f'artifacts.{key}.sha256 must be 64-char hex')
        if not isinstance(val.get('size_bytes'), int) or val['size_bytes'] < 0:
            errors.append(f'artifacts.{key}.size_bytes must be non-negative integer')
    extra = sorted(set(artifacts.keys()) - required_keys)
    for key in extra:
        errors.append(f'artifacts has unexpected key: {key}')
    return errors


def export_bundle(run_dir: Path) -> dict[str, Any]:
    run_id = run_dir.name
    run_state_path = run_dir / 'run_state.json'
    if run_state_path.exists():
        run_state = json.loads(run_state_path.read_text())
        corr = str(run_state.get('correlation_id', '')).strip()
        if corr:
            run_id = corr

    workflow_class = 'unknown'
    for probe in ('request.json', 'VerificationArtifact.json'):
        probe_path = run_dir / probe
        if probe_path.exists():
            doc = json.loads(probe_path.read_text())
            wc = doc.get('workflow_class') or doc.get('workflow_id', '')
            if wc:
                workflow_class = str(wc)
                break

    artifacts: dict[str, Any] = {}
    for key, filename in ARTIFACT_MAP.items():
        file_path = run_dir / filename
        # SV2 may store evidence_records as a directory of individual files
        if key == 'evidence_registry' and not file_path.exists():
            evidence_dir = run_dir / 'evidence'
            if evidence_dir.exists() and evidence_dir.is_dir():
                # Synthesize a hash from all evidence files combined
                combined = b''
                for ef in sorted(evidence_dir.glob('*.json')):
                    combined += ef.read_bytes()
                if combined:
                    artifacts[key] = {
                        'sha256': hashlib.sha256(combined).hexdigest(),
                        'size_bytes': len(combined),
                    }
                    continue
            artifacts[key] = None
        elif file_path.exists():
            artifacts[key] = _hash_file(file_path)
        else:
            artifacts[key] = None

    bundle: dict[str, Any] = {
        'version': 'v1',
        'workflow_class': workflow_class,
        'run_id': run_id,
        'artifacts': artifacts,
    }

    validation_errors = _validate_bundle(bundle)
    if validation_errors:
        print(f'Schema validation FAIL for {run_dir}:', file=sys.stderr)
        for err in validation_errors:
            print(f'  {err}', file=sys.stderr)
        sys.exit(1)

    out_path = run_dir / 'canonical_conformance_bundle.json'
    out_path.write_text(json.dumps(bundle, indent=2) + '\n')
    print(f'Exported: {out_path}')
    return bundle


def main() -> int:
    args = sys.argv[1:]
    dirs: list[Path] = []

    if args:
        dirs = [Path(a) for a in args]
    else:
        out_dir = ROOT / 'out'
        if out_dir.exists():
            dirs = sorted(
                d for d in out_dir.iterdir()
                if d.is_dir() and (d / 'VerificationArtifact.json').exists()
            )

    if not dirs:
        print('No run directories found. Pass paths or ensure out/ has run dirs.', file=sys.stderr)
        return 1

    for d in dirs:
        export_bundle(d)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

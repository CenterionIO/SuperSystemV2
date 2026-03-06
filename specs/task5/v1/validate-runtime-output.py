#!/usr/bin/env python3
"""Stage 5 runtime-output validator parity with SS.

Runs both golden workflows through the CLI, captures each `_persisted_out_dir`,
and validates emitted runtime artifacts and evidence linkage.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / 'cli.py'

REQUIRED_FILES = [
    'ExecutionPlan.json',
    'BuildReport.json',
    'VerificationArtifact.json',
    'run_state.json',
    'proof.json',
    'trace.jsonl',
    'policy_snapshot.json',
    'request.json',
]


def _run_golden(name: str) -> tuple[dict[str, Any] | None, str | None]:
    proc = subprocess.run(
        ['python3', str(CLI), 'golden', name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None, f'{name}: cli.py golden failed rc={proc.returncode}\n{proc.stderr.strip()}'

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return None, f'{name}: golden output is not JSON: {exc}'

    if not isinstance(payload, dict):
        return None, f'{name}: golden output must be a JSON object'
    return payload, None


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _validate_run(run_name: str, out_dir: Path, errors: list[str]) -> None:
    if not out_dir.exists() or not out_dir.is_dir():
        errors.append(f'{run_name}: out dir missing: {out_dir}')
        return

    for rel in REQUIRED_FILES:
        p = out_dir / rel
        if not p.exists():
            errors.append(f'{run_name}: missing required file {rel}')

    evidence_dir = out_dir / 'evidence'
    if not evidence_dir.exists() or not evidence_dir.is_dir():
        errors.append(f'{run_name}: missing evidence directory')
        return

    evidence_files = sorted(evidence_dir.glob('evidence_*.json'))
    if not evidence_files:
        errors.append(f'{run_name}: evidence dir has no evidence_*.json files')
        return

    evidence_by_id: dict[str, dict[str, Any]] = {}
    for evidence_file in evidence_files:
        try:
            record = _load(evidence_file)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'{run_name}: failed to parse {evidence_file.name}: {exc}')
            continue

        required = ['evidence_id', 'canonical_path', 'sha256', 'size_bytes']
        missing = [field for field in required if field not in record]
        if missing:
            errors.append(f"{run_name}: {evidence_file.name} missing fields: {missing}")
            continue

        if not isinstance(record.get('evidence_id'), str) or not record['evidence_id']:
            errors.append(f'{run_name}: {evidence_file.name} evidence_id must be non-empty string')
            continue
        if not isinstance(record.get('canonical_path'), str) or not record['canonical_path']:
            errors.append(f'{run_name}: {evidence_file.name} canonical_path must be non-empty string')
        if not isinstance(record.get('sha256'), str) or not record['sha256']:
            errors.append(f'{run_name}: {evidence_file.name} sha256 must be non-empty string')
        if not isinstance(record.get('size_bytes'), int) or record['size_bytes'] < 0:
            errors.append(f'{run_name}: {evidence_file.name} size_bytes must be non-negative integer')

        evidence_by_id[record['evidence_id']] = record

    verification_path = out_dir / 'VerificationArtifact.json'
    if not verification_path.exists():
        errors.append(f'{run_name}: missing VerificationArtifact.json')
        return

    verification = _load(verification_path)
    checks = verification.get('checks')
    if not isinstance(checks, list) or len(checks) == 0:
        errors.append(f'{run_name}: VerificationArtifact.checks must be a non-empty list')
        return

    for idx, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            errors.append(f'{run_name}: checks[{idx}] must be object')
            continue
        refs = check.get('evidence_refs')
        if not isinstance(refs, list) or len(refs) == 0:
            errors.append(f"{run_name}: checks[{idx}] missing non-empty evidence_refs")
            continue
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                errors.append(f'{run_name}: checks[{idx}] has invalid evidence ref value: {ref!r}')
                continue
            if ref not in evidence_by_id:
                errors.append(f'{run_name}: checks[{idx}] references unknown evidence id: {ref}')

    manifest = out_dir / 'manifest.json'
    proof = out_dir / 'proof.json'
    run_state = out_dir / 'run_state.json'
    if manifest.exists() and not manifest.is_file():
        errors.append(f'{run_name}: manifest.json exists but is not a file')
    if not proof.exists():
        errors.append(f'{run_name}: missing proof.json')
    elif not proof.is_file():
        errors.append(f'{run_name}: proof.json exists but is not a file')
    if not run_state.exists():
        errors.append(f'{run_name}: missing run_state.json')
    elif not run_state.is_file():
        errors.append(f'{run_name}: run_state.json exists but is not a file')


def main() -> int:
    errors: list[str] = []
    run_dirs: dict[str, Path] = {}

    for name in ('code_change', 'mcp_tool'):
        payload, err = _run_golden(name)
        if err:
            errors.append(err)
            continue

        out_dir_raw = str((payload or {}).get('_persisted_out_dir', '')).strip()
        if not out_dir_raw:
            errors.append(f'{name}: missing _persisted_out_dir in CLI response')
            continue

        out_dir = Path(out_dir_raw)
        run_dirs[name] = out_dir
        _validate_run(name, out_dir, errors)

    # Generate and validate canonical_conformance_bundle.json
    export_script = ROOT / 'tools' / 'export_canonical_conformance.py'
    for name, out_dir in run_dirs.items():
        proc = subprocess.run(
            ['python3', str(export_script), str(out_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            errors.append(f'{name}: export_canonical_conformance failed rc={proc.returncode}\n{proc.stderr.strip()}')
            continue

        bundle_path = out_dir / 'canonical_conformance_bundle.json'
        if not bundle_path.exists():
            errors.append(f'{name}: canonical_conformance_bundle.json not generated')
            continue

        try:
            bundle = json.loads(bundle_path.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f'{name}: canonical_conformance_bundle.json invalid JSON: {exc}')
            continue

        if bundle.get('version') != 'v1':
            errors.append(f'{name}: bundle version must be v1')
        if not isinstance(bundle.get('workflow_class'), str) or not bundle['workflow_class']:
            errors.append(f'{name}: bundle workflow_class missing')
        if not isinstance(bundle.get('run_id'), str) or not bundle['run_id']:
            errors.append(f'{name}: bundle run_id missing')
        artifacts = bundle.get('artifacts')
        if not isinstance(artifacts, dict):
            errors.append(f'{name}: bundle artifacts missing')
        else:
            required_keys = [
                'verification_artifact', 'execution_plan', 'build_report',
                'evidence_registry', 'proof', 'manifest', 'trace',
                'run_state', 'policy_snapshot', 'request',
            ]
            for key in required_keys:
                if key not in artifacts:
                    errors.append(f'{name}: bundle artifacts missing key: {key}')
            for key in ('run_state', 'proof'):
                if artifacts.get(key) is None:
                    errors.append(f'{name}: bundle artifacts.{key} must be non-null')

    if errors:
        print('Stage 5 runtime output validation: FAIL')
        for err in errors:
            print(f'- {err}')
        return 1

    print('Stage 5 runtime output validation: PASS')
    for name in ('code_change', 'mcp_tool'):
        if name in run_dirs:
            print(f"- {name}: {run_dirs[name]}")
    print('- checks: required files, evidence records, VerificationArtifact evidence linkage')
    print('- canonical_conformance_bundle.json generated + validated')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

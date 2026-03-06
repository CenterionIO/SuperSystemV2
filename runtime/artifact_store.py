#!/usr/bin/env python3
"""Deterministic output writer for out/<correlation_id>/..."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def persist_outputs(
    root_dir: Path,
    correlation_id: str,
    *,
    execution_plan: Dict[str, Any] | None = None,
    build_report: Dict[str, Any],
    verification_artifact: Dict[str, Any],
    trace_rows: Iterable[Dict[str, Any]],
    policy_snapshot: Dict[str, Any],
    request_snapshot: Dict[str, Any],
    evidence_rows: Iterable[Dict[str, Any]],
) -> Path:
    base = root_dir / "out" / correlation_id
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if execution_plan is not None:
        (base / "ExecutionPlan.json").write_text(json.dumps(execution_plan, indent=2) + "\n")
    (base / "BuildReport.json").write_text(json.dumps(build_report, indent=2) + "\n")
    (base / "VerificationArtifact.json").write_text(json.dumps(verification_artifact, indent=2) + "\n")
    (base / "policy_snapshot.json").write_text(json.dumps(policy_snapshot, indent=2) + "\n")
    (base / "request.json").write_text(json.dumps(request_snapshot, indent=2) + "\n")

    with (base / "trace.jsonl").open("a", encoding="utf-8") as fh:
        for row in trace_rows:
            fh.write(json.dumps(row) + "\n")

    for idx, row in enumerate(evidence_rows, start=1):
        (evidence_dir / f"evidence_{idx:04d}.json").write_text(json.dumps(row, indent=2) + "\n")

    required = [
        "ExecutionPlan.json",
        "BuildReport.json",
        "VerificationArtifact.json",
        "trace.jsonl",
        "policy_snapshot.json",
        "request.json",
    ]
    evidence_paths = sorted(str(path.relative_to(base)) for path in evidence_dir.glob("*.json"))
    artifacts = []
    for rel_path in sorted(required + evidence_paths):
        path = base / rel_path
        if not path.exists():
            continue
        artifacts.append(
            {
                "path": rel_path,
                "sha256": _sha256_file(path),
                "size_bytes": int(path.stat().st_size),
            }
        )
    manifest = {
        "schema_version": "v1",
        "correlation_id": correlation_id,
        "required_artifacts": required,
        "artifacts": artifacts,
    }
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    return base

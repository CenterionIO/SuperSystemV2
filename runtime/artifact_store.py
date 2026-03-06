#!/usr/bin/env python3
"""Deterministic output writer for out/<correlation_id>/..."""

from __future__ import annotations

import json
import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except Exception:
        # Deterministic UUID for non-UUID correlation IDs.
        return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value)))


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
    correlation_uuid = _coerce_uuid(correlation_id)
    base = root_dir / "out" / correlation_id
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if execution_plan is not None:
        (base / "ExecutionPlan.json").write_text(json.dumps(execution_plan, indent=2) + "\n")
    (base / "BuildReport.json").write_text(json.dumps(build_report, indent=2) + "\n")
    (base / "VerificationArtifact.json").write_text(json.dumps(verification_artifact, indent=2) + "\n")
    (base / "policy_snapshot.json").write_text(json.dumps(policy_snapshot, indent=2) + "\n")
    (base / "request.json").write_text(json.dumps(request_snapshot, indent=2) + "\n")

    trace_cache: list[dict[str, Any]] = []
    with (base / "trace.jsonl").open("a", encoding="utf-8") as fh:
        for row in trace_rows:
            trace_cache.append(row)
            fh.write(json.dumps(row) + "\n")

    evidence_cache = list(evidence_rows)
    for idx, row in enumerate(evidence_cache, start=1):
        (evidence_dir / f"evidence_{idx:04d}.json").write_text(json.dumps(row, indent=2) + "\n")

    last_transition_at = ""
    for row in reversed(trace_cache):
        ts = str(row.get("timestamp", "")).strip()
        if ts:
            last_transition_at = ts
            break
    current_state = "complete" if str(verification_artifact.get("overall_status")) == "pass" else "blocked"
    run_state = {
        "correlation_id": correlation_uuid,
        "current_state": current_state,
        "transitions": trace_cache,
        "last_transition_at": last_transition_at,
    }
    (base / "run_state.json").write_text(json.dumps(run_state, indent=2) + "\n")

    evidence_by_id = {
        str(row.get("evidence_id", "")): row
        for row in evidence_cache
        if isinstance(row, dict) and str(row.get("evidence_id", "")).strip()
    }
    linkage_resolved = True
    for check in verification_artifact.get("checks", []) if isinstance(verification_artifact, dict) else []:
        refs = check.get("evidence_refs") if isinstance(check, dict) else None
        if not isinstance(refs, list):
            linkage_resolved = False
            break
        for ref in refs:
            meta = evidence_by_id.get(str(ref))
            if not isinstance(meta, dict):
                linkage_resolved = False
                break
            if not str(meta.get("canonical_path", "")).strip():
                linkage_resolved = False
                break
            if not str(meta.get("sha256", "")).strip():
                linkage_resolved = False
                break
            if not isinstance(meta.get("size_bytes"), int) or int(meta.get("size_bytes", 0)) <= 0:
                linkage_resolved = False
                break
        if not linkage_resolved:
            break
    proof = {
        "overall_status": str(verification_artifact.get("overall_status", "")),
        "evidence_linkage_resolved": linkage_resolved,
        "created_at": last_transition_at,
    }
    (base / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")

    required = [
        "ExecutionPlan.json",
        "BuildReport.json",
        "VerificationArtifact.json",
        "run_state.json",
        "proof.json",
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

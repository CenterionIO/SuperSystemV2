#!/usr/bin/env python3
"""Deterministic output writer for out/<correlation_id>/..."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable


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

    return base

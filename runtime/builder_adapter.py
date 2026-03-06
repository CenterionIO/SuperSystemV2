#!/usr/bin/env python3
"""Minimal deterministic Builder adapter for executable MVP golden flows."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def simulate_build(
    *,
    root_dir: Path,
    workflow_id: str,
    correlation_id: str,
    plan: Dict[str, Any],
    required_checks: List[str],
) -> Dict[str, Any]:
    run_inputs = root_dir / "out" / correlation_id / "inputs"
    run_inputs.mkdir(parents=True, exist_ok=True)

    criteria_results = []
    artifacts = []

    for i, check_type in enumerate(required_checks, start=1):
        evidence_id = f"ev_{check_type}_{i:03d}"
        content = f"simulated artifact for {check_type}"
        artifact_path = run_inputs / f"artifact_{i:03d}.txt"
        artifact_path.write_text(content)

        criteria_results.append(
            {
                "criteria_id": check_type,
                "status": "pass",
                "evidence_ids": [evidence_id],
            }
        )
        artifacts.append(
            {
                "evidence_id": evidence_id,
                "kind": "simulated",
                "path": str(artifact_path.relative_to(root_dir)),
                "sha256": _sha256_text(content),
            }
        )

    return {
        "schema_version": "v1",
        "build_report_id": f"build_{workflow_id}",
        "workflow_id": workflow_id,
        "correlation_id": correlation_id,
        "plan_id": str(plan.get("execution_plan_id", f"plan_{workflow_id}")),
        "criteria_results": criteria_results,
        "artifacts": artifacts,
        "notes": "Simulated builder output",
    }

#!/usr/bin/env python3
"""Deterministic reviewer-facing proof surface for run artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict


class ProofError(ValueError):
    pass


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_out_dir(out_dir: str | Path) -> Path:
    path = Path(out_dir)
    if not path.exists() or not path.is_dir():
        raise ProofError(f"out dir not found: {path}")
    return path


def proof_run(out_dir: str | Path) -> Dict[str, Any]:
    base = _resolve_out_dir(out_dir)
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        raise ProofError("manifest.json missing")

    manifest = _load_json(manifest_path)
    verification_artifact = _load_json(base / "VerificationArtifact.json")
    build_report = _load_json(base / "BuildReport.json")

    evidence_records = {}
    evidence_dir = base / "evidence"
    for path in sorted(evidence_dir.glob("*.json")):
        row = _load_json(path)
        evidence_id = str(row.get("evidence_id", ""))
        if evidence_id:
            evidence_records[evidence_id] = row

    manifest_ok = True
    manifest_errors: list[str] = []
    for entry in manifest.get("artifacts", []):
        rel = str(entry.get("path", ""))
        file_path = base / rel
        if not file_path.exists():
            manifest_ok = False
            manifest_errors.append(f"missing artifact {rel}")
            continue
        expected_hash = str(entry.get("sha256", ""))
        expected_size = int(entry.get("size_bytes", -1))
        actual_hash = _sha256_file(file_path)
        actual_size = int(file_path.stat().st_size)
        if expected_hash != actual_hash:
            manifest_ok = False
            manifest_errors.append(f"hash mismatch {rel}")
        if expected_size != actual_size:
            manifest_ok = False
            manifest_errors.append(f"size mismatch {rel}")

    broken_links: list[str] = []
    for check in verification_artifact.get("checks", []):
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("check_id", ""))
        refs = check.get("evidence_refs", [])
        if not isinstance(refs, list):
            broken_links.append(f"{check_id}: evidence_refs missing")
            continue
        for ref in refs:
            if str(ref) not in evidence_records:
                broken_links.append(f"{check_id}: unknown evidence_id {ref}")

    criteria_to_evidence: dict[str, list[str]] = {}
    for row in build_report.get("criteria_results", []):
        if isinstance(row, dict):
            criteria_to_evidence[str(row.get("criteria_id", ""))] = [str(v) for v in row.get("evidence_ids", [])]

    return {
        "out_dir": str(base),
        "correlation_id": str(verification_artifact.get("correlation_id", "")),
        "overall_status": str(verification_artifact.get("overall_status", "")),
        "manifest_ok": manifest_ok,
        "manifest_errors": manifest_errors,
        "evidence_records_count": len(evidence_records),
        "verification_checks_count": len(verification_artifact.get("checks", [])),
        "broken_link_count": len(broken_links),
        "broken_links": broken_links,
        "criteria_to_evidence": criteria_to_evidence,
        "pass": manifest_ok and not broken_links,
    }


def proof_evidence(out_dir: str | Path, evidence_id: str) -> Dict[str, Any]:
    base = _resolve_out_dir(out_dir)
    if not evidence_id:
        raise ProofError("evidence_id required")

    evidence_path = None
    evidence_record = None
    evidence_dir = base / "evidence"
    for path in sorted(evidence_dir.glob("*.json")):
        row = _load_json(path)
        if str(row.get("evidence_id", "")) == evidence_id:
            evidence_path = path
            evidence_record = row
            break
    if evidence_record is None or evidence_path is None:
        raise ProofError(f"evidence not found: {evidence_id}")

    build_report = _load_json(base / "BuildReport.json")
    verification_artifact = _load_json(base / "VerificationArtifact.json")

    build_refs: list[str] = []
    for row in build_report.get("criteria_results", []):
        if not isinstance(row, dict):
            continue
        refs = [str(v) for v in row.get("evidence_ids", [])]
        if evidence_id in refs:
            build_refs.append(str(row.get("criteria_id", "")))

    verify_refs: list[str] = []
    for check in verification_artifact.get("checks", []):
        if not isinstance(check, dict):
            continue
        refs = [str(v) for v in check.get("evidence_refs", [])]
        if evidence_id in refs:
            verify_refs.append(str(check.get("check_id", "")))

    file_hash = _sha256_file(evidence_path)
    file_size = int(evidence_path.stat().st_size)

    return {
        "out_dir": str(base),
        "evidence_id": evidence_id,
        "evidence_file": str(evidence_path),
        "record": evidence_record,
        "file_sha256": file_hash,
        "file_size_bytes": file_size,
        "linked_from_build_criteria": build_refs,
        "linked_from_verification_checks": verify_refs,
        "pass": bool(build_refs) and bool(verify_refs),
    }

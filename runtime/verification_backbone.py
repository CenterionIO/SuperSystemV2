#!/usr/bin/env python3
"""Stage 5 verification backbone runtime engine.

Evaluates criteria results against Stage 4 specs + policy bundle and emits
canonical verification outputs with fail-closed behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from runtime.policy_engine import (
    PolicyBundle,
    apply_fail_closed,
    normalize_status,
)


@dataclass(frozen=True)
class VerificationSpecs:
    engine: Dict[str, Any]
    plugin_abi: Dict[str, Any]
    evidence_registry: Dict[str, Any]


class VerificationBackbone:
    def __init__(self, root_dir: Path, policy_bundle: PolicyBundle) -> None:
        self.root_dir = root_dir
        self.bundle = policy_bundle
        self.specs = self._load_specs(root_dir)

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text())

    def _load_specs(self, root_dir: Path) -> VerificationSpecs:
        base = root_dir / "specs" / "task4" / "v1"
        return VerificationSpecs(
            engine=self._load_json(base / "verify-mcp-engine.json"),
            plugin_abi=self._load_json(base / "verifier-plugin-abi.json"),
            evidence_registry=self._load_json(base / "evidence-registry.json"),
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _aggregate_status(check_statuses: List[str]) -> str:
        if "blocked" in check_statuses:
            return "blocked"
        if "fail" in check_statuses:
            return "fail"
        if "warn" in check_statuses:
            return "warn"
        return "pass"

    def _validate_evidence_refs(self, refs: List[str]) -> list[str]:
        prefix = "ev_"
        bad: list[str] = []
        for ref in refs:
            if not isinstance(ref, str) or not ref.startswith(prefix):
                bad.append(str(ref))
        return bad

    def run(self, job_id: str, domain: str, request: Dict[str, Any]) -> Dict[str, Any]:
        subject = request.get("subject", {}) or {}
        workflow_class = str(request.get("workflow_class") or subject.get("workflow_class") or "").strip()
        correlation_id = str(request.get("correlation_id") or subject.get("correlation_id") or job_id)
        has_exception_artifact = bool(request.get("has_exception_artifact", False))

        checks_run: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []

        if workflow_class not in self.bundle.workflow_taxonomy.get("classes", {}):
            return {
                "job_id": job_id,
                "domain": domain,
                "overall_status": "blocked",
                "summary": f"Unknown workflow_class: {workflow_class}",
                "checks_run": [{"check_id": "workflow_class", "status": "blocked", "reason": "unknown workflow_class"}],
                "findings": [],
                "evidence": [],
                "tool_trace": [],
                "verification_artifact": None,
                "verifier_version": "mcp-verify-orchestrator@v1",
                "policy_version": "v1",
                "timestamp": self._now_iso(),
            }

        supported_check_types = set(self.specs.engine.get("supported_check_types", []))
        required_checks = set(self.bundle.workflow_taxonomy["classes"][workflow_class].get("required_checks", []))

        criteria_input = request.get("criteria") or subject.get("criteria") or []
        if not isinstance(criteria_input, list):
            criteria_input = []

        seen_required: set[str] = set()
        artifact_checks: list[dict[str, Any]] = []

        for idx, raw in enumerate(criteria_input):
            item = raw if isinstance(raw, dict) else {}
            check_id = str(item.get("check_id") or f"check_{idx+1}")
            check_type = str(item.get("check_type") or "").strip()
            input_status = str(item.get("status") or "blocked")
            required = bool(item.get("required", check_type in required_checks))
            message = str(item.get("message") or "")
            refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
            refs = [str(r) for r in refs]

            if required and check_type:
                seen_required.add(check_type)

            if check_type not in supported_check_types:
                checks_run.append(
                    {
                        "check_id": check_id,
                        "status": "blocked",
                        "reason": f"unsupported check_type: {check_type}",
                    }
                )
                findings.append(
                    {
                        "severity": "high",
                        "type": "unsupported_check_type",
                        "claim": check_type,
                        "reason": f"Check type is not supported by verification engine: {check_type}",
                        "evidence_refs": [],
                    }
                )
                artifact_checks.append(
                    {
                        "check_id": check_id,
                        "check_type": check_type or "unknown",
                        "required": required,
                        "status": "blocked",
                        "message": "unsupported check_type",
                    }
                )
                continue

            bad_refs = self._validate_evidence_refs(refs)
            status = normalize_status(input_status)
            if bad_refs:
                status = "blocked"
                findings.append(
                    {
                        "severity": "medium",
                        "type": "invalid_evidence_ref",
                        "claim": check_id,
                        "reason": f"Invalid evidence refs: {bad_refs}",
                        "evidence_refs": [],
                    }
                )

            effective_status = apply_fail_closed(
                self.bundle,
                status,
                required=required,
                has_exception_artifact=has_exception_artifact,
            )

            checks_run.append(
                {
                    "check_id": check_id,
                    "status": effective_status,
                    "reason": message or f"{check_type} -> {effective_status}",
                }
            )
            artifact_checks.append(
                {
                    "check_id": check_id,
                    "check_type": check_type,
                    "required": required,
                    "status": effective_status,
                    "message": message,
                }
            )

            for ref in refs:
                evidence.append(
                    {
                        "id": ref,
                        "source_type": "registry",
                        "source": "evidence-registry",
                        "excerpt": check_id,
                        "timestamp": self._now_iso(),
                    }
                )

            if effective_status in {"blocked", "fail", "warn"}:
                findings.append(
                    {
                        "severity": "medium" if effective_status == "warn" else "high",
                        "type": "criteria_not_passed",
                        "claim": check_id,
                        "reason": f"{check_type} returned {effective_status}",
                        "evidence_refs": refs,
                    }
                )

        # Required checks missing -> fail-closed blocked.
        for missing in sorted(required_checks - seen_required):
            check_id = f"missing_required_{missing}"
            checks_run.append(
                {
                    "check_id": check_id,
                    "status": "blocked",
                    "reason": f"required check missing: {missing}",
                }
            )
            artifact_checks.append(
                {
                    "check_id": check_id,
                    "check_type": missing,
                    "required": True,
                    "status": "blocked",
                    "message": "required check missing",
                }
            )
            findings.append(
                {
                    "severity": "high",
                    "type": "missing_required_check",
                    "claim": missing,
                    "reason": f"Required check not supplied: {missing}",
                    "evidence_refs": [],
                }
            )

        overall_status = self._aggregate_status([c["status"] for c in checks_run] or ["blocked"])
        fail_closed = overall_status == "blocked"

        verification_artifact = {
            "schema_version": "v1",
            "verification_id": f"ver_{job_id}",
            "workflow_id": str(request.get("workflow_id") or job_id),
            "correlation_id": correlation_id,
            "verifier_version": "mcp-verify-orchestrator@v1",
            "checks": artifact_checks,
            "overall_status": overall_status,
            "fail_closed": fail_closed,
            "blocker_reason": "required check blocked or missing" if fail_closed else "",
        }

        summary_by_status = {
            "pass": "Verification passed: all required checks passed.",
            "warn": "Verification warning: one or more checks returned warn.",
            "fail": "Verification failed: one or more checks returned fail.",
            "blocked": "Verification blocked: fail-closed conditions were triggered.",
        }

        return {
            "job_id": job_id,
            "domain": domain,
            "overall_status": overall_status,
            "summary": summary_by_status[overall_status],
            "checks_run": checks_run,
            "findings": findings,
            "evidence": evidence,
            "tool_trace": [],
            "verification_artifact": verification_artifact,
            "verifier_version": "mcp-verify-orchestrator@v1",
            "policy_version": "v1",
            "timestamp": self._now_iso(),
        }

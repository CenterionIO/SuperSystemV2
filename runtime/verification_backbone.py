#!/usr/bin/env python3
"""Stage 5 verification backbone runtime engine.

Evaluates criteria results against Stage 4 specs + policy bundle and emits
canonical verification outputs with fail-closed behavior.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from runtime.artifact_store import persist_outputs
from runtime.policy_engine import (
    PolicyBundle,
    apply_fail_closed,
    normalize_status,
)
from runtime.spec_loader import RuntimeSpecBundle, load_runtime_spec_bundle


@dataclass(frozen=True)
class VerificationSpecs:
    engine: Dict[str, Any]
    plugin_abi: Dict[str, Any]
    evidence_registry: Dict[str, Any]


class VerificationBackbone:
    def __init__(self, root_dir: Path, policy_bundle: PolicyBundle) -> None:
        self.root_dir = root_dir
        self.bundle = policy_bundle
        self.spec_bundle: RuntimeSpecBundle = load_runtime_spec_bundle(root_dir)
        self.specs = self._load_specs(root_dir)
        self.max_criteria_per_request = int(self.spec_bundle.config.limits.get("max_criteria_per_request", 200))
        self.plugin_registry = self._build_plugin_registry()

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

    def _build_plugin_registry(self) -> Dict[str, Dict[str, Any]]:
        timeout_default = int(self.specs.plugin_abi.get("timeout_policy", {}).get("default_timeout_ms", 30000))
        caps = self.specs.plugin_abi.get("capability_flags", {})
        registry: Dict[str, Dict[str, Any]] = {}
        for check_type in self.specs.engine.get("supported_check_types", []):
            registry[str(check_type)] = {
                "handler": self._default_plugin_handler,
                "timeout_ms": timeout_default,
                "capabilities": caps,
            }
        return registry

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

    @staticmethod
    def _default_plugin_handler(item: Dict[str, Any]) -> Dict[str, Any]:
        # Deterministic stub plugin: accepts declared status from criteria payload.
        return {"status": str(item.get("status", "blocked")), "message": str(item.get("message", ""))}

    def _run_plugin_with_timeout(self, check_type: str, item: Dict[str, Any]) -> Dict[str, Any]:
        plugin = self.plugin_registry.get(check_type)
        if not plugin:
            return {"status": "blocked", "message": f"plugin not found for check_type={check_type}"}
        timeout_s = max(0.001, float(plugin["timeout_ms"]) / 1000.0)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(plugin["handler"], item)
            try:
                return fut.result(timeout=timeout_s)
            except TimeoutError:
                return {"status": "blocked", "message": f"plugin timeout for check_type={check_type}"}
            except Exception as exc:
                return {"status": "blocked", "message": f"plugin error for check_type={check_type}: {exc}"}

    def _build_artifact_lookup(self, request: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        build_report = request.get("build_report")
        artifacts = build_report.get("artifacts", []) if isinstance(build_report, dict) else []
        lookup: Dict[str, Dict[str, Any]] = {}
        for row in artifacts:
            if not isinstance(row, dict):
                continue
            evidence_id = str(row.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            raw_path = str(row.get("path", "")).strip()
            canonical_path = raw_path
            size_bytes = 0
            if raw_path:
                path_obj = Path(raw_path)
                if not path_obj.is_absolute():
                    path_obj = (self.root_dir / raw_path).resolve()
                else:
                    path_obj = path_obj.resolve()
                canonical_path = str(path_obj)
                if path_obj.exists() and path_obj.is_file():
                    size_bytes = int(path_obj.stat().st_size)
            lookup[evidence_id] = {
                "evidence_id": evidence_id,
                "canonical_path": canonical_path,
                "sha256": str(row.get("sha256", "")),
                "size_bytes": size_bytes,
            }
        return lookup

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
        if len(criteria_input) > self.max_criteria_per_request:
            return {
                "job_id": job_id,
                "domain": domain,
                "overall_status": "blocked",
                "summary": f"criteria length exceeds cap: {len(criteria_input)}>{self.max_criteria_per_request}",
                "checks_run": [{"check_id": "criteria_cap", "status": "blocked", "reason": "criteria count exceeds cap"}],
                "findings": [],
                "evidence": [],
                "tool_trace": [],
                "verification_artifact": None,
                "verifier_version": "mcp-verify-orchestrator@v1",
                "policy_version": "v1",
                "timestamp": self._now_iso(),
            }

        seen_required: set[str] = set()
        artifact_checks: list[dict[str, Any]] = []
        referenced_evidence_ids: set[str] = set()
        artifact_lookup = self._build_artifact_lookup(request)

        for idx, raw in enumerate(criteria_input):
            item = raw if isinstance(raw, dict) else {}
            check_id = str(item.get("check_id") or f"check_{idx+1}")
            check_type = str(item.get("check_type") or "").strip()
            input_status = str(item.get("status") or "blocked")
            required = bool(item.get("required", check_type in required_checks))
            message = str(item.get("message") or "")
            refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
            refs = [str(r) for r in refs]
            referenced_evidence_ids.update(refs)

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
                        "evidence_refs": refs,
                    }
                )
                continue

            plugin_result = self._run_plugin_with_timeout(check_type, item)
            bad_refs = self._validate_evidence_refs(refs)
            unresolved_refs: list[str] = []
            for ref in refs:
                meta = artifact_lookup.get(ref)
                if not meta:
                    unresolved_refs.append(ref)
                    continue
                has_path = bool(str(meta.get("canonical_path", "")).strip())
                has_hash = bool(str(meta.get("sha256", "")).strip())
                has_size = int(meta.get("size_bytes", 0)) > 0
                if not (has_path and has_hash and has_size):
                    unresolved_refs.append(ref)
            status = normalize_status(plugin_result.get("status", input_status))
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
            if unresolved_refs:
                status = "blocked"
                findings.append(
                    {
                        "severity": "high",
                        "type": "evidence_linkage_invalid",
                        "claim": check_id,
                        "reason": f"Evidence linkage invalid for refs: {unresolved_refs}",
                        "evidence_refs": refs,
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
                    "reason": plugin_result.get("message") or message or f"{check_type} -> {effective_status}",
                }
            )
            artifact_checks.append(
                {
                    "check_id": check_id,
                    "check_type": check_type,
                    "required": required,
                    "status": effective_status,
                    "message": message,
                    "evidence_refs": refs,
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
                    "evidence_refs": [],
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

        for evidence_id in sorted(referenced_evidence_ids):
            meta = artifact_lookup.get(
                evidence_id,
                {
                    "evidence_id": evidence_id,
                    "canonical_path": "",
                    "sha256": "",
                    "size_bytes": 0,
                },
            )
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "canonical_path": str(meta.get("canonical_path", "")),
                    "sha256": str(meta.get("sha256", "")),
                    "size_bytes": int(meta.get("size_bytes", 0)),
                    "produced_by": "builder_adapter",
                    "produced_at": self._now_iso(),
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
            "_persisted_out_dir": str(
                persist_outputs(
                    self.root_dir,
                    correlation_id,
                    execution_plan=request.get("execution_plan") if isinstance(request.get("execution_plan"), dict) else None,
                    build_report=request.get("build_report") or {"correlation_id": correlation_id, "status": overall_status},
                    verification_artifact=verification_artifact,
                    trace_rows=[
                        {
                            "event": "verify_start",
                            "job_id": job_id,
                            "domain": domain,
                            "workflow_class": workflow_class,
                            "timestamp": self._now_iso(),
                        },
                        {
                            "event": "verify_complete",
                            "job_id": job_id,
                            "domain": domain,
                            "overall_status": overall_status,
                            "timestamp": self._now_iso(),
                        }
                    ],
                    policy_snapshot={
                        "workflow_taxonomy_version": self.bundle.workflow_taxonomy.get("version"),
                        "routing_policy_version": self.bundle.routing_policy.get("version"),
                        "permissions_policy_version": self.bundle.permissions_policy.get("version"),
                        "override_policy_version": self.bundle.override_policy.get("version"),
                    },
                    request_snapshot=request,
                    evidence_rows=evidence,
                )
            ),
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

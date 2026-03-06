#!/usr/bin/env python3
"""mcp-verify-orchestrator — canonical verification entrypoint (rebuild mode).

This server intentionally provides a contract-first interface only.
Domain logic is rebuilt as plugins later; no legacy verifier internals are called.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp_file_checker import file_exists as _file_exists
from mcp_witness import search_evidence as _search_evidence
from runtime.permissions_guard import (
    PermissionError as _PermissionError,
    ensure_path_allowed as _ensure_path_allowed,
    ensure_tool_allowed as _ensure_tool_allowed,
)
from runtime.policy_engine import (
    apply_fail_closed as _apply_fail_closed,
    load_policy_bundle as _load_policy_bundle,
    next_state_for_verification as _next_state_for_verification,
)
from runtime.schema_checks import (
    SchemaValidationError as _SchemaValidationError,
    validate_verify_request as _validate_verify_request,
    validate_verify_response as _validate_verify_response,
)
from runtime.spec_loader import SpecVersionError as _SpecVersionError, load_runtime_spec_bundle as _load_runtime_spec_bundle
from runtime.verification_backbone import VerificationBackbone

server = FastMCP("mcp-verify-orchestrator")
_POLICY_BUNDLE = _load_policy_bundle(Path(__file__).resolve().parent)
_VERIFY_ROLE = "VerifyMCP"
_SPEC_BUNDLE = _load_runtime_spec_bundle(Path(__file__).resolve().parent)
_VERIFICATION_BACKBONE = VerificationBackbone(Path(__file__).resolve().parent, _POLICY_BUNDLE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _blocked_result(job_id: str, domain: str, reason: str) -> dict:
    return {
        "job_id": job_id,
        "domain": domain,
        "overall_status": "blocked",
        "summary": reason,
        "checks_run": [{"check_id": f"{domain}_plugin", "status": "blocked", "reason": "not_implemented"}],
        "findings": [],
        "evidence": [],
        "tool_trace": [],
        "verifier_version": "mcp-verify-orchestrator@v1",
        "policy_version": "v1",
        "timestamp": _now_iso(),
    }


def _truth_v1(job_id: str, request: dict) -> dict:
    """Minimal rebuild-safe conversation verifier.

    This intentionally avoids legacy dependencies and external model calls.
    It provides deterministic checks so conversation verification is active.
    """
    subject = request.get("subject", {}) or {}
    question = str(subject.get("question", "")).strip()
    assistant_output = str(subject.get("assistant_output", "")).strip()

    checks_run = []
    findings = []
    evidence = []
    tool_trace = []
    lower_output = assistant_output.lower()
    is_runtime_error = assistant_output.startswith("[Provider error]") or assistant_output.startswith("[Agent error]")

    if not assistant_output:
        checks_run.append(
            {"check_id": "non_empty_response", "status": "fail", "reason": "assistant output is empty"}
        )
        findings.append(
            {
                "severity": "high",
                "type": "empty_response",
                "claim": "",
                "reason": "Assistant output is empty.",
                "evidence_refs": [],
            }
        )
        return {
            "job_id": job_id,
            "domain": "truth",
            "overall_status": "fail",
            "summary": "Truth v1 failed: empty assistant response.",
            "checks_run": checks_run,
            "findings": findings,
            "evidence": [],
            "tool_trace": [],
            "verifier_version": "mcp-verify-orchestrator@v1",
            "policy_version": "v1",
            "timestamp": _now_iso(),
        }

    checks_run.append(
        {"check_id": "non_empty_response", "status": "pass", "reason": "assistant output present"}
    )

    # Provider/agent runtime errors are blocked for runtime reasons, not freshness.
    if is_runtime_error:
        checks_run.append(
            {
                "check_id": "runtime_response",
                "status": "blocked",
                "reason": "assistant returned provider/agent runtime error",
            }
        )
        findings.append(
            {
                "severity": "medium",
                "type": "runtime_error",
                "claim": "",
                "reason": "Assistant returned runtime/provider error instead of a substantive answer.",
                "evidence_refs": [],
            }
        )
        return {
            "job_id": job_id,
            "domain": "truth",
            "overall_status": "blocked",
            "summary": "Truth v1 blocked: runtime/provider error response.",
            "checks_run": checks_run,
            "findings": findings,
            "evidence": evidence,
            "tool_trace": tool_trace,
            "verifier_version": "mcp-verify-orchestrator@v1",
            "policy_version": "v1",
            "timestamp": _now_iso(),
        }

    # Deterministic local claim/evidence checks.
    # 1) Filesystem path claims (absolute paths) -> verify existence.
    path_pattern = re.compile(r"(/Users/[^\s,;:)\]]+)")
    raw_paths = path_pattern.findall(assistant_output)
    mentioned_paths = sorted(set(p.rstrip(".,;:!?`'\"") for p in raw_paths))[:20]
    path_unverified = 0
    for path in mentioned_paths:
        try:
            _ensure_tool_allowed(_POLICY_BUNDLE, _VERIFY_ROLE, "file_exists")
            _ensure_path_allowed(_POLICY_BUNDLE, _VERIFY_ROLE, path, "read")
            raw = _file_exists(path)
            tool_trace.append({"tool": "file_exists", "args": {"path": path}, "status": "ok"})
            parsed = json.loads(raw)
            exists = bool(parsed.get("exists"))
            evidence.append(
                {
                    "id": f"ev_file_{len(evidence)+1}",
                    "source_type": "file",
                    "source": path,
                    "excerpt": f"exists={exists}",
                    "timestamp": _now_iso(),
                    "hash": parsed.get("content_hash"),
                }
            )
            if not exists:
                path_unverified += 1
                findings.append(
                    {
                        "severity": "medium",
                        "type": "unverified_claim",
                        "claim": path,
                        "reason": "Assistant referenced a filesystem path that could not be verified on disk.",
                        "evidence_refs": [evidence[-1]["id"]],
                    }
                )
        except _PermissionError as exc:
            path_unverified += 1
            tool_trace.append(
                {"tool": "file_exists", "args": {"path": path}, "status": "blocked", "error": str(exc)}
            )
            findings.append(
                {
                    "severity": "high",
                    "type": "permission_denied",
                    "claim": path,
                    "reason": str(exc),
                    "evidence_refs": [],
                }
            )
        except Exception as exc:
            tool_trace.append(
                {"tool": "file_exists", "args": {"path": path}, "status": "error", "error": str(exc)}
            )
            findings.append(
                {
                    "severity": "medium",
                    "type": "file_check_error",
                    "claim": path,
                    "reason": str(exc),
                    "evidence_refs": [],
                }
            )

    if mentioned_paths:
        checks_run.append(
            {
                "check_id": "path_claims",
                "status": "unverified" if path_unverified else "pass",
                "reason": f"checked {len(mentioned_paths)} absolute path claims",
            }
        )
    else:
        checks_run.append(
            {
                "check_id": "path_claims",
                "status": "pass",
                "reason": "no absolute path claims detected",
            }
        )

    # 2) Conversation evidence probe through witness search for key terms.
    # This keeps truth_v2 orchestrated across verification services.
    keyword_terms = [w for w in re.findall(r"[A-Za-z0-9_-]{4,}", question.lower()) if w not in {"what", "when", "where", "this", "that", "with", "from", "have", "will"}]
    keyword_terms = keyword_terms[:4]
    if keyword_terms:
        keyword_query = " ".join(keyword_terms)
        try:
            _ensure_tool_allowed(_POLICY_BUNDLE, _VERIFY_ROLE, "search_evidence")
            raw = _search_evidence(keyword_query, "any", 0, 999999, 3)
            tool_trace.append({"tool": "search_evidence", "args": {"keywords": keyword_query}, "status": "ok"})
            parsed = json.loads(raw)
            match_count = int(parsed.get("total_matches", 0))
            evidence.append(
                {
                    "id": f"ev_witness_{len(evidence)+1}",
                    "source_type": "tool",
                    "source": "mcp-witness.search_evidence",
                    "excerpt": f"keywords={keyword_query} matches={match_count}",
                    "timestamp": _now_iso(),
                }
            )
            checks_run.append(
                {
                    "check_id": "conversation_evidence_probe",
                    "status": "pass",
                    "reason": f"witness searched with {match_count} matches",
                }
            )
        except _PermissionError as exc:
            tool_trace.append(
                {"tool": "search_evidence", "args": {"keywords": keyword_query}, "status": "blocked", "error": str(exc)}
            )
            checks_run.append(
                {
                    "check_id": "conversation_evidence_probe",
                    "status": "blocked",
                    "reason": f"permissions denied: {exc}",
                }
            )
        except Exception as exc:
            tool_trace.append(
                {"tool": "search_evidence", "args": {"keywords": keyword_query}, "status": "error", "error": str(exc)}
            )
            checks_run.append(
                {
                    "check_id": "conversation_evidence_probe",
                    "status": "unverified",
                    "reason": f"witness search unavailable: {exc}",
                }
            )

    # Freshness-sensitive prompts should be blocked until web-backed truth checks are wired.
    # Keep this intentionally narrow to avoid false positives on local/system questions.
    q = question.lower()
    freshness_phrases = (
        "latest ",
        "most recent",
        "as of today",
        "today's",
        "current price",
        "pricing",
        "release date",
        "current version",
        "is it available",
        "availability",
        "breaking news",
        "stock price",
    )
    requires_freshness = any(token in q for token in freshness_phrases)
    if requires_freshness:
        checks_run.append(
            {
                "check_id": "freshness_web",
                "status": "blocked",
                "reason": "freshness-sensitive content requires web verifier plugin",
            }
        )
        findings.append(
            {
                "severity": "medium",
                "type": "freshness_not_verified",
                "claim": "",
                "reason": "Freshness-sensitive claim detected; web verification plugin not yet implemented.",
                "evidence_refs": [],
            }
        )
        return {
            "job_id": job_id,
            "domain": "truth",
            "overall_status": "blocked",
            "summary": "Truth v1 blocked: freshness-sensitive content requires web verification.",
            "checks_run": checks_run,
            "findings": findings,
            "evidence": evidence,
            "tool_trace": tool_trace,
            "verifier_version": "mcp-verify-orchestrator@v1",
            "policy_version": "v1",
            "timestamp": _now_iso(),
        }

    checks_run.append(
        {"check_id": "freshness_web", "status": "pass", "reason": "no freshness-sensitive markers detected"}
    )

    # Roll up final status from checks.
    statuses = [c.get("status", "pass") for c in checks_run]
    if "blocked" in statuses:
        overall_status = "blocked"
    elif "fail" in statuses:
        overall_status = "fail"
    elif "warn" in statuses or "unverified" in statuses:
        overall_status = "warn"
    else:
        overall_status = "pass"

    # Stage 3: enforce canonical fail-closed behavior for required truth checks.
    overall_status = _apply_fail_closed(
        _POLICY_BUNDLE,
        overall_status,
        required=True,
        has_exception_artifact=False,
    )

    summary = {
        "pass": "Truth v2 passed: deterministic checks succeeded.",
        "warn": "Truth v2 warning: non-blocking verification issues detected.",
        "blocked": "Truth v2 blocked: required verification could not complete.",
        "fail": "Truth v2 failed: one or more deterministic checks failed.",
    }[overall_status]

    if path_unverified:
        summary = (
            f"Truth v2 unverified: {path_unverified} claim(s) could not be verified. "
            "See verification findings for why each claim was unverified."
        )

    return {
        "job_id": job_id,
        "domain": "truth",
        "overall_status": overall_status,
        "summary": summary,
        "checks_run": checks_run,
        "findings": findings,
        "evidence": evidence,
        "tool_trace": tool_trace,
        "verifier_version": "mcp-verify-orchestrator@v1",
        "policy_version": "v1",
        "timestamp": _now_iso(),
    }


@server.tool()
def runtime_route_preview(request_json: str) -> str:
    """Preview Stage 3 routing decision using policy/v1 (deterministic, side-effect free).

    request_json:
      {
        "workflow_class": "code_change|mcp_tool|research_only|transcription|ui_change|ops_fix",
        "verdict": "pass|warn|fail|blocked|unverified",
        "required": true|false,
        "has_exception_artifact": true|false
      }
    """
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"status": "blocked", "error": f"Invalid request_json: {exc}"}, indent=2)

    workflow_class = str(request.get("workflow_class", "")).strip()
    verdict = str(request.get("verdict", "")).strip()
    required = bool(request.get("required", True))
    has_exception_artifact = bool(request.get("has_exception_artifact", False))

    try:
        effective_verdict = _apply_fail_closed(
            _POLICY_BUNDLE,
            verdict,
            required=required,
            has_exception_artifact=has_exception_artifact,
        )
        next_state = _next_state_for_verification(_POLICY_BUNDLE, workflow_class, effective_verdict)
    except Exception as exc:
        return json.dumps({"status": "blocked", "error": str(exc)}, indent=2)

    return json.dumps(
        {
            "status": "pass",
            "workflow_class": workflow_class,
            "input_verdict": verdict,
            "effective_verdict": effective_verdict,
            "next_state": next_state,
            "policy_version": "v1",
            "timestamp": _now_iso(),
        },
        indent=2,
    )


@server.tool()
def verify_run(request_json: str) -> str:
    """Run canonical verification contract (plugin implementation pending)."""
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError as exc:
        return json.dumps(
            {
                "job_id": "unknown",
                "domain": "unknown",
                "overall_status": "blocked",
                "summary": f"Invalid request_json: {exc}",
                "checks_run": [{"check_id": "request_parse", "status": "blocked", "reason": str(exc)}],
                "findings": [],
                "evidence": [],
                "tool_trace": [],
                "verifier_version": "mcp-verify-orchestrator@v1",
                "policy_version": "v1",
                "timestamp": _now_iso(),
            },
            indent=2,
        )

    try:
        _validate_verify_request(request)
    except _SchemaValidationError as exc:
        return json.dumps(
            {
                "job_id": str(request.get("job_id", "unknown")),
                "domain": str(request.get("domain", "unknown")),
                "overall_status": "blocked",
                "summary": f"Schema validation failed: {exc}",
                "checks_run": [{"check_id": "schema_validation", "status": "blocked", "reason": str(exc)}],
                "findings": [],
                "evidence": [],
                "tool_trace": [],
                "verifier_version": "mcp-verify-orchestrator@v1",
                "policy_version": "v1",
                "timestamp": _now_iso(),
            },
            indent=2,
        )
    except _SpecVersionError as exc:
        return json.dumps(
            {
                "job_id": str(request.get("job_id", "unknown")),
                "domain": str(request.get("domain", "unknown")),
                "overall_status": "blocked",
                "summary": f"Spec version mismatch: {exc}",
                "checks_run": [{"check_id": "spec_version", "status": "blocked", "reason": str(exc)}],
                "findings": [],
                "evidence": [],
                "tool_trace": [],
                "verifier_version": "mcp-verify-orchestrator@v1",
                "policy_version": "v1",
                "timestamp": _now_iso(),
            },
            indent=2,
        )

    job_id = request.get("job_id", "unknown")
    domain = request.get("domain", "truth")

    if domain not in ("truth", "plan", "research", "ui", "api", "custom"):
        return json.dumps(_blocked_result(job_id, domain, f"Unknown verification domain: {domain}"), indent=2)

    if domain == "truth":
        response = _truth_v1(job_id, request)
        try:
            _validate_verify_response(response)
        except _SchemaValidationError as exc:
            response = {
                "job_id": str(job_id),
                "domain": "truth",
                "overall_status": "blocked",
                "summary": f"Response schema validation failed: {exc}",
                "checks_run": [{"check_id": "response_schema", "status": "blocked", "reason": str(exc)}],
                "findings": [],
                "evidence": [],
                "tool_trace": [],
                "verifier_version": "mcp-verify-orchestrator@v1",
                "policy_version": "v1",
                "timestamp": _now_iso(),
            }
        return json.dumps(response, indent=2)

    # Stage 5: use verification backbone for non-truth domains.
    response = _VERIFICATION_BACKBONE.run(job_id, domain, request)
    try:
        _validate_verify_response(response)
    except _SchemaValidationError as exc:
        response = {
            "job_id": str(job_id),
            "domain": domain,
            "overall_status": "blocked",
            "summary": f"Response schema validation failed: {exc}",
            "checks_run": [{"check_id": "response_schema", "status": "blocked", "reason": str(exc)}],
            "findings": [],
            "evidence": [],
            "tool_trace": [],
            "verifier_version": "mcp-verify-orchestrator@v1",
            "policy_version": "v1",
            "timestamp": _now_iso(),
        }
    return json.dumps(response, indent=2)


if __name__ == "__main__":
    server.run(transport="stdio")

#!/usr/bin/env python3
"""Pure runtime orchestrator API used by MCP wrapper and local tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from runtime.permissions_guard import ensure_tool_allowed as _ensure_tool_allowed
from runtime.policy_engine import load_policy_bundle as _load_policy_bundle
from runtime.state_machine import RuntimeStateMachine

ROOT = Path(__file__).resolve().parents[1]
_POLICY_BUNDLE = _load_policy_bundle(ROOT)
_ROLE = "Orchestrator"
_SM = RuntimeStateMachine(ROOT)


def _error(message: str) -> str:
    return json.dumps({"status": "blocked", "error": message}, indent=2)


def _parse_json(name: str, payload: str) -> Dict[str, Any]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid {name}: expected JSON object")
    return data


def runtime_create_run(request_json: str) -> str:
    try:
        _ensure_tool_allowed(_POLICY_BUNDLE, _ROLE, "runtime.create_run")
        request = _parse_json("request_json", request_json)
        workflow_class = str(request.get("workflow_class", "")).strip()
        if not workflow_class:
            return _error("workflow_class is required")
        correlation_id = request.get("correlation_id")
        correlation_value = str(correlation_id).strip() if correlation_id is not None else None
        run = _SM.create_run(workflow_class, correlation_value or None)
        return json.dumps({"status": "pass", "run": asdict(run)}, indent=2)
    except Exception as exc:
        return _error(str(exc))


def runtime_step(request_json: str) -> str:
    try:
        _ensure_tool_allowed(_POLICY_BUNDLE, _ROLE, "runtime.step")
        request = _parse_json("request_json", request_json)
        run_id = str(request.get("run_id", "")).strip()
        event = str(request.get("event", "")).strip()
        data = request.get("data") or {}
        if not run_id:
            return _error("run_id is required")
        if not event:
            return _error("event is required")
        if not isinstance(data, dict):
            return _error("data must be a JSON object")

        run = _SM.load_run(run_id)
        transition = _SM.step(run, event, **data)
        run = _SM.load_run(run_id)
        return json.dumps({"status": "pass", "transition": asdict(transition), "run": asdict(run)}, indent=2)
    except Exception as exc:
        return _error(str(exc))


def runtime_get_run(request_json: str) -> str:
    try:
        _ensure_tool_allowed(_POLICY_BUNDLE, _ROLE, "runtime.get_run")
        request = _parse_json("request_json", request_json)
        run_id = str(request.get("run_id", "")).strip()
        if not run_id:
            return _error("run_id is required")
        run = _SM.load_run(run_id)
        return json.dumps({"status": "pass", "run": asdict(run)}, indent=2)
    except Exception as exc:
        return _error(str(exc))


def runtime_tail_transitions(request_json: str) -> str:
    try:
        _ensure_tool_allowed(_POLICY_BUNDLE, _ROLE, "runtime.tail_transitions")
        request = _parse_json("request_json", request_json)
        run_id = str(request.get("run_id", "")).strip()
        limit = int(request.get("limit", 20))
        if not run_id:
            return _error("run_id is required")
        if limit < 1:
            return _error("limit must be >= 1")
        log_path = ROOT / "runtime" / "state" / "logs" / f"{run_id}.jsonl"
        if not log_path.exists():
            return json.dumps({"status": "pass", "run_id": run_id, "transitions": []}, indent=2)
        lines = [line for line in log_path.read_text().splitlines() if line.strip()]
        rows = [json.loads(line) for line in lines[-limit:]]
        return json.dumps({"status": "pass", "run_id": run_id, "transitions": rows}, indent=2)
    except Exception as exc:
        return _error(str(exc))


def runtime_skip_proof(request_json: str) -> str:
    """Skip the verification/proof phase for a run and advance it to completed.

    Request fields:
        run_id  (str, required)  — the run to skip proof on
        reason  (str, optional)  — human-readable justification; defaults to
                                   "skip_proof requested"

    The run must be in an eligible state (implementation, verifying,
    build_rework, blocked_evidence, blocked).  The transition is recorded in
    the audit log with ``event=skip_proof`` and the run's ``skip_proof``,
    ``proof_skipped_at``, and ``proof_skip_reason`` fields are populated.
    """
    try:
        _ensure_tool_allowed(_POLICY_BUNDLE, _ROLE, "runtime.skip_proof")
        request = _parse_json("request_json", request_json)
        run_id = str(request.get("run_id", "")).strip()
        reason = str(request.get("reason", "")).strip() or "skip_proof requested"
        if not run_id:
            return _error("run_id is required")
        run = _SM.load_run(run_id)
        transition = _SM.step(run, "skip_proof", reason=reason)
        run = _SM.load_run(run_id)
        return json.dumps(
            {
                "status": "pass",
                "skip_proof": True,
                "proof_skipped_at": run.proof_skipped_at,
                "proof_skip_reason": run.proof_skip_reason,
                "transition": asdict(transition),
                "run": asdict(run),
            },
            indent=2,
        )
    except Exception as exc:
        return _error(str(exc))


def runtime_heartbeat(request_json: str) -> str:
    try:
        _ensure_tool_allowed(_POLICY_BUNDLE, _ROLE, "runtime.heartbeat")
        request = _parse_json("request_json", request_json)
        run_id = str(request.get("run_id", "")).strip()
        if not run_id:
            return _error("run_id is required")
        run = _SM.load_run(run_id)
        _SM.heartbeat(run)
        run = _SM.load_run(run_id)
        return json.dumps({"status": "pass", "run": asdict(run)}, indent=2)
    except Exception as exc:
        return _error(str(exc))

#!/usr/bin/env python3
"""mcp-workflow-observer — Read-only live progress visibility for CCUI.

Exposes workflow/run state without touching execution logic.
Data sources:
  - runtime/state/<run_id>.json          (live RunState)
  - runtime/state/logs/<run_id>.jsonl    (transition log)
  - out/<correlation_id>/run_state.json  (completed run summary)
  - out/<correlation_id>/manifest.json   (emitted artifacts)
  - out/<correlation_id>/VerificationArtifact.json
  - out/<correlation_id>/proof.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

server = FastMCP("mcp-workflow-observer")

_ROOT = Path(__file__).parent
_STATE_DIR = _ROOT / "runtime" / "state"
_LOG_DIR = _STATE_DIR / "logs"
_OUT_DIR = _ROOT / "out"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl_tail(path: Path, limit: int) -> List[Dict[str, Any]]:
    """Return last `limit` JSON lines from a .jsonl file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
        return rows
    except Exception:
        return []


def _find_run_state_path(run_id: str) -> Optional[Path]:
    """Resolve live state file by run_id."""
    p = _STATE_DIR / f"{run_id}.json"
    return p if p.exists() else None


def _find_out_dir(correlation_id: str) -> Optional[Path]:
    """Find out/<correlation_id> dir."""
    p = _OUT_DIR / correlation_id
    return p if p.is_dir() else None


def _summarise_run_state(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract observer fields from a live RunState dict."""
    return {
        "run_id": data.get("run_id"),
        "correlation_id": data.get("correlation_id"),
        "workflow_class": data.get("workflow_class"),
        "current_state": data.get("current_state"),
        "previous_state": data.get("previous_state"),
        "is_terminal": data.get("is_terminal"),
        "blocked_reason": data.get("blocked_reason"),
        "last_reason": data.get("last_reason"),
        "transition_count": data.get("transition_count"),
        "updated_at": data.get("updated_at"),
        "last_heartbeat_at": data.get("last_heartbeat_at"),
        "heartbeat_missed": data.get("heartbeat_missed", 0),
    }


# ---------------------------------------------------------------------------
# Tool: observer_list_runs
# ---------------------------------------------------------------------------

@server.tool()
def observer_list_runs() -> str:
    """List all known runs: live (runtime/state/) and completed (out/).

    Returns JSON array of run summaries.
    """
    results: List[Dict[str, Any]] = []

    # Live runs from runtime/state/
    if _STATE_DIR.exists():
        for path in sorted(_STATE_DIR.glob("*.json")):
            data = _read_json(path)
            if data and "run_id" in data:
                results.append({
                    "source": "live",
                    "run_id": data.get("run_id"),
                    "correlation_id": data.get("correlation_id"),
                    "workflow_class": data.get("workflow_class"),
                    "current_state": data.get("current_state"),
                    "is_terminal": data.get("is_terminal"),
                    "updated_at": data.get("updated_at"),
                })

    # Completed runs from out/
    seen_corr = {r.get("correlation_id") for r in results}
    if _OUT_DIR.exists():
        for d in sorted(_OUT_DIR.iterdir()):
            if not d.is_dir():
                continue
            rs_path = d / "run_state.json"
            rs = _read_json(rs_path)
            if rs:
                corr = rs.get("correlation_id", d.name)
                if corr in seen_corr:
                    continue
                results.append({
                    "source": "completed",
                    "correlation_id": corr,
                    "current_state": rs.get("current_state"),
                    "last_transition_at": rs.get("last_transition_at"),
                })

    return json.dumps({"runs": results}, indent=2)


# ---------------------------------------------------------------------------
# Tool: observer_get_run
# ---------------------------------------------------------------------------

@server.tool()
def observer_get_run(run_id: str) -> str:
    """Get full live status for a run by run_id or correlation_id.

    Returns: current_state, workflow_class, actor hint, blocked_reason,
             recent transitions (last 5), verification state if present.
    """
    # Try live state first
    live_path = _find_run_state_path(run_id)
    live_data: Optional[Dict[str, Any]] = None
    if live_path:
        live_data = _read_json(live_path)

    # Try out/ dir by correlation_id if no live state
    out_path = _find_out_dir(run_id)

    # If run_id is actually a correlation_id, scan live states
    if not live_data and not out_path:
        if _STATE_DIR.exists():
            for p in _STATE_DIR.glob("*.json"):
                d = _read_json(p)
                if d and d.get("correlation_id") == run_id:
                    live_data = d
                    break

    result: Dict[str, Any] = {}

    if live_data:
        result["status"] = _summarise_run_state(live_data)
        # Add last 5 transitions from log
        log_path = _LOG_DIR / f"{live_data.get('run_id', run_id)}.jsonl"
        result["recent_transitions"] = _read_jsonl_tail(log_path, 5)

    # Overlay with out/ artifacts if available
    corr_id = (live_data or {}).get("correlation_id", run_id)
    out_dir = _find_out_dir(corr_id) or _find_out_dir(run_id)
    if out_dir:
        rs = _read_json(out_dir / "run_state.json")
        if rs and not live_data:
            result["status"] = {
                "correlation_id": rs.get("correlation_id"),
                "current_state": rs.get("current_state"),
                "last_transition_at": rs.get("last_transition_at"),
            }
            result["recent_transitions"] = (rs.get("transitions") or [])[-5:]

        proof = _read_json(out_dir / "proof.json")
        if proof:
            result["verification_state"] = {
                "verdict": proof.get("verdict"),
                "overall_status": proof.get("overall_status"),
                "evidence_count": proof.get("evidence_count"),
                "criteria_count": proof.get("criteria_count"),
                "all_evidence_resolved": proof.get("all_evidence_resolved"),
            }

        manifest = _read_json(out_dir / "manifest.json")
        if manifest:
            result["artifacts"] = [a.get("file") for a in manifest.get("artifacts", [])]

    if not result:
        return json.dumps({"error": f"No run found for id={run_id!r}"})

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool: observer_tail_events
# ---------------------------------------------------------------------------

@server.tool()
def observer_tail_events(run_id: str, limit: int = 10) -> str:
    """Return the last N transition events for a run.

    Reads from runtime/state/logs/<run_id>.jsonl (live) or
    out/<correlation_id>/run_state.json transitions array (completed).
    """
    limit = max(1, min(limit, 100))

    # Live transition log
    log_path = _LOG_DIR / f"{run_id}.jsonl"
    if log_path.exists():
        events = _read_jsonl_tail(log_path, limit)
        return json.dumps({"run_id": run_id, "source": "live_log", "events": events}, indent=2)

    # Scan live states for correlation_id match
    if _STATE_DIR.exists():
        for p in _STATE_DIR.glob("*.json"):
            d = _read_json(p)
            if d and d.get("correlation_id") == run_id:
                actual_run_id = d.get("run_id", run_id)
                log_path2 = _LOG_DIR / f"{actual_run_id}.jsonl"
                if log_path2.exists():
                    events = _read_jsonl_tail(log_path2, limit)
                    return json.dumps({"run_id": actual_run_id, "source": "live_log", "events": events}, indent=2)

    # Fallback: out/ run_state transitions
    out_dir = _find_out_dir(run_id)
    if out_dir:
        rs = _read_json(out_dir / "run_state.json")
        if rs:
            transitions = (rs.get("transitions") or [])[-limit:]
            return json.dumps({"correlation_id": run_id, "source": "run_state", "events": transitions}, indent=2)

    return json.dumps({"error": f"No event log found for id={run_id!r}"})


# ---------------------------------------------------------------------------
# Tool: observer_get_artifacts
# ---------------------------------------------------------------------------

@server.tool()
def observer_get_artifacts(correlation_id: str) -> str:
    """Return the manifest of emitted artifacts for a completed run."""
    out_dir = _find_out_dir(correlation_id)
    if not out_dir:
        return json.dumps({"error": f"No output directory for correlation_id={correlation_id!r}"})

    manifest = _read_json(out_dir / "manifest.json")
    if manifest:
        return json.dumps(manifest, indent=2)

    # Fallback: list files in out dir
    files = [f.name for f in sorted(out_dir.iterdir()) if f.is_file()]
    return json.dumps({"correlation_id": correlation_id, "files": files}, indent=2)


# ---------------------------------------------------------------------------
# Tool: observer_get_verification
# ---------------------------------------------------------------------------

@server.tool()
def observer_get_verification(correlation_id: str) -> str:
    """Return verification state for a run: proof.json + VerificationArtifact summary."""
    out_dir = _find_out_dir(correlation_id)
    if not out_dir:
        return json.dumps({"error": f"No output directory for correlation_id={correlation_id!r}"})

    result: Dict[str, Any] = {}

    proof = _read_json(out_dir / "proof.json")
    if proof:
        result["proof"] = proof

    va = _read_json(out_dir / "VerificationArtifact.json")
    if va:
        checks = va.get("checks", [])
        result["verification_artifact"] = {
            "overall_status": va.get("overall_status"),
            "checks_run": len(checks),
            "checks_summary": [
                {
                    "check_id": c.get("check_id"),
                    "status": c.get("status"),
                    "reason": c.get("reason"),
                }
                for c in checks[:20]  # cap for readability
            ],
        }

    if not result:
        return json.dumps({"error": f"No verification data for correlation_id={correlation_id!r}"})

    return json.dumps(result, indent=2)


if __name__ == "__main__":
    server.run(transport="stdio")

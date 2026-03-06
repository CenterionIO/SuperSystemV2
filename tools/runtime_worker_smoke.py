#!/usr/bin/env python3
"""Smoke check for runtime worker heartbeat/stall handling."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/Users/ai/SuperSystemV2")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.orchestrator_api import runtime_create_run, runtime_get_run, runtime_step
from runtime.state_machine import RuntimeStateMachine
from runtime.worker import RuntimeWorker


def _obj(payload: str) -> dict:
    return json.loads(payload)


def main() -> int:
    sm = RuntimeStateMachine(ROOT)
    worker = RuntimeWorker(ROOT)

    created = _obj(runtime_create_run(json.dumps({"workflow_class": "code_change", "correlation_id": "corr-worker-smoke"})))
    assert created["status"] == "pass"
    run_id = created["run"]["run_id"]

    _obj(runtime_step(json.dumps({"run_id": run_id, "event": "operator_request_valid"})))
    _obj(runtime_step(json.dumps({"run_id": run_id, "event": "classified"})))
    _obj(runtime_step(json.dumps({"run_id": run_id, "event": "verify_plan_build", "data": {"verdict": "pass", "required": True}})))

    # Force stale heartbeat and ensure worker routes to blocked_platform.
    run = sm.load_run(run_id)
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=200)
    run.last_heartbeat_at = stale_at.isoformat().replace("+00:00", "Z")
    sm.persist_run(run)

    transitions = worker.process_once()
    assert transitions, "expected worker to apply stalled-run transition"
    run_after_stall = _obj(runtime_get_run(json.dumps({"run_id": run_id})))
    assert run_after_stall["run"]["current_state"] == "blocked_platform"

    # If still stalled in blocked_platform, worker escalates.
    transitions2 = worker.process_once()
    assert transitions2, "expected escalation transition for blocked_platform stall"
    run_after_escalation = _obj(runtime_get_run(json.dumps({"run_id": run_id})))
    assert run_after_escalation["run"]["current_state"] == "escalation"
    assert run_after_escalation["run"]["is_terminal"] is True

    print("Stage 4 runtime worker smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

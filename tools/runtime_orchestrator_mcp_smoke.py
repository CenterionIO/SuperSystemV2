#!/usr/bin/env python3
"""Smoke check for Stage 4 MCP runtime orchestrator tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/Users/ai/SuperSystemV2")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.orchestrator_api import (
    runtime_create_run,
    runtime_get_run,
    runtime_heartbeat,
    runtime_step,
    runtime_tail_transitions,
)


def _obj(payload: str) -> dict:
    return json.loads(payload)


def main() -> int:
    created = _obj(runtime_create_run(json.dumps({"workflow_class": "code_change", "correlation_id": "corr-mcp-stage4"})))
    assert created["status"] == "pass"
    run_id = created["run"]["run_id"]

    assert _obj(runtime_step(json.dumps({"run_id": run_id, "event": "operator_request_valid"})))["status"] == "pass"
    assert _obj(runtime_step(json.dumps({"run_id": run_id, "event": "classified"})))["status"] == "pass"
    assert _obj(
        runtime_step(
            json.dumps(
                {
                    "run_id": run_id,
                    "event": "verify_plan_build",
                    "data": {"verdict": "pass", "required": True},
                }
            )
        )
    )["status"] == "pass"
    assert _obj(runtime_step(json.dumps({"run_id": run_id, "event": "build_report_submitted"})))["status"] == "pass"
    done = _obj(
        runtime_step(
            json.dumps(
                {
                    "run_id": run_id,
                    "event": "verify_overall",
                    "data": {"verdict": "pass", "required": True},
                }
            )
        )
    )
    assert done["status"] == "pass"
    assert done["run"]["current_state"] == "completed"

    loaded = _obj(runtime_get_run(json.dumps({"run_id": run_id})))
    assert loaded["status"] == "pass"
    assert loaded["run"]["correlation_id"] == "corr-mcp-stage4"
    hb = _obj(runtime_heartbeat(json.dumps({"run_id": run_id})))
    assert hb["status"] == "pass"
    assert hb["run"]["heartbeat_missed"] == 0

    tail = _obj(runtime_tail_transitions(json.dumps({"run_id": run_id, "limit": 10})))
    assert tail["status"] == "pass"
    assert len(tail["transitions"]) >= 5

    print("Stage 4 runtime orchestrator MCP smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stage 4 smoke check for runtime state-machine skeleton."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/Users/ai/SuperSystemV2")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.state_machine import RuntimeStateMachine


def _assert_code_change_flow(sm: RuntimeStateMachine) -> None:
    run = sm.create_run("code_change", correlation_id="corr-stage4-code-change")
    sm.step(run, "operator_request_valid")
    sm.step(run, "classified")
    sm.step(run, "verify_plan_build", verdict="pass", required=True)
    sm.step(run, "build_report_submitted")
    sm.step(run, "verify_overall", verdict="pass", required=True)
    assert run.current_state == "completed"
    assert run.is_terminal is True


def _assert_research_warn_block(sm: RuntimeStateMachine) -> None:
    run = sm.create_run("research_only", correlation_id="corr-stage4-research")
    sm.step(run, "operator_request_valid")
    sm.step(run, "classified")
    sm.step(run, "verify_research_plan", verdict="warn", required=True, has_exception_artifact=False)
    assert run.current_state == "blocked_evidence"


def _assert_retry_cap(sm: RuntimeStateMachine) -> None:
    run = sm.create_run("code_change", correlation_id="corr-stage4-loop-cap")
    sm.step(run, "operator_request_valid")
    sm.step(run, "classified")
    for _ in range(2):
        sm.step(run, "verify_plan_build", verdict="fail", required=True)
        sm.step(run, "planner_patch_submitted")
    # Third verification_fail exceeds retry cap (2) and escalates.
    sm.step(run, "verify_plan_build", verdict="fail", required=True)
    assert run.current_state == "escalation"
    assert run.is_terminal is True


def main() -> int:
    sm = RuntimeStateMachine(ROOT)
    _assert_code_change_flow(sm)
    _assert_research_warn_block(sm)
    _assert_retry_cap(sm)
    print("Stage 4 runtime state-machine smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

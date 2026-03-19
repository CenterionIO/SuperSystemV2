#!/usr/bin/env python3
"""Stage 4 runtime state-machine skeleton.

Deterministic, policy-driven executor with persisted state snapshots.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from runtime.policy_engine import (
    PolicyBundle,
    apply_fail_closed,
    class_route,
    load_policy_bundle,
    normalize_status,
)

STATE_MACHINE_VERSION = "v1"
TERMINAL_STATES = {"completed", "completed_with_warnings", "escalation"}
DEFAULT_LOOP_CONTROLS = {
    "max_iterations_per_phase": {
        "research": 3,
        "planning": 5,
        "implementation": 8,
        "verifying": 5,
        "build_rework": 3,
        "research_rework": 2,
        "plan_rework": 2,
    },
    "retry_caps_by_error_type": {
        "verification_fail": 2,
        "plan_blocker": 3,
        "workflow_error": 3,
        "platform_error": 3,
    },
    "heartbeat_policy": {
        "interval_seconds": 30,
        "stall_threshold_missed_beats": 3,
        "on_stall": "blocked_platform",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class RunState:
    run_id: str
    correlation_id: str
    workflow_class: str
    current_state: str
    previous_state: Optional[str]
    policy_version: str
    state_machine_version: str
    created_at: str
    updated_at: str
    state_entry_counts: Dict[str, int] = field(default_factory=dict)
    retry_counts: Dict[str, int] = field(default_factory=dict)
    transition_count: int = 0
    last_reason: str = ""
    blocked_reason: Optional[str] = None
    is_terminal: bool = False
    last_heartbeat_at: str = ""
    heartbeat_missed: int = 0
    skip_proof: bool = False
    proof_skipped_at: Optional[str] = None
    proof_skip_reason: str = ""


@dataclass
class TransitionRecord:
    run_id: str
    correlation_id: str
    workflow_class: str
    from_state: str
    to_state: str
    event: str
    reason: str
    timestamp: str
    policy_version: str
    state_machine_version: str


class RuntimeStateMachine:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.bundle: PolicyBundle = load_policy_bundle(root_dir)
        self.loop_controls = DEFAULT_LOOP_CONTROLS

        self.state_dir = root_dir / "runtime" / "state"
        self.log_dir = self.state_dir / "logs"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self, workflow_class: str, correlation_id: Optional[str] = None) -> RunState:
        class_route(self.bundle, workflow_class)
        now = _now_iso()
        run = RunState(
            run_id=str(uuid4()),
            correlation_id=correlation_id or str(uuid4()),
            workflow_class=workflow_class,
            current_state="intake",
            previous_state=None,
            policy_version=str(self.bundle.routing_policy.get("version", "v1")),
            state_machine_version=STATE_MACHINE_VERSION,
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
            state_entry_counts={"intake": 1},
        )
        self.persist_run(run)
        return run

    def step(self, run: RunState, event: str, **data: Any) -> TransitionRecord:
        if run.is_terminal:
            raise ValueError(f"Run {run.run_id} is terminal at state={run.current_state}")

        from_state = run.current_state
        to_state, reason = self._resolve_transition(run, event, data)
        run.previous_state = from_state
        run.current_state = to_state
        run.updated_at = _now_iso()
        run.transition_count += 1
        run.last_reason = reason
        run.blocked_reason = reason if to_state.startswith("blocked") else None
        run.state_entry_counts[to_state] = run.state_entry_counts.get(to_state, 0) + 1
        run.is_terminal = to_state in TERMINAL_STATES

        cap_breach = self._enforce_iteration_cap(run, to_state)
        if cap_breach:
            to_state = "escalation"
            run.previous_state = run.current_state
            run.current_state = "escalation"
            run.updated_at = _now_iso()
            run.transition_count += 1
            run.last_reason = cap_breach
            run.is_terminal = True
            run.state_entry_counts["escalation"] = run.state_entry_counts.get("escalation", 0) + 1
            record = TransitionRecord(
                run_id=run.run_id,
                correlation_id=run.correlation_id,
                workflow_class=run.workflow_class,
                from_state=from_state,
                to_state="escalation",
                event=event,
                reason=cap_breach,
                timestamp=run.updated_at,
                policy_version=run.policy_version,
                state_machine_version=run.state_machine_version,
            )
        else:
            record = TransitionRecord(
                run_id=run.run_id,
                correlation_id=run.correlation_id,
                workflow_class=run.workflow_class,
                from_state=from_state,
                to_state=to_state,
                event=event,
                reason=reason,
                timestamp=run.updated_at,
                policy_version=run.policy_version,
                state_machine_version=run.state_machine_version,
            )

        self.persist_transition(record)
        self.persist_run(run)
        return record

    def heartbeat(self, run: RunState) -> None:
        now = _now_iso()
        run.last_heartbeat_at = now
        run.heartbeat_missed = 0
        run.updated_at = now
        self.persist_run(run)

    def is_stalled(self, run: RunState, now_utc: Optional[datetime] = None) -> bool:
        if run.is_terminal:
            return False
        heartbeat_policy = self.loop_controls.get("heartbeat_policy", {})
        interval = int(heartbeat_policy.get("interval_seconds", 30))
        threshold = int(heartbeat_policy.get("stall_threshold_missed_beats", 3))
        if not run.last_heartbeat_at:
            return False
        try:
            last = datetime.fromisoformat(run.last_heartbeat_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        now = now_utc or datetime.now(timezone.utc)
        elapsed = (now - last).total_seconds()
        return elapsed > (interval * threshold)

    def load_run(self, run_id: str) -> RunState:
        path = self.state_dir / f"{run_id}.json"
        payload = json.loads(path.read_text())
        return RunState(**payload)

    def persist_run(self, run: RunState) -> None:
        path = self.state_dir / f"{run.run_id}.json"
        path.write_text(json.dumps(asdict(run), indent=2) + "\n")

    def persist_transition(self, transition: TransitionRecord) -> None:
        path = self.log_dir / f"{transition.run_id}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(transition)) + "\n")

    def _resolve_transition(self, run: RunState, event: str, data: Dict[str, Any]) -> tuple[str, str]:
        if event == "platform_error":
            retry_cap_reason = self._increment_retry(run, "platform_error")
            if retry_cap_reason:
                return "escalation", retry_cap_reason
            return "blocked_platform", "platform_error"

        route = class_route(self.bundle, run.workflow_class)
        current = run.current_state

        if current == "intake" and event == "operator_request_valid":
            return "classify", "intake accepted"

        if current == "classify" and event == "classified":
            next_phase = route["normal_flow"][2]
            return next_phase, f"classified->{next_phase}"

        if current == "research" and event == "verify_research_plan":
            return self._resolve_verification_result(run, data, pass_state="planning", fail_state="research_rework")

        if current == "research_rework" and event == "research_patch_submitted":
            return "research", "research patch submitted"

        if current == "planning" and event == "verify_plan_build":
            return self._resolve_verification_result(run, data, pass_state="implementation", fail_state="plan_rework")

        if current == "plan_rework" and event == "planner_patch_submitted":
            return "planning", "plan patch submitted"

        if current == "implementation" and event == "build_report_submitted":
            return "verifying", "build report submitted"

        if current == "implementation" and event == "plan_blocker":
            retry_cap_reason = self._increment_retry(run, "plan_blocker")
            if retry_cap_reason:
                return "escalation", retry_cap_reason
            return "blocked", "plan blocker"

        if current == "verifying" and event == "verify_overall":
            verdict = str(data.get("verdict", "blocked"))
            if verdict == "warn_optional_only":
                return "completed_with_warnings", "optional-only warnings"
            return self._resolve_verification_result(
                run,
                data,
                pass_state="completed",
                fail_state=route["rework_routes"]["verification_fail"],
            )

        if event == "skip_proof":
            SKIP_PROOF_ELIGIBLE = {
                "implementation", "verifying", "build_rework",
                "blocked_evidence", "blocked",
            }
            if current not in SKIP_PROOF_ELIGIBLE:
                return "blocked", f"skip_proof not allowed from state={current}"
            reason = str(data.get("reason", "skip_proof requested"))
            run.skip_proof = True
            run.proof_skipped_at = _now_iso()
            run.proof_skip_reason = reason
            return "completed", f"proof skipped: {reason}"

        if current == "build_rework" and event == "build_patch_submitted":
            return "implementation", "build patch submitted"

        if current == "blocked_evidence" and event == "missing_evidence_supplied":
            return "verifying", "evidence supplied"

        if current == "blocked" and event == "implementation_retry_approved":
            return "implementation", "retry approved"

        if current == "blocked" and event == "requires_user_exception":
            return "escalation", "user exception required"

        if current == "blocked_platform" and event == "recovery_health_pass":
            previous = run.previous_state or "implementation"
            if previous not in {"research", "planning", "implementation", "verifying", "build_rework", "blocked_evidence"}:
                previous = "implementation"
            return previous, f"platform recovered->{previous}"

        if current == "blocked_platform" and event == "recovery_failed_or_caps_exceeded":
            return "escalation", "platform recovery failed or caps exceeded"

        retry_cap_reason = self._increment_retry(run, "workflow_error")
        if retry_cap_reason:
            return "escalation", retry_cap_reason
        return "blocked", f"no transition for state={current} event={event}"

    def _resolve_verification_result(
        self,
        run: RunState,
        data: Dict[str, Any],
        *,
        pass_state: str,
        fail_state: str,
    ) -> tuple[str, str]:
        verdict = str(data.get("verdict", "blocked"))
        required = bool(data.get("required", True))
        has_exception_artifact = bool(data.get("has_exception_artifact", False))

        effective = apply_fail_closed(
            self.bundle,
            verdict,
            required=required,
            has_exception_artifact=has_exception_artifact,
        )

        if effective == "pass":
            return pass_state, "verification pass"
        if effective == "fail":
            retry_cap_reason = self._increment_retry(run, "verification_fail")
            if retry_cap_reason:
                return "escalation", retry_cap_reason
            return fail_state, "verification fail"
        return class_route(self.bundle, run.workflow_class)["blocked_evidence_route"], f"verification {normalize_status(verdict)}"

    def _increment_retry(self, run: RunState, error_type: str) -> Optional[str]:
        run.retry_counts[error_type] = run.retry_counts.get(error_type, 0) + 1
        cap = self.loop_controls["retry_caps_by_error_type"].get(error_type)
        if cap is not None and run.retry_counts[error_type] > cap:
            return f"retry cap exceeded for {error_type}"
        return None

    def _enforce_iteration_cap(self, run: RunState, state: str) -> Optional[str]:
        cap = self.loop_controls["max_iterations_per_phase"].get(state)
        if cap is None:
            return None
        count = run.state_entry_counts.get(state, 0)
        if count > cap:
            return f"iteration cap exceeded for {state}: {count}>{cap}"
        return None

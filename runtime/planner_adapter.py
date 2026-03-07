#!/usr/bin/env python3
"""Minimal deterministic Planner adapter for executable MVP golden flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class PlannerResult:
    execution_plan: Dict[str, Any]


def create_execution_plan(
    *,
    workflow_id: str,
    correlation_id: str,
    workflow_class: str,
    required_checks: List[str],
    goal: str = "",
) -> PlannerResult:
    if isinstance(goal, str) and any(token in goal.lower() for token in ("ambiguous", "plan_blocker")):
        return PlannerResult(
            execution_plan={
                "schema_version": "v1",
                "plan_blocker": True,
                "blocker_reason": "Planner detected ambiguous goal; clarification required.",
                "workflow_id": workflow_id,
                "correlation_id": correlation_id,
                "workflow_class": workflow_class,
            }
        )
    steps = []
    criteria = []
    for i, check in enumerate(required_checks, start=1):
        cid = f"crit_{i:03d}_{check}"
        criteria.append(
            {
                "criteria_id": cid,
                "check_type": check,
                "description": f"Satisfy {check}",
                "required": True,
            }
        )
        steps.append(
            {
                "step_id": f"step_{i:03d}",
                "description": f"Implement evidence for {check}",
                "criteria_ids": [cid],
                "depends_on": [],
                "required_tools": ["builder.simulated_write"],
            }
        )

    plan = {
        "schema_version": "v1",
        "plan_id": f"plan_{workflow_id}",
        "workflow_id": workflow_id,
        "correlation_id": correlation_id,
        "workflow_class": workflow_class,
        "autonomy_mode": "approve_final",
        "criteria_ids": [c["criteria_id"] for c in criteria],
        "steps": steps,
        "acceptance_criteria": criteria,
    }
    return PlannerResult(execution_plan=plan)

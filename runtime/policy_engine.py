#!/usr/bin/env python3
"""Runtime policy engine for Stage 3 wiring.

Loads Stage 2 policy bundle and provides deterministic helpers for:
- fail-closed verdict normalization
- workflow-class route lookup
- next-state decisions for verification outcomes
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from runtime.spec_loader import load_runtime_spec_bundle

CANONICAL_STATUSES = {"pass", "warn", "fail", "blocked"}


@dataclass(frozen=True)
class PolicyBundle:
    workflow_taxonomy: Dict[str, Any]
    routing_policy: Dict[str, Any]
    permissions_policy: Dict[str, Any]
    override_policy: Dict[str, Any]


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def load_policy_bundle(base_dir: Path) -> PolicyBundle:
    # Centralized spec loader enforces version pinning/fail-closed semantics.
    spec_bundle = load_runtime_spec_bundle(base_dir)
    policy = spec_bundle.policy
    return PolicyBundle(
        workflow_taxonomy=policy["workflow_taxonomy"],
        routing_policy=policy["routing_policy"],
        permissions_policy=policy["permissions_policy"],
        override_policy=policy["override_policy"],
    )


def normalize_status(status: str) -> str:
    """Map legacy statuses to canonical Task1 taxonomy."""
    s = (status or "").strip().lower()
    if s in CANONICAL_STATUSES:
        return s
    if s in {"unverified", "unknown", "n/a"}:
        return "warn"
    return "blocked"


def apply_fail_closed(
    bundle: PolicyBundle,
    status: str,
    *,
    required: bool,
    has_exception_artifact: bool = False,
) -> str:
    """Apply fail-closed semantics from Stage 2 routing policy."""
    normalized = normalize_status(status)
    if not required:
        return normalized

    fc = bundle.routing_policy.get("fail_closed", {})
    required_warn_behavior = fc.get("required_warn_behavior", "blocked")
    required_missing_check_behavior = fc.get("required_missing_check_behavior", "blocked")
    requires_artifact = bool(fc.get("required_warn_exception_requires_artifact", True))

    if normalized == "warn":
        if has_exception_artifact and requires_artifact:
            return "warn"
        return required_warn_behavior

    if normalized not in CANONICAL_STATUSES:
        return required_missing_check_behavior

    return normalized


def class_route(bundle: PolicyBundle, workflow_class: str) -> Dict[str, Any]:
    classes = bundle.routing_policy.get("classes", {})
    if workflow_class not in classes:
        raise KeyError(f"Unknown workflow_class: {workflow_class}")
    return classes[workflow_class]


def next_state_for_verification(
    bundle: PolicyBundle,
    workflow_class: str,
    verdict: str,
) -> str:
    """Deterministic routing for verification result.

    - pass -> completed
    - fail -> class rework route (verification_fail)
    - warn/blocked -> blocked_evidence_route (fail-closed handled upstream)
    """
    route = class_route(bundle, workflow_class)
    effective = normalize_status(verdict)

    if effective == "pass":
        return "completed"
    if effective == "fail":
        return route["rework_routes"]["verification_fail"]
    return route["blocked_evidence_route"]

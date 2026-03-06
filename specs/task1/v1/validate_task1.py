#!/usr/bin/env python3
"""Task 1 gate validator (A-E) for SuperSystemV2/specs/task1/v1.

Gates:
- A: JSON Schema validation for all examples
- B: Ownership conformance for examples (deny-by-default, unknown path rejection)
- C: Orchestrator/Planner boundary checks
- D: Deterministic transition mapping checks from runtime stub
- E: Ownership coverage for all schema leaf fields
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

try:
    from jsonschema import Draft202012Validator
except Exception as exc:  # pragma: no cover
    print("ERROR: jsonschema is required. Run with /Users/ai/SuperSystemV2/.venv/bin/python", file=sys.stderr)
    print(f"Import error: {exc}", file=sys.stderr)
    sys.exit(2)


ROOT = Path(__file__).resolve().parent
SCHEMAS_DIR = ROOT / "schemas"
OWNERSHIP_DIR = ROOT / "ownership"
EXAMPLES_DIR = ROOT / "examples"
IO_FILE = ROOT / "orchestrator_planner_io.v1.json"
RUNTIME_FILE = ROOT / "runtime_state_machine_stub.v1.yaml"


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def collect_schema_paths(schema: Dict[str, Any], base: str = "") -> Tuple[Set[str], Set[str]]:
    """Return (all_node_paths, leaf_paths) in JSON Pointer + [] wildcard format."""
    node_paths: Set[str] = set()
    leaf_paths: Set[str] = set()

    schema_type = schema.get("type")

    if base:
        node_paths.add(base)

    if schema_type == "object":
        props = schema.get("properties", {})
        if not props:
            if base:
                leaf_paths.add(base)
            return node_paths, leaf_paths
        for key, sub in props.items():
            child_base = f"{base}/{key}" if base else f"/{key}"
            child_nodes, child_leaves = collect_schema_paths(sub, child_base)
            node_paths |= child_nodes
            leaf_paths |= child_leaves
        return node_paths, leaf_paths

    if schema_type == "array":
        items = schema.get("items", {})
        child_base = f"{base}/[]" if base else "/[]"
        child_nodes, child_leaves = collect_schema_paths(items, child_base)
        node_paths |= child_nodes
        leaf_paths |= child_leaves
        return node_paths, leaf_paths

    # scalar or untyped fallback
    if base:
        leaf_paths.add(base)
    return node_paths, leaf_paths


def collect_example_leaf_paths(value: Any, base: str = "") -> Set[str]:
    leaves: Set[str] = set()
    if isinstance(value, dict):
        for key, sub in value.items():
            child = f"{base}/{key}" if base else f"/{key}"
            leaves |= collect_example_leaf_paths(sub, child)
        return leaves
    if isinstance(value, list):
        if not value:
            # Empty arrays still require ownership at container path.
            if base:
                leaves.add(base)
            return leaves
        for item in value:
            child = f"{base}/[]" if base else "/[]"
            leaves |= collect_example_leaf_paths(item, child)
        return leaves
    if base:
        leaves.add(base)
    return leaves


def gate_a_schema_validation(errors: List[str]) -> None:
    for schema_file in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        base = schema_file.name.replace(".schema.json", "")
        example_file = EXAMPLES_DIR / f"{base}.example.json"
        if not example_file.exists():
            errors.append(f"Gate A: missing example for schema {base}: {example_file}")
            continue

        schema = load_json(schema_file)
        example = load_json(example_file)
        validator = Draft202012Validator(schema)
        schema_errors = sorted(validator.iter_errors(example), key=lambda e: str(e.path))
        for err in schema_errors:
            loc = "/" + "/".join(str(p) for p in err.path)
            errors.append(f"Gate A: {base} example invalid at {loc}: {err.message}")


def gate_b_e_ownership(errors: List[str]) -> None:
    for schema_file in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        base = schema_file.name.replace(".schema.json", "")
        ownership_file = OWNERSHIP_DIR / f"{base}.ownership.json"
        example_file = EXAMPLES_DIR / f"{base}.example.json"

        if not ownership_file.exists():
            errors.append(f"Gate B/E: missing ownership file for {base}")
            continue
        if not example_file.exists():
            errors.append(f"Gate B/E: missing example file for {base}")
            continue

        schema = load_json(schema_file)
        ownership = load_json(ownership_file)
        example = load_json(example_file)

        if ownership.get("deny_by_default") is not True:
            errors.append(f"Gate B/E: {ownership_file.name} must set deny_by_default=true")
        if ownership.get("path_format") != "json-pointer-with-array-wildcard":
            errors.append(f"Gate B/E: {ownership_file.name} path_format mismatch")

        field_ownership = ownership.get("fieldOwnership", {})
        if not isinstance(field_ownership, dict) or not field_ownership:
            errors.append(f"Gate B/E: {ownership_file.name} fieldOwnership missing/empty")
            continue

        all_nodes, leaf_nodes = collect_schema_paths(schema)

        # Unknown ownership paths fail.
        for path in field_ownership.keys():
            if not path.startswith("/"):
                errors.append(f"Gate B: {ownership_file.name} non-canonical path (must start with '/'): {path}")
            # Canonical array wildcard segment must be standalone '/[]/' segment, not 'steps[]'.
            for seg in [s for s in path.split("/") if s]:
                if "[]" in seg and seg != "[]":
                    errors.append(
                        f"Gate B: {ownership_file.name} non-canonical array wildcard syntax at {path} "
                        "(use '/[]/' segments only)"
                    )
            if path not in all_nodes and path not in leaf_nodes:
                errors.append(f"Gate B: {ownership_file.name} has unknown path {path}")

        # E: every schema leaf must have ownership.
        for leaf in sorted(leaf_nodes):
            if leaf not in field_ownership:
                errors.append(f"Gate E: {ownership_file.name} missing ownership for schema leaf {leaf}")

        # B: every example leaf must resolve ownership.
        example_leaves = collect_example_leaf_paths(example)
        for leaf in sorted(example_leaves):
            # If example has empty array container leaf (e.g. /steps), allow ownership on that container.
            if leaf not in field_ownership and leaf not in all_nodes:
                errors.append(f"Gate B: {base} example leaf {leaf} not covered by ownership")

        # Ownership rule completeness.
        for path, rule in field_ownership.items():
            for k in ("writtenBy", "readableBy", "verifiedBy"):
                if k not in rule or not isinstance(rule[k], list) or not rule[k]:
                    errors.append(f"Gate B/E: {ownership_file.name} {path} missing non-empty {k}")


def gate_c_boundary(errors: List[str]) -> None:
    exec_ownership = load_json(OWNERSHIP_DIR / "ExecutionPlan.ownership.json").get("fieldOwnership", {})
    allowed_orchestrator_exec_paths = {
        "/workflow_id",
        "/correlation_id",
        "/workflow_class",
        "/autonomy_mode",
    }

    for path, rule in exec_ownership.items():
        writers = set(rule.get("writtenBy", []))
        if "Orchestrator" in writers and path not in allowed_orchestrator_exec_paths:
            errors.append(f"Gate C: Orchestrator writes non-routing ExecutionPlan path {path}")
        if "Planner" in writers and path in allowed_orchestrator_exec_paths:
            errors.append(f"Gate C: Planner writes routing-owned ExecutionPlan path {path}")

    io = load_json(IO_FILE)
    to_planner = set(io["orchestrator_to_planner"]["properties"].keys())
    from_planner = set(io["planner_to_orchestrator"]["properties"].keys())

    required_routing = {"workflow_id", "correlation_id", "workflow_class", "autonomy_mode"}
    missing = required_routing - to_planner
    if missing:
        errors.append(f"Gate C: orchestrator_to_planner missing routing fields: {sorted(missing)}")

    forbidden_from_planner = {"workflow_class", "autonomy_mode", "route", "routing", "routing_state", "next_state"}
    overlap = forbidden_from_planner & from_planner
    if overlap:
        errors.append(f"Gate C: planner_to_orchestrator contains forbidden routing mutation fields: {sorted(overlap)}")


def gate_d_transitions(errors: List[str]) -> None:
    text = RUNTIME_FILE.read_text()
    required_patterns = [
        "condition: verify_research_plan == pass",
        "condition: verify_research_plan == fail",
        "condition: verify_research_plan in [warn, blocked]",
        "condition: verify_plan_build == pass",
        "condition: verify_plan_build == fail",
        "condition: verify_plan_build in [warn, blocked]",
        "condition: verify_overall == pass",
        "condition: verify_overall == fail",
        "condition: verify_overall == warn_optional_only",
        "condition: verify_overall in [warn_required_present, blocked]",
        "loop_controls:",
        "max_iterations_per_phase:",
        "retry_caps_by_error_type:",
        "heartbeat_policy:",
    ]
    for pat in required_patterns:
        if pat not in text:
            errors.append(f"Gate D: missing transition mapping pattern: {pat}")
    if "* ->" in text:
        errors.append("Gate D: wildcard state transitions are not allowed")
    if "Return to state that was active before platform_error." in text:
        errors.append("Gate D: textual transition targets are not allowed; use explicit state IDs")


def main() -> int:
    errors: List[str] = []

    gate_a_schema_validation(errors)
    gate_b_e_ownership(errors)
    gate_c_boundary(errors)
    gate_d_transitions(errors)

    if errors:
        print("Task 1 gates: FAIL")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Task 1 gates: PASS")
    print("- Gate A: schema validation")
    print("- Gate B: ownership conformance")
    print("- Gate C: orchestrator/planner boundary")
    print("- Gate D: transition mapping")
    print("- Gate E: schema leaf ownership coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

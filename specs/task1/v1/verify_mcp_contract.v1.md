# Verify MCP Contract v1

## Scope
Canonical verification contract for workflow checks across Research, Plan, Build, and Runtime gates.

## Status Taxonomy (Locked)
- `pass`
- `warn`
- `fail`
- `blocked`

No additional runtime statuses are allowed.

## Fail-Closed Rules
1. Every required check must return `pass`.
2. Required check returning `warn` is treated as `blocked` unless explicit policy exception exists.
3. Any missing required check result is `blocked`.
4. If required evidence is missing or unreadable, result is `blocked`.

## Required Check Types
- `acceptance_criteria`
- `plan_build_alignment`
- `research_plan_alignment`
- `permissions_scope`
- `evidence_integrity`
- `freshness`

`freshness` is mandatory for time-sensitive claims/workflow classes.

## Input Contract (Conceptual)
- correlation_id
- workflow_id
- workflow_class
- autonomy_mode
- required_checks[]
- artifacts[]
- policy_snapshot_id

## Output Contract (Conceptual)
- verification_id
- checks[] (check_id, check_type, required, status, message, evidence_ids)
- overall_status
- fail_closed (boolean)
- blocker_reason

## Boundary Constraints
1. Verify MCP must not mutate plan/build artifacts.
2. Verify MCP can only emit verification artifacts and verdicts.
3. Verify MCP must produce deterministic check traces (machine-parsable).

## Ownership Lint Binding
- Field ownership maps are mandatory for all schema fields.
- Unknown field paths in ownership maps fail validation.
- Fields without ownership metadata fail authority-conformance gate.

## Field Path Standard
Use JSON Pointer with `[]` wildcard for arrays.
Examples:
- `/workflow_id`
- `/steps/[]/criteria_ids`
- `/checks/[]/status`

# Task 1 Completion Gates v1

## Gate 1: Authority Conformance
- Every schema field path must exist in paired ownership map.
- Ownership map must not reference unknown schema field paths.
- Every action-capable field must include `writtenBy`, `readableBy`, and `verifiedBy`.
- Ownership paths must use canonical JSON Pointer with standalone `[]` segments (`/steps/[]/field`).
- Non-canonical wildcard formats (for example `/steps[]/field`) fail.

## Gate 2: Boundary Integrity (Orchestrator vs Planner)
- Orchestrator artifacts cannot contain Planner-authored step fields.
- Planner artifacts cannot contain Orchestrator routing/state mutation fields.

## Gate 3: Schema and Transition Validity
- All example files validate against their schemas.
- State machine contains deterministic transition mapping with explicit rework routing:
  - `pass -> proceed`
  - `fail -> rework state`
  - `warn_required|blocked -> blocked_evidence/escalation path`
- State machine includes global loop controls:
  - max iterations per phase
  - retry caps by error type
  - heartbeat/stall policy

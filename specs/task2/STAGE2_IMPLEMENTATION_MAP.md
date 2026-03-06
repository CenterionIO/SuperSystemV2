# Stage 2 Implementation Map (Policy + Enforcement)

Scope: Convert Task 1 contracts into enforceable policy/routing behavior without expanding runtime complexity.

## Objectives

1. Implement policy-as-data for routing, permissions, autonomy, and verification requirements.
2. Bind policy decisions to runtime enforcement points (not prompt-only behavior).
3. Produce machine-checkable outputs that integrate with Task 1 gates/contracts.

## Inputs (from Task 1)

1. `specs/task1/v1/ROLE_AUTHORITY_MATRIX.md`
2. `specs/task1/v1/orchestrator_planner_io.v1.json`
3. `specs/task1/v1/schemas/*`
4. `specs/task1/v1/ownership/*`
5. `specs/task1/v1/verify_mcp_contract.v1.md`
6. `specs/task1/v1/runtime_state_machine_stub.v1.yaml`

## Stage 2 Deliverables

1. `policy/v1/workflow_taxonomy.json`
- Maps each `workflow_class` to:
  - required verification ladder
  - required evidence types
  - default autonomy mode
  - risk-tier defaults

2. `policy/v1/permissions_policy.json`
- Role-based allow/deny for tools
- Path scope policy
- Network scope policy
- Explicit deny defaults

3. `policy/v1/routing_policy.json`
- Deterministic route selection rules
- Rework routing rules (`fail -> plan_rework/build_rework`)
- Blocked evidence resume rules

4. `policy/v1/override_policy.json`
- Conflict precedence order
- Council override conditions
- Required override evidence and audit metadata

5. `policy/v1/policy_schema.json`
- JSON Schema for all policy files above.

6. `policy/v1/examples/*`
- One valid example policy bundle per workflow class (`code_change`, `mcp_tool`, `ui_change`).

7. `tools/validate_policy_v1.py`
- Lints policy bundle against `policy_schema.json`
- Verifies cross-file consistency (taxonomy x permissions x routing)
- Emits deterministic pass/fail report

## Execution Order

1. Author `policy_schema.json` first.
2. Author `workflow_taxonomy.json` and `routing_policy.json`.
3. Author `permissions_policy.json` and `override_policy.json`.
4. Add policy examples.
5. Implement `validate_policy_v1.py`.
6. Run validator and fix until clean pass.

## Stage 2 Gates

1. Gate P1: Policy Schema Validation
- All policy files validate against `policy_schema.json`.

2. Gate P2: Cross-Policy Consistency
- Every workflow class in taxonomy has routing and permission entries.
- Every required check type in taxonomy exists in Verify MCP contract check types.

3. Gate P3: Enforcement Completeness
- Every role/tool/path/network decision maps to an enforcement point.
- No allow rule exists without explicit owner role.

4. Gate P4: Fail-Closed Preservation
- No policy path allows required `warn` to bypass blocked behavior without explicit exception artifact requirements.

5. Gate P5: Boundary Preservation
- Policy must not grant Planner routing mutation authority.
- Policy must not grant Orchestrator plan authoring authority.

## Out of Scope (Stage 3)

1. Runtime engine changes beyond policy loading.
2. New MCP server behavior changes.
3. UI mode-toggle behavior changes.

## Exit Criteria

Stage 2 is complete when all P1-P5 gates pass and policy bundle can be consumed by runtime without schema or ownership conflicts.

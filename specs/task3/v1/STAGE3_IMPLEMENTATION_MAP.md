# Stage 3 Implementation Map (Runtime Wiring)

Status: in progress

## Scope

Wire Stage 2 policy bundle into runtime behavior.

## Implemented in this slice

1. Runtime policy engine module:
- `runtime/policy_engine.py`
- loads `policy/v1/*`
- canonical status normalization (`pass|warn|fail|blocked`)
- fail-closed application for required checks
- deterministic verification next-state routing by workflow class

2. Verify orchestrator wiring:
- `mcp_verify_orchestrator.py`
- removed legacy `unverified` output status in truth rollup
- applies fail-closed policy from Stage 2
- added `runtime_route_preview` tool for deterministic route simulation

3. Permissions enforcement at dispatch boundaries:
- `runtime/permissions_guard.py`
- `mcp_truth.py`: enforces VerifyMCP tool/path/network policy before each tool call
- `mcp_verify_orchestrator.py`: enforces VerifyMCP tool/path policy before evidence probes
- `policy/v1/permissions_policy.json`: includes concrete verifier dispatch tools

4. Smoke test:
- `tools/runtime_policy_smoke.py`

## Remaining Stage 3 items

1. Route policy engine into full workflow state machine executor (not just preview).
2. Add runtime gate logs with correlation IDs and policy snapshot IDs.
3. Add CI command aggregating Task1 + Stage2 + Stage3 smoke.

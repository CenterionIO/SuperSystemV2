# Stage 4 Runtime Skeleton

Status: in progress

## Implemented in this slice

1. Deterministic runtime executor
- `runtime/state_machine.py`
- Policy-driven transitions using `routing_policy.json`
- Fail-closed verdict handling via `runtime/policy_engine.py`
- Explicit transitions for rework, blocked evidence, blocked platform, and escalation

2. Loop and retry controls
- Phase iteration caps aligned to Task 1 stub defaults
- Retry caps for `verification_fail`, `plan_blocker`, `workflow_error`, `platform_error`

3. State persistence and transition logs
- Per-run snapshot: `runtime/state/<run_id>.json`
- Transition stream: `runtime/state/logs/<run_id>.jsonl`
- Every transition records `run_id`, `correlation_id`, `policy_version`, `state_machine_version`

4. Validation
- `tools/runtime_state_machine_smoke.py`
- Covers happy path, fail-closed warn-to-blocked path, and retry-cap escalation

5. MCP runtime endpoint
- `runtime/orchestrator_api.py` (pure API)
- `mcp_runtime_orchestrator.py` (MCP wrapper)
- Tools:
  - `runtime_create_run`
  - `runtime_step`
  - `runtime_get_run`
  - `runtime_tail_transitions`
- `tools/runtime_orchestrator_mcp_smoke.py` validates endpoint flow and persisted transition tail retrieval

6. Active worker loop
- `runtime/worker.py`
- Detects stalled runs via heartbeat policy and applies deterministic transitions:
  - `platform_error` when stalled in active states
  - `recovery_failed_or_caps_exceeded` when stalled while already in `blocked_platform`
- `tools/runtime_worker_smoke.py` validates stall -> `blocked_platform` -> `escalation`

7. Unified gate command
- `tools/run_all_gates.sh`
- Runs Task 1 + Stage 2 + Stage 3 + Stage 4 checks in one command

## Remaining Stage 4 items

1. Integrate worker loop execution into your process manager/CI runtime (script is implemented; scheduling is external).

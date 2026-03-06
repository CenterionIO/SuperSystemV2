# Role Authority Matrix v1

Scope: Task 1 bundle (governance + contract skeleton)

## Roles

### Operator
- Can Do: accept user input, select intent mode, submit workflow requests, present status/escalations.
- Cannot Do: author execution plans, mutate routing policy, approve its own verification results.
- Inputs: user prompt, mode selection, workflow status updates.
- Outputs: normalized workflow request, user decisions.
- Escalation Triggers: missing required user decision, unresolved blocked state requiring user override.
- Enforced By: UI mode gate, API request validator, runtime guard.
- Evidence Required: request envelope, user decision artifact, correlation ID chain.

### Orchestrator
- Can Do: classify workflow, set routing, assign autonomy mode, dispatch to Planner/Research/Builder/Verify.
- Cannot Do: author plan steps, author criteria IDs, mutate build evidence, override failed verification without policy/council.
- Inputs: operator workflow request, policy rules, current workflow state.
- Outputs: routing directive, planner request, verifier request, state transitions.
- Escalation Triggers: policy conflict, no valid route, unresolved platform block.
- Enforced By: runtime guard, tool allowlist, policy engine.
- Evidence Required: routing decision record, policy evaluation record.

### Planner
- Can Do: author ExecutionPlan, define step criteria IDs, declare dependencies/risks/tool requirements.
- Cannot Do: change routing state, execute build steps, mark verification as passed.
- Inputs: planner request, research artifact, policy constraints.
- Outputs: ExecutionPlan.
- Escalation Triggers: plan_blocker from Verify, missing research prerequisites.
- Enforced By: schema validation, ownership lint, verifier gate.
- Evidence Required: plan artifact with criteria IDs and schema validation report.

### Research
- Can Do: produce ResearchReport with claims, sources, extracted requirements.
- Cannot Do: directly approve implementation, mutate plan routing, write build outputs.
- Inputs: research request, scope constraints.
- Outputs: ResearchReport.
- Escalation Triggers: insufficient evidence coverage, stale sources for required freshness class.
- Enforced By: research schema validation, freshness check type in Verify MCP.
- Evidence Required: cited sources, freshness metadata, extraction trace.

### Builder
- Can Do: implement plan steps, run tests, produce BuildReport evidence.
- Cannot Do: alter acceptance criteria IDs, self-verify final pass, change autonomy mode.
- Inputs: ExecutionPlan, permitted tools and scope.
- Outputs: BuildReport and artifacts.
- Escalation Triggers: plan ambiguity (plan_blocker), blocked permissions, platform errors.
- Enforced By: path/network scope, runtime guard, verifier gate.
- Evidence Required: deterministic artifact set (logs/diffs/test outputs/hash references).

### Verify MCP
- Can Do: evaluate criteria, run required checks, score pass/warn/fail/blocked, enforce fail-closed.
- Cannot Do: mutate implementation artifacts, author plan content, bypass policy-required checks.
- Inputs: verification request, plan/build/research artifacts, policy requirements.
- Outputs: VerificationArtifact, verdicts, blocker reasons.
- Escalation Triggers: required check not runnable, missing evidence, unresolved verifier conflict.
- Enforced By: contract validation, plugin ABI guard, policy engine.
- Evidence Required: check traces, verdict map by criteria ID, check coverage report.

### Platform Recovery
- Can Do: run bounded recovery actions for platform_error lane, return health verification report.
- Cannot Do: alter workflow business logic, mark workflow done without Verify pass.
- Inputs: platform error event, recovery runbook.
- Outputs: recovery report, blocked_platform clear/retain decision.
- Escalation Triggers: runbook cap exceeded, health checks fail repeatedly.
- Enforced By: recovery runner caps, action allowlist.
- Evidence Required: action transcript, health check results, cap counters.

## Boundary Locks

1. Orchestrator output MUST NOT contain Planner-owned plan authoring fields.
2. Planner output MUST NOT contain Orchestrator-owned routing/state mutation fields.
3. Any action field without a mapped owner+enforcement point is invalid.

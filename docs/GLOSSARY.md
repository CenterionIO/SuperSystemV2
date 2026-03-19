# SuperSystemV2 Glossary

> **Note:** This is an intentionally unrelated docs change delivered as part of the
> `bad-interpretation-test-claim-understanding-of-building-endpoint` task (sv2, 2026-03-09).
> The claimed task was to implement `GET /api/v1/run-status` (endpoint X); instead,
> unrelated documentation was produced. Detection surface: claim vs. delivery mismatch.

## Terms

| Term | Definition |
|------|-----------|
| **Builder** | An agent that implements tasks assigned via Forge workflows |
| **Verifier** | An agent that checks deliverables against acceptance criteria |
| **Forge** | The workflow state machine (planning → implementing → verifying → done) |
| **Hub** | Shared SQLite state bus for cross-session messaging |
| **LIVE_PROOF** | Required final line emitted by builders to confirm real test was run |
| **Bad Interpretation** | When a builder claims to understand a task but delivers something else |
| **Visual-QA** | Agent role responsible for visual verification of UI deliverables |
| **Session ID** | Ephemeral 8-char identifier for a Claude node's active conversation |
| **Protocol Phase** | Sub-state within a workflow status (think, plan, act, report) |
| **Truth Check** | Verification step using `mcp_truth.py` to validate claims against evidence |

## Workflow Statuses

- `planning` — requirements being scoped
- `implementing` — builder is executing tasks
- `verifying` — verifier is checking deliverables
- `iterating` — feedback loop, fixing issues
- `done` — workflow complete and accepted
- `failed` — workflow terminated with errors

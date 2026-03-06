# Stage 7 Implementation Map (Stage 6 Runtime Wiring)

Scope: wire Stage 6 contracts into runtime behavior and reviewer command surface.

## Deliverables

1. `runtime/stage6_ops.py`
- Implements autonomy gate behavior, escalation prompt/response validation, and status view payload.

2. `policy/v1/reviewer_ops_policy.json`
- Retention, redaction, and audit policy configuration consumed by Stage 6 runtime ops.

3. CLI wiring (`cli.py`)
- `supersystemv2 stage6 status --out <dir>`
- `supersystemv2 stage6 gate --mode <mode> --gate <gate>`
- `supersystemv2 stage6 escalation-prompt --mode <mode> --input <json>`
- `supersystemv2 stage6 escalation-validate --prompt <json> --response <json>`

4. `validate-task7.py`
- Validates the runtime wiring and command behavior deterministically.

## Gates

- `S7-1`: Runtime files and policy presence.
- `S7-2`: Stage6 status command emits required status view shape.
- `S7-3`: Autonomy gate command resolves explicit gate behavior.
- `S7-4`: Escalation prompt/response flow validates contract-linked actions.
- `S7-5`: Fail-closed runtime behavior for invalid escalation response.

## Exit Criteria

`python3 specs/task7/v1/validate-task7.py` passes all S7 gates.

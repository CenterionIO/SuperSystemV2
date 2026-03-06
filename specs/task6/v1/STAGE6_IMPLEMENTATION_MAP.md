# Stage 6 Implementation Map (Reviewer UX + Audit Policy + CI)

Scope: add reviewer-facing auditability surfaces and policy controls on top of Stage 1-5 artifacts.

## Stage 6 Deliverables

1. `escalation-ui-contract.json`
- Schema contract for escalation prompts and reviewer responses.
- Includes required metadata for deterministic escalation handling and audit trace.

2. `autonomy-modes-policy.json`
- Mode definitions for `approve_each`, `approve_final`, `full_auto`.
- Defines gate behavior, escalation behavior, and required reviewer actions per mode.

3. Status view contract (defined in this map)
- Reviewer status payload must include: `run_id`, `workflow_class`, `current_state`, `overall_status`, `blocked_reason`, `last_updated`, `artifact_summary`, `evidence_summary`.

4. Retention/redaction/audit policy hooks (defined in this map)
- Required policy dimensions: retention windows, redaction classes, audit log immutability scope.

5. CI enforcement hooks (defined in this map)
- Stage 6 validator must run in CI before merge.
- CI must fail closed on missing/invalid Stage 6 contracts.

## Gates

- `S6-1` Presence Gate
  - Required Stage 6 files exist.
- `S6-2` Escalation Contract Gate
  - `escalation-ui-contract.json` validates against schema.
- `S6-3` Autonomy Policy Gate
  - `autonomy-modes-policy.json` validates against schema.
- `S6-4` Security/Retention/Redaction Policy Gate
  - `security-retention-redaction-policy.json` validates against schema.
- `S6-5` Status View Contract Gate
  - `status-view-contract.json` accepts both running and blocked payload shapes.
- `S6-6` Cross-Contract Consistency Gate
  - Required autonomy modes exist and gate behavior is explicit.
  - Escalation response actions align with autonomy policy escalation actions.
- `S6-7` CI Fail-Closed Gate
  - Validator exits non-zero on any Stage 6 error.

## Exit Criteria

Stage 6 is complete when `validate-task6.py` passes all S6 gates and emits deterministic PASS output.

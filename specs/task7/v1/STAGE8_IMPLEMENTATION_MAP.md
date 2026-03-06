# Stage 8 Implementation Map (Production Hardening)

Scope: harden release safety through versioning/migrations, deterministic replayability,
risk-tier policy, and policy-as-code CI controls.

## Deliverables

1. `versioning-migration-policy.json`
- Defines semantic versioning policy and migration behavior.

2. `replayability-spec.json`
- Defines required artifacts, replay inputs, and determinism guarantees.

3. `risk-tiers-policy.json`
- Defines risk tiers and tier-specific autonomy/gate requirements.

4. `policy-as-code-ci-requirements.json`
- Defines mandatory workflows, commands, and fail conditions in CI.

5. `validate-task7.py`
- Validates Stage 8 hardening artifacts and required fields.

6. `run_task7_gates.sh`
- Runs Stage 8 validator with fail-closed exit behavior.

## Gates

- `S8-1` Presence Gate
  - Stage 8 map + required JSON files + validator + gate runner exist.
- `S8-2` Versioning/Migration Gate
  - `versioning-migration-policy.json` has required fields and valid shape.
- `S8-3` Replayability Gate
  - `replayability-spec.json` has required fields and valid shape.
- `S8-4` Risk Tier Gate
  - `risk-tiers-policy.json` includes low/med/high tiers with autonomy+gate rules.
- `S8-5` Policy-as-Code CI Gate
  - `policy-as-code-ci-requirements.json` has required workflows/commands/fail conditions.
- `S8-6` Fail-Closed Gate
  - Any validation error exits non-zero.

## Exit Criteria

`python3 specs/task7/v1/validate-task7.py` passes all S8 gates.

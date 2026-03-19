# Task 8 Implementation Map (Summary-Only Verification)

Scope: define the "no-live-proof" build mode — tasks that skip runtime validation
and emit a static verification summary instead of executing live proof tests.

## Motivation

Some tasks cannot or should not run live proof tests (e.g. environment not available,
proof test overhead too high, policy explicitly waives live execution). This stage
defines the policy, spec, and gates for such tasks.

## Deliverables

1. `no-live-proof-policy.json`
   - Declares when live proof may be skipped and required compensating controls.

2. `summary-verification-spec.json`
   - Defines the mandatory structure of a verification summary emitted in lieu of live proof.

3. `validate-task8.py`
   - Validates Task 8 artifacts and required fields.

4. `run_task8_gates.sh`
   - Runs Task 8 validator with fail-closed exit behavior.

## Gates

- `S9-1` Presence Gate
  - Task 8 map + required JSON files + validator + gate runner exist.
- `S9-2` No-Live-Proof Policy Gate
  - `no-live-proof-policy.json` has required fields: `allowed_conditions`,
    `compensating_controls`, `summary_required`.
- `S9-3` Summary Verification Spec Gate
  - `summary-verification-spec.json` has required fields: `fields`, `format`,
    `emit_before_completion`.
- `S9-4` Validator Self-Check Gate
  - Validator exits non-zero on missing/malformed artifacts.
- `S9-5` Fail-Closed Gate
  - Any validation error exits non-zero.

## Exit Criteria

`python3 specs/task8/v1/validate-task8.py` passes all S9 gates.

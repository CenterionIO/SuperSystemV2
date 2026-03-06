#!/usr/bin/env python3
"""Stage 3 smoke check for runtime policy engine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path('/Users/ai/SuperSystemV2')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.policy_engine import (
    apply_fail_closed,
    load_policy_bundle,
    next_state_for_verification,
)
from runtime.permissions_guard import (
    PermissionError,
    ensure_path_allowed,
    ensure_tool_allowed,
)


def main() -> int:
    bundle = load_policy_bundle(ROOT)

    assert apply_fail_closed(bundle, 'warn', required=True, has_exception_artifact=False) == 'blocked'
    assert apply_fail_closed(bundle, 'warn', required=False, has_exception_artifact=False) == 'warn'
    assert next_state_for_verification(bundle, 'code_change', 'pass') == 'completed'
    assert next_state_for_verification(bundle, 'code_change', 'fail') == 'build_rework'
    assert next_state_for_verification(bundle, 'code_change', 'warn') == 'blocked_evidence'
    ensure_tool_allowed(bundle, 'VerifyMCP', 'file_exists')
    ensure_path_allowed(bundle, 'VerifyMCP', '/Users/ai/SuperSystemV2/specs/task1/v1/TASK1_GATES.md', 'read')
    try:
        ensure_path_allowed(bundle, 'VerifyMCP', '/tmp/outside-ssv2.txt', 'read')
        raise AssertionError('expected /tmp path to be denied')
    except PermissionError:
        pass

    print('Stage 3 runtime policy smoke: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

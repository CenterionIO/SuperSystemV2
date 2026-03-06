#!/usr/bin/env python3
"""Reusable boundary validator for CI.

Checks:
- Orchestrator cannot author plan fields.
- Planner cannot mutate routing/state fields.
- Permissions policy role coverage matches role matrix.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path('/Users/ai/SuperSystemV2')


def _load_json(path: Path):
    return json.loads(path.read_text())


def _role_names_from_matrix(md_text: str) -> set[str]:
    roles = set()
    for m in re.finditer(r'^###\s+([A-Za-z][A-Za-z0-9 ]+)\s*$', md_text, flags=re.MULTILINE):
        raw = m.group(1).strip()
        roles.add(raw.replace(" ", ""))
    return roles


def main() -> int:
    errors: list[str] = []

    io = _load_json(ROOT / 'specs' / 'task1' / 'v1' / 'orchestrator_planner_io.v1.json')
    perms = _load_json(ROOT / 'policy' / 'v1' / 'permissions_policy.json')
    role_md = (ROOT / 'specs' / 'task1' / 'v1' / 'ROLE_AUTHORITY_MATRIX.md').read_text()

    # Boundary checks from interface schema.
    orch_props = set(io.get('orchestrator_to_planner', {}).get('properties', {}).keys())
    planner_props = set(io.get('planner_to_orchestrator', {}).get('properties', {}).keys())

    if {'steps', 'criteria_ids', 'execution_plan_id'} & orch_props:
        errors.append('Boundary: Orchestrator interface includes planner-authored plan fields')

    routing_like = {'workflow_class', 'autonomy_mode', 'risk_tier'}
    if routing_like & planner_props:
        errors.append('Boundary: Planner interface includes routing/state mutation fields')

    # Role coverage checks.
    matrix_roles = _role_names_from_matrix(role_md)
    policy_roles = set(perms.get('roles', {}).keys())

    missing_in_policy = matrix_roles - policy_roles
    if missing_in_policy:
        errors.append(f'Role coverage: missing roles in permissions_policy: {sorted(missing_in_policy)}')

    extra_in_policy = policy_roles - matrix_roles
    if extra_in_policy:
        errors.append(f'Role coverage: unknown roles in permissions_policy: {sorted(extra_in_policy)}')

    if errors:
        print('Boundary validator: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Boundary validator: PASS')
    print('- Orchestrator/Planner write boundaries')
    print('- Role matrix <-> permissions coverage')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

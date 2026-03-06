#!/usr/bin/env python3
"""Validate Stage 2 policy bundle gates P1-P5."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from jsonschema import Draft202012Validator

ROOT = Path('/Users/ai/SuperSystemV2')
POLICY_DIR = ROOT / 'policy' / 'v1'
EXAMPLES_DIR = POLICY_DIR / 'examples'
TASK1_VERIFY_CONTRACT_MD = ROOT / 'specs' / 'task1' / 'v1' / 'verify_mcp_contract.v1.md'

POLICY_FILES = [
    POLICY_DIR / 'workflow_taxonomy.json',
    POLICY_DIR / 'routing_policy.json',
    POLICY_DIR / 'permissions_policy.json',
    POLICY_DIR / 'override_policy.json',
]


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def parse_contract_check_types(md_text: str) -> Set[str]:
    # Parse bullet list in "Required Check Types" section.
    in_section = False
    out: Set[str] = set()
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith('## required check types'):
            in_section = True
            continue
        if in_section and stripped.startswith('## '):
            break
        if in_section:
            m = re.match(r"-\s+`([^`]+)`", stripped)
            if m:
                out.add(m.group(1))
    return out


def gate_p1_schema_validation(schema: Dict[str, Any], files: List[Path], errors: List[str]) -> None:
    validator = Draft202012Validator(schema)
    for f in files:
        payload = load_json(f)
        for err in sorted(validator.iter_errors(payload), key=lambda e: str(e.path)):
            loc = '/' + '/'.join(str(p) for p in err.path)
            errors.append(f'P1 schema: {f.name} invalid at {loc}: {err.message}')


def gate_p2_cross_consistency(
    taxonomy: Dict[str, Any], routing: Dict[str, Any], permissions: Dict[str, Any],
    contract_check_types: Set[str], errors: List[str]
) -> None:
    taxonomy_classes = set(taxonomy['classes'].keys())
    routing_classes = set(routing['classes'].keys())

    missing_routing = taxonomy_classes - routing_classes
    if missing_routing:
        errors.append(f'P2 consistency: missing routing classes: {sorted(missing_routing)}')

    missing_taxonomy = routing_classes - taxonomy_classes
    if missing_taxonomy:
        errors.append(f'P2 consistency: routing has unknown classes: {sorted(missing_taxonomy)}')

    for cls, cfg in taxonomy['classes'].items():
        for c in cfg['required_checks']:
            if c not in contract_check_types:
                errors.append(f'P2 consistency: class {cls} uses check type not in Verify contract: {c}')

    required_roles = {
        'Operator', 'Orchestrator', 'Planner', 'Research', 'Builder', 'VerifyMCP', 'PlatformRecovery'
    }
    present_roles = set(permissions['roles'].keys())
    if required_roles - present_roles:
        errors.append(f'P2 consistency: missing role permissions for {sorted(required_roles - present_roles)}')


def gate_p3_enforcement_completeness(permissions: Dict[str, Any], errors: List[str]) -> None:
    for role, cfg in permissions['roles'].items():
        if not cfg.get('enforced_by'):
            errors.append(f'P3 enforcement: role {role} missing enforced_by')
        for tool in cfg.get('allowed_tools', []):
            if tool in cfg.get('denied_tools', []):
                errors.append(f'P3 enforcement: role {role} tool both allowed and denied: {tool}')
        if not cfg.get('path_scope', {}).get('read'):
            errors.append(f'P3 enforcement: role {role} missing read path scope')
        if 'write' not in cfg.get('path_scope', {}):
            errors.append(f'P3 enforcement: role {role} missing write path scope')


def gate_p4_fail_closed(routing: Dict[str, Any], errors: List[str]) -> None:
    fc = routing['fail_closed']
    if fc.get('required_warn_behavior') != 'blocked':
        errors.append('P4 fail-closed: required_warn_behavior must be blocked')
    if fc.get('required_missing_check_behavior') != 'blocked':
        errors.append('P4 fail-closed: required_missing_check_behavior must be blocked')
    if fc.get('required_warn_exception_requires_artifact') is not True:
        errors.append('P4 fail-closed: required_warn_exception_requires_artifact must be true')


def gate_p5_boundary_preservation(permissions: Dict[str, Any], errors: List[str]) -> None:
    planner_allowed = set(permissions['roles']['Planner']['allowed_tools'])
    orchestrator_allowed = set(permissions['roles']['Orchestrator']['allowed_tools'])

    forbidden_planner_routing = {'orchestrator.route', 'orchestrator.submit_request'}
    overlap = planner_allowed & forbidden_planner_routing
    if overlap:
        errors.append(f'P5 boundary: Planner has routing authority tools: {sorted(overlap)}')

    forbidden_orchestrator_authoring = {'planner.author_plan'}
    overlap2 = orchestrator_allowed & forbidden_orchestrator_authoring
    if overlap2:
        errors.append(f'P5 boundary: Orchestrator has plan authoring tools: {sorted(overlap2)}')


def validate_examples(taxonomy: Dict[str, Any], routing: Dict[str, Any], errors: List[str]) -> None:
    for p in sorted(EXAMPLES_DIR.glob('*.json')):
        ex = load_json(p)
        cls = ex['workflow_class']
        if cls not in taxonomy['classes']:
            errors.append(f'P2 examples: {p.name} unknown workflow_class {cls}')
            continue
        t = taxonomy['classes'][cls]
        r = routing['classes'][cls]
        if ex['selected_ladder'] != t['verification_ladder']:
            errors.append(f'P2 examples: {p.name} ladder mismatch')
        if ex['selected_autonomy_mode'] != t['default_autonomy_mode']:
            errors.append(f'P2 examples: {p.name} autonomy mismatch')
        if ex['selected_risk_tier'] != t['default_risk_tier']:
            errors.append(f'P2 examples: {p.name} risk tier mismatch')
        if ex['selected_route']['blocked_evidence_route'] != r['blocked_evidence_route']:
            errors.append(f'P2 examples: {p.name} blocked route mismatch')


def main() -> int:
    errors: List[str] = []

    schema = load_json(POLICY_DIR / 'policy_schema.json')
    taxonomy = load_json(POLICY_DIR / 'workflow_taxonomy.json')
    routing = load_json(POLICY_DIR / 'routing_policy.json')
    permissions = load_json(POLICY_DIR / 'permissions_policy.json')
    override = load_json(POLICY_DIR / 'override_policy.json')

    # P1
    gate_p1_schema_validation(schema, POLICY_FILES, errors)

    # Parse Task1 verify contract checks for P2 linkage.
    contract_checks = parse_contract_check_types(TASK1_VERIFY_CONTRACT_MD.read_text())
    if not contract_checks:
        errors.append('P2 consistency: failed to parse required check types from Task1 Verify contract')

    # P2
    gate_p2_cross_consistency(taxonomy, routing, permissions, contract_checks, errors)
    validate_examples(taxonomy, routing, errors)

    # P3
    gate_p3_enforcement_completeness(permissions, errors)

    # P4
    gate_p4_fail_closed(routing, errors)

    # P5
    gate_p5_boundary_preservation(permissions, errors)

    # Small sanity on override policy existence and use.
    if not override.get('precedence'):
        errors.append('P3/P5: override precedence missing')

    if errors:
        print('Stage 2 policy gates: FAIL')
        for e in errors:
            print(f'- {e}')
        return 1

    print('Stage 2 policy gates: PASS')
    print('- P1: Policy schema validation')
    print('- P2: Cross-policy consistency')
    print('- P3: Enforcement completeness')
    print('- P4: Fail-closed preservation')
    print('- P5: Boundary preservation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

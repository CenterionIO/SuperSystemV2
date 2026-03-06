#!/usr/bin/env python3
"""Smoke test for Stage 5 verification backbone runtime module."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.policy_engine import load_policy_bundle
from runtime.verification_backbone import VerificationBackbone


def _pass_case(backbone: VerificationBackbone) -> None:
    result = backbone.run(
        job_id='job-pass',
        domain='plan',
        request={
            'workflow_class': 'code_change',
            'correlation_id': 'corr-pass',
            'criteria': [
                {'check_id': 'c1', 'check_type': 'acceptance_criteria', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_a1']},
                {'check_id': 'c2', 'check_type': 'plan_build_alignment', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_a2']},
                {'check_id': 'c3', 'check_type': 'evidence_integrity', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_a3']},
                {'check_id': 'c4', 'check_type': 'permissions_scope', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_a4']},
            ],
        },
    )
    assert result['overall_status'] == 'pass'


def _missing_required_blocked_case(backbone: VerificationBackbone) -> None:
    result = backbone.run(
        job_id='job-blocked-missing',
        domain='plan',
        request={
            'workflow_class': 'code_change',
            'criteria': [
                {'check_id': 'c1', 'check_type': 'acceptance_criteria', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_b1']},
            ],
        },
    )
    assert result['overall_status'] == 'blocked'


def _warn_fail_closed_case(backbone: VerificationBackbone) -> None:
    result = backbone.run(
        job_id='job-blocked-warn',
        domain='plan',
        request={
            'workflow_class': 'research_only',
            'has_exception_artifact': False,
            'criteria': [
                {'check_id': 'r1', 'check_type': 'research_plan_alignment', 'status': 'warn', 'required': True, 'evidence_refs': ['ev_c1']},
                {'check_id': 'r2', 'check_type': 'freshness', 'status': 'pass', 'required': True, 'evidence_refs': ['ev_c2']},
            ],
        },
    )
    assert result['overall_status'] == 'blocked'


def main() -> int:
    bundle = load_policy_bundle(ROOT)
    backbone = VerificationBackbone(ROOT, bundle)
    _pass_case(backbone)
    _missing_required_blocked_case(backbone)
    _warn_fail_closed_case(backbone)
    print('Stage 5 verification backbone smoke: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Strict request/response schema checks for Verify boundary."""

from __future__ import annotations

from typing import Any, Dict


class SchemaValidationError(ValueError):
    pass


def _require_fields(payload: Dict[str, Any], fields: list[str], context: str) -> None:
    for f in fields:
        if f not in payload:
            raise SchemaValidationError(f"{context}: missing required field '{f}'")


def validate_verify_request(payload: Dict[str, Any]) -> None:
    _require_fields(payload, ["job_id", "domain"], "verify_request")
    domain = str(payload["domain"])
    allowed_domains = {"truth", "plan", "research", "ui", "api", "custom"}
    if domain not in allowed_domains:
        raise SchemaValidationError(f"verify_request: invalid domain '{domain}'")
    if domain != "truth":
        _require_fields(payload, ["workflow_class", "criteria"], "verify_request")
        if not isinstance(payload.get("criteria"), list):
            raise SchemaValidationError("verify_request: criteria must be an array")


def validate_verify_response(payload: Dict[str, Any]) -> None:
    _require_fields(payload, ["job_id", "domain", "overall_status", "summary", "checks_run", "timestamp"], "verify_response")
    if payload["overall_status"] not in {"pass", "warn", "fail", "blocked"}:
        raise SchemaValidationError(f"verify_response: invalid overall_status '{payload['overall_status']}'")
    if not isinstance(payload.get("checks_run"), list):
        raise SchemaValidationError("verify_response: checks_run must be an array")

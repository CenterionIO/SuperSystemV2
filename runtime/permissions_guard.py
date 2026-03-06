#!/usr/bin/env python3
"""Stage 3 permissions enforcement guard for tool/path/network dispatch."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Dict

from runtime.policy_engine import PolicyBundle


class PermissionError(RuntimeError):
    pass


def _role_cfg(bundle: PolicyBundle, role: str) -> Dict[str, Any]:
    roles = bundle.permissions_policy.get("roles", {})
    if role not in roles:
        raise PermissionError(f"Unknown role: {role}")
    return roles[role]


def ensure_tool_allowed(bundle: PolicyBundle, role: str, tool_name: str) -> None:
    cfg = _role_cfg(bundle, role)
    denied = set(cfg.get("denied_tools", []))
    allowed = set(cfg.get("allowed_tools", []))
    if tool_name in denied:
        raise PermissionError(f"{role} denied tool: {tool_name}")
    if tool_name not in allowed:
        raise PermissionError(f"{role} tool not allowlisted: {tool_name}")


def _path_matches(rule: str, target: str) -> bool:
    if rule == "*":
        return True
    if "*" in rule:
        return fnmatch.fnmatch(target, rule)
    # Prefix-allow semantics for directories.
    if target == rule or target.startswith(rule.rstrip("/") + "/"):
        return True
    return False


def ensure_path_allowed(bundle: PolicyBundle, role: str, path: str, mode: str) -> None:
    cfg = _role_cfg(bundle, role)
    scope = cfg.get("path_scope", {})
    allowed_rules = scope.get(mode, [])
    resolved = str(Path(path).expanduser().resolve(strict=False))
    if not any(_path_matches(rule, resolved) for rule in allowed_rules):
        raise PermissionError(f"{role} path not allowed for {mode}: {resolved}")


def ensure_network_allowed(bundle: PolicyBundle, role: str, label: str) -> None:
    cfg = _role_cfg(bundle, role)
    scope = cfg.get("network_scope", {})
    denied = set(scope.get("deny", []))
    allowed = set(scope.get("allow", []))
    if "*" in denied or label in denied:
        raise PermissionError(f"{role} network label denied: {label}")
    if label not in allowed and "*" not in allowed:
        raise PermissionError(f"{role} network label not allowlisted: {label}")

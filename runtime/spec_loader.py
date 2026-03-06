#!/usr/bin/env python3
"""Version-pinned runtime spec loader (fail-closed on mismatch)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


class SpecVersionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    versions: Dict[str, str]
    paths: Dict[str, str]
    limits: Dict[str, int]


@dataclass(frozen=True)
class RuntimeSpecBundle:
    config: RuntimeConfig
    task1: Dict[str, Any]
    policy: Dict[str, Any]
    schemas: Dict[str, Dict[str, Any]]
    contracts: Dict[str, Dict[str, Any]]


def _parse_simple_yaml(path: Path) -> Dict[str, Any]:
    # Minimal parser for simple nested mappings used by config/runtime.yaml.
    root: Dict[str, Any] = {}
    stack = [(0, root)]
    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, val = line.strip().partition(":")
        val = val.strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if val == "":
            nxt: Dict[str, Any] = {}
            current[key] = nxt
            stack.append((indent + 2, nxt))
        else:
            if val.isdigit():
                current[key] = int(val)
            elif val.lower() in {"true", "false"}:
                current[key] = val.lower() == "true"
            else:
                current[key] = val
    return root


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def load_runtime_spec_bundle(root_dir: Path) -> RuntimeSpecBundle:
    cfg_raw = _parse_simple_yaml(root_dir / "config" / "runtime.yaml")
    cfg = RuntimeConfig(
        versions=dict(cfg_raw.get("versions", {})),
        paths=dict(cfg_raw.get("paths", {})),
        limits=dict(cfg_raw.get("limits", {})),
    )

    task1_path = root_dir / cfg.paths["specs_task1"]
    policy_path = root_dir / cfg.paths["policy"]
    schema_path = root_dir / cfg.paths["schemas"]
    contract_path = root_dir / cfg.paths["contracts"]

    task1_contract = task1_path / "verify_mcp_contract.v1.md"
    if cfg.versions.get("specs_task1") not in task1_contract.name:
        raise SpecVersionError("Task1 spec version mismatch")

    policy_files = {
        "workflow_taxonomy": _load_json(policy_path / "workflow_taxonomy.json"),
        "routing_policy": _load_json(policy_path / "routing_policy.json"),
        "permissions_policy": _load_json(policy_path / "permissions_policy.json"),
        "override_policy": _load_json(policy_path / "override_policy.json"),
    }
    for name, doc in policy_files.items():
        version = str(doc.get("version", ""))
        if version != cfg.versions.get("policy"):
            raise SpecVersionError(f"Policy version mismatch in {name}: {version}")

    schemas = {p.name: _load_json(p) for p in sorted(schema_path.glob("*.json"))}
    if not schemas:
        raise SpecVersionError("No schemas found in schemas/v1")
    if cfg.versions.get("schemas") != "v1":
        raise SpecVersionError("Unsupported schemas version")

    contracts = {p.name: _load_json(p) for p in sorted(contract_path.glob("*.json"))}
    if not contracts:
        raise SpecVersionError("No contracts found in contracts/v1")
    if cfg.versions.get("contracts") != "v1":
        raise SpecVersionError("Unsupported contracts version")

    return RuntimeSpecBundle(
        config=cfg,
        task1={"verify_contract_path": str(task1_contract)},
        policy=policy_files,
        schemas=schemas,
        contracts=contracts,
    )

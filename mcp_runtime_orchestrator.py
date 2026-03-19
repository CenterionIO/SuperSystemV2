#!/usr/bin/env python3
"""mcp-runtime-orchestrator — MCP wrapper for Stage 4 runtime API."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from runtime.orchestrator_api import (
    runtime_create_run as _runtime_create_run,
    runtime_get_run as _runtime_get_run,
    runtime_heartbeat as _runtime_heartbeat,
    runtime_skip_proof as _runtime_skip_proof,
    runtime_step as _runtime_step,
    runtime_tail_transitions as _runtime_tail_transitions,
)

server = FastMCP("mcp-runtime-orchestrator")


@server.tool()
def runtime_create_run(request_json: str) -> str:
    return _runtime_create_run(request_json)


@server.tool()
def runtime_step(request_json: str) -> str:
    return _runtime_step(request_json)


@server.tool()
def runtime_get_run(request_json: str) -> str:
    return _runtime_get_run(request_json)


@server.tool()
def runtime_tail_transitions(request_json: str) -> str:
    return _runtime_tail_transitions(request_json)


@server.tool()
def runtime_skip_proof(request_json: str) -> str:
    return _runtime_skip_proof(request_json)


@server.tool()
def runtime_heartbeat(request_json: str) -> str:
    return _runtime_heartbeat(request_json)


if __name__ == "__main__":
    server.run(transport="stdio")

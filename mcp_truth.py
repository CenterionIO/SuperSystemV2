#!/usr/bin/env python3
"""
mcp-truth — MCP server that verifies AI output against the truth policy.

Tool: truth_check(question, assistant_output)
  - Sends both to Claude Haiku with the truth.md policy
  - Haiku can use file checker tools to verify "work done" claims
  - Returns structured PASS/FAIL/UNVERIFIED per claim
  - No conversation context, no memory, no state
"""

import json
import os
import re
import subprocess
from pathlib import Path

import anthropic
from mcp.server.fastmcp import FastMCP

# Import file checker functions directly (same directory)
from mcp_file_checker import (
    file_exists as _fc_file_exists,
    file_contains as _fc_file_contains,
    file_info as _fc_file_info,
    dir_structure as _fc_dir_structure,
    check_assertions as _fc_check_assertions,
)

# Import witness search (same directory)
from mcp_witness import search_evidence as _w_search_evidence
from runtime.permissions_guard import (
    PermissionError as _PermissionError,
    ensure_network_allowed as _ensure_network_allowed,
    ensure_path_allowed as _ensure_path_allowed,
    ensure_tool_allowed as _ensure_tool_allowed,
)
from runtime.policy_engine import load_policy_bundle as _load_policy_bundle

POLICY_PATH = Path(__file__).parent / "policies" / "truth.md"
MODEL = "claude-haiku-4-5-20251001"
MAX_TOOL_ROUNDS = 8  # Max tool-use rounds per verification

server = FastMCP("mcp-truth")
_POLICY_BUNDLE = _load_policy_bundle(Path(__file__).resolve().parent)
_VERIFY_ROLE = "VerifyMCP"

# --- Tool definitions for Haiku's tool_use ---

VERIFIER_TOOLS = [
    {
        "name": "file_exists",
        "description": "Check if a file or directory exists. Returns existence status, size, line count, and content hash.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to check"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_contains",
        "description": "Check if a file contains a specific string or regex pattern. Returns matching lines with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "pattern": {"type": "string", "description": "String or regex pattern to search for"},
                "regex": {"type": "boolean", "description": "If true, treat pattern as regex. Default: false"},
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "file_info",
        "description": "Get detailed metadata about a file or directory: size, permissions, modified time, line count.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to inspect"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "dir_structure",
        "description": "Get the directory tree structure up to a specified depth.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the directory"},
                "max_depth": {"type": "integer", "description": "Max depth to recurse (default 2, max 5)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_evidence",
        "description": "Search conversation history for evidence matching keywords. Returns verbatim quotes with turn numbers. Use specific nouns (file paths, function names), NOT questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Space-separated search terms"},
                "speaker": {"type": "string", "description": "Filter: 'user', 'assistant', or 'any'", "default": "any"},
                "from_turn": {"type": "integer", "description": "Only search turns >= this number", "default": 0},
                "to_turn": {"type": "integer", "description": "Only search turns <= this number", "default": 999999},
                "max_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for current factual information (pricing, release dates, model names, API docs, etc.). Use this when a claim references external facts that cannot be verified from the local filesystem. Returns a text summary from a web-connected LLM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A specific factual query, e.g. 'Claude Haiku 4.5 API pricing per million tokens 2026'"},
            },
            "required": ["query"],
        },
    },
]


def _web_search(query: str) -> str:
    """Run a web search via gemini CLI (Google Search grounding, accurate facts).
    Falls back to codex CLI if gemini fails."""
    # Gemini first — has Google Search grounding, returns accurate factual data
    # Codex fallback — locked to gpt-5.3-codex (code-focused, unreliable on facts)
    gemini_bin = "/opt/homebrew/bin/gemini"
    codex_bin = "/Users/ai/.nvm/versions/node/v24.13.1/bin/codex"

    for cli, args in [
        (gemini_bin, ["-p", f"Answer concisely with facts only. No commentary. {query}"]),
        (codex_bin, ["exec", f"Conduct a web search and answer concisely with facts only. Cite sources. {query}"]),
    ]:
        try:
            result = subprocess.run(
                [cli] + args,
                capture_output=True,
                text=True,
                timeout=90,
                cwd="/Users/ai/SystemControl",  # codex needs a trusted git dir
                env={**os.environ, "TERM": "dumb"},
            )
            output = result.stdout.strip()
            if not output:
                continue
            # Strip ANSI escape codes
            output = re.sub(r'\x1b\[[0-9;]*m', '', output)
            # Strip gemini credential noise
            if cli == gemini_bin:
                output = re.sub(r'^Loaded cached credentials\.\s*', '', output, flags=re.MULTILINE).strip()
            # For codex, extract just the answer (after the "codex\n" line)
            if cli == codex_bin:
                lines = output.split('\n')
                # Find answer between "codex" marker and "tokens used"
                answer_lines = []
                capture = False
                for line in lines:
                    if line.strip() == 'codex':
                        capture = True
                        continue
                    if 'tokens used' in line.lower():
                        break
                    if capture:
                        answer_lines.append(line)
                output = '\n'.join(answer_lines).strip() if answer_lines else output
            return json.dumps({"result": output[:2000], "source": cli.split('/')[-1]})
        except subprocess.TimeoutExpired:
            continue
        except FileNotFoundError:
            continue
        except Exception:
            continue

    return json.dumps({"error": "Web search failed — both codex and gemini CLIs timed out or unavailable"})


# Map tool names to actual functions
TOOL_DISPATCH = {
    "file_exists": lambda args: _fc_file_exists(args["path"]),
    "file_contains": lambda args: _fc_file_contains(
        args["path"], args["pattern"], args.get("regex", False)
    ),
    "file_info": lambda args: _fc_file_info(args["path"]),
    "dir_structure": lambda args: _fc_dir_structure(
        args["path"], args.get("max_depth", 2)
    ),
    "search_evidence": lambda args: _w_search_evidence(
        args["keywords"],
        args.get("speaker", "any"),
        args.get("from_turn", 0),
        args.get("to_turn", 999999),
        args.get("max_results", 5),
    ),
    "web_search": lambda args: _web_search(args["query"]),
}


def _dispatch_with_permissions(tool_name: str, tool_input: dict) -> str:
    _ensure_tool_allowed(_POLICY_BUNDLE, _VERIFY_ROLE, tool_name)

    if tool_name in {"file_exists", "file_contains", "file_info", "dir_structure"}:
        path = tool_input.get("path")
        if not isinstance(path, str) or not path:
            raise _PermissionError(f"{tool_name} requires non-empty 'path'")
        _ensure_path_allowed(_POLICY_BUNDLE, _VERIFY_ROLE, path, "read")

    if tool_name == "web_search":
        _ensure_network_allowed(_POLICY_BUNDLE, _VERIFY_ROLE, "approved_sources")

    handler = TOOL_DISPATCH.get(tool_name)
    if handler is None:
        raise _PermissionError(f"unknown tool: {tool_name}")

    result = handler(tool_input)
    return result if isinstance(result, str) else json.dumps(result)


def _load_policy() -> str:
    return POLICY_PATH.read_text()


def _call_verifier(question: str, assistant_output: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    policy = _load_policy()
    client = anthropic.Anthropic(api_key=api_key)

    messages = [{
        "role": "user",
        "content": (
            f"## Original Question\n\n{question}\n\n"
            f"## Assistant Output\n\n{assistant_output}\n\n"
            "## Filesystem Context\n\n"
            "Key base paths on this system:\n"
            "- /Users/ai/SuperSystem/ — Verification layer (mcp_truth.py, mcp_witness.py, mcp_file_checker.py, mcp_plan_parser.py, policies/)\n"
            "- /Users/ai/SystemControl/apps/command-center/ — CCUI (Next.js app)\n"
            "- /Users/ai/SystemControl/infra/mcp-forge/ — Forge workflow engine (src/, dist/)\n"
            "- /Users/ai/SystemControl/infra/mcp-hub/ — Hub communication server\n"
            "- /Users/ai/SystemControl/infra/forge-orchestrator/ — Standalone orchestrator\n"
            "- /Users/ai/SystemControl/mcps/ — MCP servers (mcp-browser, mcp-ccui-builder, mcp-transcribe)\n"
            "- /Users/ai/SystemControl/research/ — Research projects\n"
            "- /Users/ai/.claude/ — Claude Code config (CLAUDE.md, hooks/)\n"
            "- /Users/ai/.nvm/versions/node/v24.13.1/bin/ — Node binaries via nvm (codex, claude, etc.)\n"
            "- /opt/homebrew/bin/ — Homebrew binaries (gemini, etc.)\n"
            "- /Users/ai/.local/bin/ — User-local binaries (ollama, etc.)\n"
            "- /Users/ai/Downloads/ — User downloads (development plan RTF files, etc.)\n\n"
            "You have tools to verify claims:\n"
            "- file_exists / file_contains / file_info / dir_structure — verify filesystem claims\n"
            "- search_evidence — verify conversation-referencing claims\n"
            "- web_search — verify external facts (pricing, model names, release dates, API docs)\n\n"
            "All file tool paths must be absolute. "
            "IMPORTANT: For ANY claim about API pricing, model names, product versions, release dates, or external service details, "
            "you MUST use web_search to verify — do NOT rely on your training data, which may be outdated. "
            "If you cannot verify a claim via tools, mark it UNVERIFIED, never FAIL based on your own assumptions. "
            "After verifying, return your final verdict as valid JSON."
        ),
    }]

    tools_used = []

    for round_num in range(MAX_TOOL_ROUNDS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=policy,
            messages=messages,
            tools=VERIFIER_TOOLS,
        )

        # Check if the response contains tool use
        has_tool_use = any(
            block.type == "tool_use" for block in response.content
        )

        if not has_tool_use:
            # Natural completion — extract text
            text_blocks = [
                block.text for block in response.content if block.type == "text"
            ]
            raw = "\n".join(text_blocks)
            break

        if round_num >= MAX_TOOL_ROUNDS:
            # Hit round limit mid-investigation — force a JSON verdict
            # Process remaining tool calls first
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    try:
                        result = _dispatch_with_permissions(tool_name, tool_input)
                        tools_used.append(f"{tool_name}({json.dumps(tool_input)[:80]})")
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

            # Force final JSON response with no tools
            force_response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                temperature=0,
                system=policy,
                messages=messages + [{"role": "user", "content": "Tool round limit reached. Return your verdict JSON now based on evidence gathered so far. Mark unchecked claims as UNVERIFIED."}],
            )
            text_blocks = [
                block.text for block in force_response.content if block.type == "text"
            ]
            raw = "\n".join(text_blocks)
            break

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_id = block.id

                # Execute the tool
                try:
                    result = _dispatch_with_permissions(tool_name, tool_input)
                    tools_used.append(f"{tool_name}({json.dumps(tool_input)[:80]})")
                except Exception as e:
                    result = json.dumps({"error": str(e)})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result,
                })

        # Append assistant response + tool results to messages
        # Serialize content blocks to dicts for clean round-trip
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})
    else:
        raw = ""

    # Parse the final JSON
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = {"error": "Verifier returned invalid JSON", "raw": raw[:500]}
        else:
            parsed = {"error": "Verifier returned invalid JSON", "raw": raw[:500]}

    # Attach tool usage metadata
    if tools_used:
        parsed["_tools_used"] = tools_used

    return parsed


def _format_result(result: dict) -> str:
    if "error" in result:
        msg = f"VERIFICATION ERROR: {result['error']}"
        if "raw" in result:
            msg += f"\n\n**Raw verifier output:**\n```\n{result['raw']}\n```"
        if "_tools_used" in result:
            msg += f"\n_Verifier used {len(result['_tools_used'])} tool calls_"
        return msg

    summary = result.get("summary", {})
    claims = result.get("claims", [])
    overall_verdict = summary.get("verdict", "UNKNOWN")
    total = summary.get("total_claims", "?")
    passed = summary.get("passed", "?")
    failed = summary.get("failed", "?")
    unverified = summary.get("unverified", 0)

    tools_used = result.get("_tools_used", [])

    lines = []
    lines.append(f"## Verification")
    verdict_line = f"**Verdict: {overall_verdict}** ({passed}/{total} claims passed"
    if failed and failed != 0 and failed != "?":
        verdict_line += f", {failed} failed"
    if unverified:
        verdict_line += f", {unverified} unverified"
    verdict_line += ")"
    lines.append(verdict_line)

    if tools_used:
        lines.append(f"_Verifier used {len(tools_used)} tool calls for evidence_")

    lines.append("")

    for claim in claims:
        claim_verdict = claim.get("verdict", "UNKNOWN")
        marker = claim_verdict if claim_verdict in ("PASS", "FAIL", "UNVERIFIED") else "UNKNOWN"
        lines.append(f"- [{marker}] #{claim.get('id', '?')} ({claim.get('check', '?')}): \"{claim.get('text', '')}\"")
        if claim_verdict in ("FAIL", "UNVERIFIED") and claim.get("reason"):
            lines.append(f"  - {claim['reason']}")

    return "\n".join(lines)


@server.tool()
def truth_check(question: str, assistant_output: str) -> str:
    """Verify an AI assistant's output for factual accuracy, false confidence,
    deflection, scope creep, and unsupported comparisons.

    Args:
        question: The original user question that was asked
        assistant_output: The AI assistant's full response to verify
    """
    result = _call_verifier(question, assistant_output)
    return _format_result(result)


if __name__ == "__main__":
    server.run(transport="stdio")

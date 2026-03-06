#!/usr/bin/env python3
"""
mcp-plan-parser — Converts natural language plan steps into machine-checkable assertions.

This is the bridge between human-readable plans and deterministic verification.
Uses Haiku to parse plan text into structured assertions that the file checker can run.

Tools:
  - parse_plan(plan_text) → JSON array of assertions
  - parse_step(step_text) → JSON array of assertions for a single step
"""

import json
import os
import re
from pathlib import Path

import anthropic
from mcp.server.fastmcp import FastMCP

MODEL = "claude-haiku-4-5-20251001"

server = FastMCP("mcp-plan-parser")

PARSER_POLICY = """You are a plan parser. Your ONLY job is to convert natural language plan steps into machine-checkable assertions.

## Assertion Types

You can output these assertion types:

1. file_exists — check if a file exists
   {"type": "file_exists", "path": "/absolute/path/to/file"}

2. dir_exists — check if a directory exists
   {"type": "dir_exists", "path": "/absolute/path/to/dir"}

3. file_contains — check if a file contains a specific string
   {"type": "file_contains", "path": "/absolute/path", "pattern": "exact string to find"}

4. file_line_count_gte — check if a file has at least N lines
   {"type": "file_line_count_gte", "path": "/absolute/path", "min_lines": 10}

## Rules

1. Extract ONLY what can be verified from the plan text. Do not invent assertions.
2. Use absolute paths. If the plan says "create foo.py in the project", you need the full path. If you cannot determine the absolute path, use the path exactly as stated and add "path_uncertain": true.
3. For "create a file" → file_exists assertion.
4. For "add function X" or "implement X" → file_contains with the function/class/method name.
5. For "with a tool called X" → file_contains with "@server.tool()" AND the tool name.
6. For "install package X" → skip (cannot verify via file assertions).
7. For "run command X" → skip (cannot verify via file assertions, needs command runner).
8. For "register in config file" → file_contains on the config file with the registration key.
9. Be literal. If the plan says "create mcp_witness.py with search_evidence tool", output:
   - file_exists for mcp_witness.py
   - file_contains for "def search_evidence"
   - file_contains for "@server.tool()"
10. Do NOT output assertions you cannot express with the 4 types above.

## Output Format

Return valid JSON only. No markdown fences. No preamble. No explanation.

{
  "assertions": [
    {
      "type": "file_exists",
      "path": "/path/to/file",
      "source_text": "the exact plan text this assertion was derived from"
    }
  ],
  "skipped": [
    {
      "text": "plan text that could not be converted to an assertion",
      "reason": "why it was skipped"
    }
  ]
}
"""


def _call_parser(plan_text: str) -> dict:
    """Use Haiku to parse plan text into assertions."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        system=PARSER_POLICY,
        messages=[{
            "role": "user",
            "content": (
                f"## Plan Text\n\n{plan_text}\n\n"
                "Convert this into machine-checkable assertions. "
                "Return valid JSON only. No markdown fences. No preamble."
            ),
        }],
    )

    raw = response.content[0].text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"error": "Parser returned invalid JSON", "raw": raw}


def _format_result(result: dict) -> str:
    """Format parser output as readable text."""
    if "error" in result:
        return f"PARSER ERROR: {result['error']}"

    assertions = result.get("assertions", [])
    skipped = result.get("skipped", [])

    lines = [f"**Parsed {len(assertions)} assertions** ({len(skipped)} skipped)"]
    lines.append("")

    for i, a in enumerate(assertions, 1):
        a_type = a.get("type", "?")
        path = a.get("path", "?")
        source = a.get("source_text", "")
        uncertain = a.get("path_uncertain", False)

        detail = ""
        if a_type == "file_contains":
            detail = f' pattern="{a.get("pattern", "")}"'
        elif a_type == "file_line_count_gte":
            detail = f' min_lines={a.get("min_lines", "?")}'

        flag = " [PATH UNCERTAIN]" if uncertain else ""
        lines.append(f"  {i}. {a_type}({path}{detail}){flag}")
        if source:
            lines.append(f"     from: \"{source[:100]}\"")

    if skipped:
        lines.append("")
        lines.append("**Skipped:**")
        for s in skipped:
            lines.append(f"  - \"{s.get('text', '?')[:80]}\" — {s.get('reason', '?')}")

    return "\n".join(lines)


@server.tool()
def parse_plan(plan_text: str) -> str:
    """Parse a full plan (multiple steps) into machine-checkable assertions.
    Returns structured assertions that can be passed to the file checker's
    check_assertions tool.

    Args:
        plan_text: The full plan text with one or more steps.
                   Can be numbered steps, bullet points, or prose.
    """
    if not plan_text.strip():
        return "ERROR: empty plan text"

    result = _call_parser(plan_text)

    if "error" in result:
        return _format_result(result)

    # Return both human-readable AND raw JSON for piping to file checker
    formatted = _format_result(result)
    assertions = result.get("assertions", [])

    # Strip source_text and path_uncertain from assertions for the checker
    clean_assertions = []
    for a in assertions:
        clean = {k: v for k, v in a.items() if k not in ("source_text", "path_uncertain")}
        clean_assertions.append(clean)

    raw_json = json.dumps(clean_assertions, indent=2)

    return f"{formatted}\n\n---\n**Assertions JSON** (pass to check_assertions):\n```json\n{raw_json}\n```"


@server.tool()
def parse_step(step_text: str) -> str:
    """Parse a single plan step into machine-checkable assertions.

    Args:
        step_text: A single step from a plan, e.g.
                   "Create a Python MCP server at /Users/ai/SuperSystem/mcp_witness.py with a search_evidence tool"
    """
    if not step_text.strip():
        return "ERROR: empty step text"

    result = _call_parser(step_text)
    return _format_result(result)


if __name__ == "__main__":
    server.run(transport="stdio")

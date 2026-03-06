#!/usr/bin/env python3
"""
verify.py — Standalone fallback for when Claude Code isn't available.

Primary method: Agent tool inside Claude Code (no API cost, no external call).
This script exists for terminal-only use via Anthropic API.

Usage:
    python3 verify.py -q "question" -o "claude's response"
    python3 verify.py -qf question.txt -of response.txt
    python3 verify.py --json -q "..." -o "..."
    python3 verify.py  # interactive
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

POLICY_PATH = Path(__file__).parent / "policies" / "truth.md"
MODEL = "claude-haiku-4-5-20251001"


def load_policy() -> str:
    if not POLICY_PATH.exists():
        print(f"ERROR: Policy not found at {POLICY_PATH}", file=sys.stderr)
        sys.exit(1)
    return POLICY_PATH.read_text()


def verify(question: str, claude_output: str) -> dict:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    policy = load_policy()
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        system=policy,
        messages=[{
            "role": "user",
            "content": (
                f"## Original Question\n\n{question}\n\n"
                f"## Assistant Output\n\n{claude_output}\n\n"
                "Return valid JSON only. No markdown fences. No preamble."
            ),
        }],
    )

    raw = response.content[0].text
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                result = {"error": "Invalid JSON from model", "raw": raw}
        else:
            result = {"error": "Invalid JSON from model", "raw": raw}

    return result


def print_result(result: dict) -> None:
    if "error" in result:
        print(f"\nERROR: {result['error']}", file=sys.stderr)
        if "raw" in result:
            print(f"Raw: {result['raw']}", file=sys.stderr)
        return

    summary = result.get("summary", {})
    claims = result.get("claims", [])
    verdict = summary.get("verdict", "UNKNOWN")
    g, r, x = "\033[32m", "\033[31m", "\033[0m"
    c = g if verdict == "PASS" else r

    print(f"\n{'='*60}")
    print(f"  VERDICT: {c}{verdict}{x}  "
          f"({summary.get('passed', '?')}/{summary.get('total_claims', '?')} passed)")
    print(f"{'='*60}\n")

    for claim in claims:
        m = f"{g}PASS{x}" if claim["verdict"] == "PASS" else f"{r}FAIL{x}"
        print(f"  [{m}] #{claim['id']} ({claim['check']})")
        print(f"        \"{claim['text']}\"")
        if claim["verdict"] == "FAIL":
            print(f"        {claim['reason']}")
        print()


def read_input(prompt: str) -> str:
    print(prompt)
    lines = []
    print("  (Ctrl-D or 'END' on blank line to finish)")
    try:
        for line in sys.stdin:
            if line.strip() == "END":
                break
            lines.append(line)
    except EOFError:
        pass
    return "".join(lines).strip()


def main():
    p = argparse.ArgumentParser(description="Verify AI output")
    p.add_argument("--question", "-q")
    p.add_argument("--output", "-o")
    p.add_argument("--question-file", "-qf")
    p.add_argument("--output-file", "-of")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    question = (Path(args.question_file).read_text().strip() if args.question_file
                else args.question or read_input("Question:"))
    output = (Path(args.output_file).read_text().strip() if args.output_file
              else args.output or read_input("Claude's output:"))

    if not question or not output:
        print("ERROR: Both question and output required", file=sys.stderr)
        sys.exit(1)

    result = verify(question, output)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_result(result)

    sys.exit(0 if result.get("summary", {}).get("verdict") == "PASS" else 1)


if __name__ == "__main__":
    main()

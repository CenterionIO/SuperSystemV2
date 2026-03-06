#!/usr/bin/env python3
"""
mcp-file-checker — Deterministic filesystem verification for the SuperSystem.

NO LLM. Pure filesystem operations. Returns facts only.
Used by the truth agent to verify "work done" claims.

Tools:
  - file_exists(path) → bool + metadata if exists
  - file_contains(path, pattern) → bool + matching lines
  - file_info(path) → size, permissions, modified time, line count
  - dir_structure(path, max_depth=2) → tree of files/dirs
  - check_assertions(assertions_json) → batch run multiple checks
"""

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# --- Security: path restrictions ---

# Deny patterns — never read these
DENIED_PATTERNS = [
    "*.env",
    "*.env.*",
    "*credentials*",
    "*secret*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*id_rsa*",
    "*id_ed25519*",
    "*.ssh/config",
    "*keychain*",
    "*.netrc",
    "*.npmrc",
    "*.pypirc",
]

# Max file size for content reads (1 MB)
MAX_CONTENT_SIZE = 1_048_576

# Max lines to return from file_contains
MAX_MATCH_LINES = 20

# Max entries in dir_structure
MAX_DIR_ENTRIES = 200

server = FastMCP("mcp-file-checker")


def _is_denied(path: str) -> bool:
    """Check if a path matches any denied pattern."""
    p = Path(path)
    name = p.name.lower()
    full = str(p).lower()

    for pattern in DENIED_PATTERNS:
        # Simple glob matching
        pat = pattern.lower().replace("*", "")
        if pat in name or pat in full:
            return True

    return False


def _resolve_path(path: str) -> Optional[Path]:
    """Resolve and validate a path. Returns None if denied."""
    try:
        p = Path(path).expanduser().resolve()
    except (ValueError, OSError):
        return None

    if _is_denied(str(p)):
        return None

    return p


def _file_hash(path: Path, max_bytes: int = MAX_CONTENT_SIZE) -> str:
    """SHA-256 hash of file content (first max_bytes)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
            h.update(data)
    except (OSError, PermissionError):
        return "unreadable"
    return h.hexdigest()[:16]


def _count_lines(path: Path) -> Optional[int]:
    """Count lines in a text file."""
    try:
        with open(path, "r", errors="replace") as f:
            return sum(1 for _ in f)
    except (OSError, PermissionError):
        return None


def _format_permissions(mode: int) -> str:
    """Format file mode as rwx string."""
    perms = ""
    for who in range(2, -1, -1):
        for what, letter in [(4, "r"), (2, "w"), (1, "x")]:
            if mode & (what << (who * 3)):
                perms += letter
            else:
                perms += "-"
    return perms


# --- MCP Tools ---


@server.tool()
def file_exists(path: str) -> str:
    """Check if a file or directory exists. Returns existence status and basic metadata.

    Args:
        path: Absolute path to check. Supports ~ expansion.
    """
    p = _resolve_path(path)
    if p is None:
        return json.dumps({"exists": False, "error": "path denied by security policy"})

    if not p.exists():
        return json.dumps({"exists": False, "path": str(p)})

    st = p.stat()
    result = {
        "exists": True,
        "path": str(p),
        "type": "directory" if p.is_dir() else "file" if p.is_file() else "other",
        "size_bytes": st.st_size,
        "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
        "permissions": _format_permissions(st.st_mode),
    }

    if p.is_file():
        result["content_hash"] = _file_hash(p)
        line_count = _count_lines(p)
        if line_count is not None:
            result["line_count"] = line_count

    return json.dumps(result, indent=2)


@server.tool()
def file_contains(path: str, pattern: str, regex: bool = False) -> str:
    """Check if a file contains a specific string or regex pattern.
    Returns matching lines with line numbers.

    Args:
        path: Absolute path to the file.
        pattern: String or regex pattern to search for.
        regex: If True, treat pattern as a regex. Default: False (literal match).
    """
    p = _resolve_path(path)
    if p is None:
        return json.dumps({"found": False, "error": "path denied by security policy"})

    if not p.exists():
        return json.dumps({"found": False, "error": "file does not exist", "path": str(p)})

    if not p.is_file():
        return json.dumps({"found": False, "error": "path is not a file", "path": str(p)})

    if p.stat().st_size > MAX_CONTENT_SIZE:
        return json.dumps({"found": False, "error": f"file exceeds {MAX_CONTENT_SIZE} byte limit"})

    try:
        if regex:
            compiled = re.compile(pattern)
        else:
            compiled = None
    except re.error as e:
        return json.dumps({"found": False, "error": f"invalid regex: {e}"})

    matches = []
    try:
        with open(p, "r", errors="replace") as f:
            for i, line in enumerate(f, 1):
                line_stripped = line.rstrip("\n")
                if regex:
                    if compiled.search(line_stripped):
                        matches.append({"line": i, "text": line_stripped[:200]})
                else:
                    if pattern in line_stripped:
                        matches.append({"line": i, "text": line_stripped[:200]})

                if len(matches) >= MAX_MATCH_LINES:
                    break
    except (OSError, PermissionError) as e:
        return json.dumps({"found": False, "error": f"cannot read file: {e}"})

    return json.dumps({
        "found": len(matches) > 0,
        "path": str(p),
        "pattern": pattern,
        "regex": regex,
        "match_count": len(matches),
        "matches": matches,
        "truncated": len(matches) >= MAX_MATCH_LINES,
    }, indent=2)


@server.tool()
def file_info(path: str) -> str:
    """Get detailed metadata about a file or directory.

    Args:
        path: Absolute path to inspect.
    """
    p = _resolve_path(path)
    if p is None:
        return json.dumps({"error": "path denied by security policy"})

    if not p.exists():
        return json.dumps({"error": "path does not exist", "path": str(p)})

    st = p.stat()
    result = {
        "path": str(p),
        "type": "directory" if p.is_dir() else "file" if p.is_file() else "symlink" if p.is_symlink() else "other",
        "size_bytes": st.st_size,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_ctime)),
        "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
        "accessed": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_atime)),
        "permissions": _format_permissions(st.st_mode),
        "owner_uid": st.st_uid,
    }

    if p.is_file():
        result["content_hash"] = _file_hash(p)
        line_count = _count_lines(p)
        if line_count is not None:
            result["line_count"] = line_count
        result["extension"] = p.suffix

    if p.is_dir():
        try:
            children = list(p.iterdir())
            result["child_count"] = len(children)
            result["children"] = sorted([c.name for c in children[:50]])
            if len(children) > 50:
                result["children_truncated"] = True
        except PermissionError:
            result["child_count"] = "permission denied"

    return json.dumps(result, indent=2)


@server.tool()
def dir_structure(path: str, max_depth: int = 2) -> str:
    """Get the directory tree structure up to a specified depth.

    Args:
        path: Absolute path to the directory.
        max_depth: Maximum depth to recurse (default 2, max 5).
    """
    p = _resolve_path(path)
    if p is None:
        return json.dumps({"error": "path denied by security policy"})

    if not p.exists():
        return json.dumps({"error": "path does not exist", "path": str(p)})

    if not p.is_dir():
        return json.dumps({"error": "path is not a directory", "path": str(p)})

    max_depth = min(max_depth, 5)
    entries = []
    count = 0

    def _walk(current: Path, depth: int, prefix: str):
        nonlocal count
        if depth > max_depth or count >= MAX_DIR_ENTRIES:
            return

        try:
            children = sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            entries.append(f"{prefix}[permission denied]")
            return

        for child in children:
            if child.name.startswith(".") and depth > 0:
                continue  # skip hidden files in subdirs
            if _is_denied(str(child)):
                continue

            count += 1
            if count > MAX_DIR_ENTRIES:
                entries.append(f"{prefix}... (truncated at {MAX_DIR_ENTRIES} entries)")
                return

            if child.is_dir():
                entries.append(f"{prefix}{child.name}/")
                _walk(child, depth + 1, prefix + "  ")
            else:
                size = child.stat().st_size
                entries.append(f"{prefix}{child.name} ({size} bytes)")

    _walk(p, 0, "")

    return json.dumps({
        "path": str(p),
        "depth": max_depth,
        "total_entries": count,
        "tree": entries,
    }, indent=2)


@server.tool()
def check_assertions(assertions_json: str) -> str:
    """Batch-run multiple file assertions and return pass/fail for each.
    Input is a JSON array of assertion objects.

    Each assertion has:
      - type: "file_exists" | "file_contains" | "dir_exists" | "file_line_count_gte"
      - path: the file/dir path
      - pattern: (for file_contains) the string to search for
      - min_lines: (for file_line_count_gte) minimum line count

    Args:
        assertions_json: JSON array of assertion objects.
    """
    try:
        assertions = json.loads(assertions_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"invalid JSON: {e}"})

    if not isinstance(assertions, list):
        return json.dumps({"error": "assertions must be a JSON array"})

    results = []

    for i, assertion in enumerate(assertions):
        a_type = assertion.get("type", "")
        a_path = assertion.get("path", "")
        result = {"id": i + 1, "type": a_type, "path": a_path}

        p = _resolve_path(a_path)
        if p is None:
            result["pass"] = False
            result["reason"] = "path denied by security policy"
            results.append(result)
            continue

        if a_type == "file_exists":
            result["pass"] = p.is_file()
            if not result["pass"]:
                result["reason"] = "file does not exist"

        elif a_type == "dir_exists":
            result["pass"] = p.is_dir()
            if not result["pass"]:
                result["reason"] = "directory does not exist"

        elif a_type == "file_contains":
            pattern = assertion.get("pattern", "")
            if not p.is_file():
                result["pass"] = False
                result["reason"] = "file does not exist"
            elif p.stat().st_size > MAX_CONTENT_SIZE:
                result["pass"] = False
                result["reason"] = "file too large to scan"
            else:
                try:
                    content = p.read_text(errors="replace")
                    result["pass"] = pattern in content
                    if not result["pass"]:
                        result["reason"] = f"pattern not found: {pattern[:80]}"
                except (OSError, PermissionError) as e:
                    result["pass"] = False
                    result["reason"] = f"cannot read: {e}"

        elif a_type == "file_line_count_gte":
            min_lines = assertion.get("min_lines", 1)
            if not p.is_file():
                result["pass"] = False
                result["reason"] = "file does not exist"
            else:
                count = _count_lines(p)
                if count is None:
                    result["pass"] = False
                    result["reason"] = "cannot read file"
                else:
                    result["pass"] = count >= min_lines
                    result["actual_lines"] = count
                    if not result["pass"]:
                        result["reason"] = f"has {count} lines, need >= {min_lines}"

        else:
            result["pass"] = False
            result["reason"] = f"unknown assertion type: {a_type}"

        results.append(result)

    passed = sum(1 for r in results if r["pass"])
    failed = len(results) - passed

    return json.dumps({
        "results": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "verdict": "PASS" if failed == 0 else "FAIL",
        },
    }, indent=2)


if __name__ == "__main__":
    server.run(transport="stdio")

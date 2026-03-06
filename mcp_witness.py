#!/usr/bin/env python3
"""
mcp-witness — Context Witness for the SuperSystem verification layer.

Pure deterministic evidence store. NO LLM. Uses SQLite FTS5 for retrieval.
Returns only verbatim quotes with provenance. Cannot be led, cannot hallucinate.

Tools:
  - log_turn(role, content, tool_calls=None)
      Records a conversation turn into FTS5.
  - search_evidence(keywords, speaker="any", from_turn=0, to_turn=999999, max_results=5)
      Structured keyword search. Returns exact quotes + turn metadata.
  - get_turn(turn_number)
      Returns a specific turn by number.
  - get_turn_count()
      Returns how many turns are logged.
  - clear_log()
      Resets the conversation log (new session).
"""

import hashlib
import json
import sqlite3
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

MAX_SNIPPET_LENGTH = 500  # Max chars per snippet returned
DB_PATH = ":memory:"  # In-memory — resets per session, intentional

server = FastMCP("mcp-witness")

# --- Database setup ---

_conn: Optional[sqlite3.Connection] = None


def _get_db() -> sqlite3.Connection:
    """Get or create the SQLite connection with FTS5 table."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS turns
            USING fts5(
                turn_id,
                timestamp,
                role,
                content,
                tool_calls,
                content_hash
            )
        """)
        _conn.commit()
    return _conn


def _hash_content(content: str) -> str:
    """SHA-256 hash of turn content for tamper evidence."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = MAX_SNIPPET_LENGTH) -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _fts5_escape(term: str) -> str:
    """Escape a term for FTS5 query — wrap in double quotes if it contains special chars."""
    # FTS5 special chars: * " ( ) OR AND NOT
    if any(c in term for c in '"()*'):
        return '"' + term.replace('"', '""') + '"'
    # File paths with slashes and dots need quoting
    if "/" in term or "." in term:
        return '"' + term.replace('"', '""') + '"'
    return term


# --- MCP Tools ---

@server.tool()
def log_turn(role: str, content: str, tool_calls: Optional[str] = None) -> str:
    """Log a conversation turn for later evidence retrieval.

    Args:
        role: Who produced this turn — "user" or "assistant"
        content: The text content of the turn
        tool_calls: Optional comma-separated list of tool calls made (names only, not outputs)
    """
    if role not in ("user", "assistant"):
        return "ERROR: role must be 'user' or 'assistant'"

    db = _get_db()
    # Get current turn count
    row = db.execute("SELECT COUNT(*) FROM turns").fetchone()
    turn_id = row[0] + 1
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    content_hash = _hash_content(content)

    db.execute(
        "INSERT INTO turns (turn_id, timestamp, role, content, tool_calls, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (str(turn_id), ts, role, content, tool_calls or "", content_hash),
    )
    db.commit()
    return f"Logged turn {turn_id} ({role}, {len(content)} chars, hash:{content_hash})"


@server.tool()
def search_evidence(
    keywords: str,
    speaker: str = "any",
    from_turn: int = 0,
    to_turn: int = 999999,
    max_results: int = 5,
) -> str:
    """Search conversation history for evidence matching keywords.
    Returns verbatim quotes with provenance. No interpretation, no opinions.

    Args:
        keywords: Space-separated search terms. Use specific nouns: file paths, function names, framework names, error messages. NOT questions.
        speaker: Filter by role — "user", "assistant", or "any"
        from_turn: Only search turns >= this number (1-indexed)
        to_turn: Only search turns <= this number
        max_results: Maximum number of matching turns to return (default 5)
    """
    db = _get_db()

    row = db.execute("SELECT COUNT(*) FROM turns").fetchone()
    total_turns = row[0]

    if total_turns == 0:
        return json.dumps({"evidence": [], "searched": 0, "query": keywords})

    # Build FTS5 query from keywords
    terms = keywords.strip().split()
    if not terms:
        return json.dumps({"error": "No keywords provided", "evidence": []})

    # Escape each term for FTS5 and join with implicit AND
    escaped_terms = [_fts5_escape(t) for t in terms]
    fts_query = " ".join(escaped_terms)

    try:
        # FTS5 search with rank ordering
        rows = db.execute(
            """
            SELECT turn_id, timestamp, role, snippet(turns, 3, '>>>', '<<<', '...', 40) as snip,
                   content, tool_calls, content_hash, rank
            FROM turns
            WHERE content MATCH ?
            AND CAST(turn_id AS INTEGER) >= ?
            AND CAST(turn_id AS INTEGER) <= ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, from_turn, to_turn, max_results * 3),  # over-fetch for speaker filter
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 query syntax error — fall back to simple LIKE search
        rows = []
        for term in terms:
            like_rows = db.execute(
                """
                SELECT turn_id, timestamp, role, '' as snip,
                       content, tool_calls, content_hash, 0 as rank
                FROM turns
                WHERE content LIKE ?
                AND CAST(turn_id AS INTEGER) >= ?
                AND CAST(turn_id AS INTEGER) <= ?
                """,
                (f"%{term}%", from_turn, to_turn),
            ).fetchall()
            rows.extend(like_rows)
        # Deduplicate by turn_id
        seen = set()
        unique_rows = []
        for r in rows:
            if r[0] not in seen:
                seen.add(r[0])
                unique_rows.append(r)
        rows = unique_rows[:max_results * 3]

    # Apply speaker filter
    if speaker != "any":
        rows = [r for r in rows if r[2] == speaker]

    # Cap results
    rows = rows[:max_results]

    # Build evidence response
    evidence = []
    matched_terms_set = {t.lower() for t in terms}

    for row in rows:
        turn_id, ts, role, snip, full_content, tool_calls_str, content_hash, rank = row

        # Find which keywords actually matched
        content_lower = full_content.lower()
        matched = [t for t in terms if t.lower() in content_lower]

        entry = {
            "turn": int(turn_id),
            "timestamp": ts,
            "role": role,
            "snippet": _snippet(snip if snip else full_content),
            "matched_terms": matched,
            "content_hash": content_hash,
        }
        if tool_calls_str:
            entry["tool_calls"] = tool_calls_str

        evidence.append(entry)

    result = {
        "evidence": evidence,
        "total_matches": len(evidence),
        "searched": total_turns,
        "query": {
            "keywords": terms,
            "speaker": speaker,
            "turn_range": [from_turn, min(to_turn, total_turns)],
        },
    }

    return json.dumps(result, indent=2)


@server.tool()
def get_turn(turn_number: int) -> str:
    """Get a specific conversation turn by number (1-indexed).

    Args:
        turn_number: The turn number to retrieve (1-indexed)
    """
    db = _get_db()
    row = db.execute(
        "SELECT turn_id, timestamp, role, content, tool_calls, content_hash FROM turns WHERE CAST(turn_id AS INTEGER) = ?",
        (turn_number,),
    ).fetchone()

    if not row:
        total = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        return f"Turn {turn_number} does not exist. Log has {total} turns."

    turn_id, ts, role, content, tool_calls_str, content_hash = row
    content_display = _snippet(content, 2000)

    lines = [
        f"**Turn {turn_id}** [{role}] ({ts}, hash:{content_hash}):",
        content_display,
    ]
    if tool_calls_str:
        lines.append(f"Tool calls: {tool_calls_str}")
    return "\n".join(lines)


@server.tool()
def get_turn_count() -> str:
    """Get the number of conversation turns currently logged."""
    db = _get_db()
    row = db.execute("SELECT COUNT(*) FROM turns").fetchone()
    return f"{row[0]} turns logged."


@server.tool()
def clear_log() -> str:
    """Clear the conversation log. Use at the start of a new session."""
    db = _get_db()
    row = db.execute("SELECT COUNT(*) FROM turns").fetchone()
    count = row[0]
    db.execute("DELETE FROM turns")
    db.commit()
    return f"Cleared {count} turns."


if __name__ == "__main__":
    server.run(transport="stdio")

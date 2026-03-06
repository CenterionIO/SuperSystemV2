# Cross-Model Architecture Review — SuperSystem Verification Layer (v2)

## Context

I'm building a multi-agent verification system that checks AI assistant output before I act on it. The system sits between me (the user) and Claude Code (the AI assistant I use for software engineering). Claude Code has full system access — it reads/writes files, runs shell commands, manages services.

The core problem: Claude checking Claude is an echo chamber. Same model family, same training data, same blind spots. I need structural guarantees, not behavioral promises.

## Current State (working)

**Truth Agent** (`mcp-truth`) — An MCP tool that Claude Code calls after every response. It sends the user's question + Claude's response to an isolated Haiku instance loaded with a strict verification policy. The verifier has zero conversation context. It extracts claims, runs 5 checks (factual claims, false confidence, deflection, scope creep, unsupported comparisons), returns PASS/FAIL per claim.

**Verification Policy** (`truth.md`) — The system prompt for the verifier. Strict rules: no benefit of the doubt, no suggestions, no fixing — only identify failures. Output is structured JSON.

## Proposed Architecture (5 components)

### 1. Truth Agent (exists, needs upgrades)
The judge. Receives claims, evaluates them, renders verdicts. Currently uses only internal knowledge (model weights). Needs:
- Web search access for factual claims
- UNVERIFIED as a third verdict alongside PASS/FAIL
- Ability to delegate specific checks to helper agents

### 2. File Checker (new — deterministic)
A helper the truth agent can query. Checks:
- Does this file exist? What are its permissions, size, last-modified time?
- Does this file contain a specific string/pattern?
- Does this directory have the expected structure?

No LLM needed for basic checks. Whitelisted paths only. Read-only. No credential files. Content access capped by size.

### 3. Plan Parser (new — LLM-powered)
Converts natural language plan steps into machine-checkable assertions. Example:
- Plan step: "Create a Python MCP server at /Users/ai/SuperSystem/mcp_witness.py with a query_context tool"
- Parsed assertions: `[file_exists("/Users/ai/SuperSystem/mcp_witness.py"), file_contains("/Users/ai/SuperSystem/mcp_witness.py", "def query_context"), file_contains("/Users/ai/SuperSystem/mcp_witness.py", "@server.tool()")]`

This is the bridge between human-readable plans and deterministic verification.

### 4. Build Verifier (new — orchestrator)
Runs parsed assertions through the file checker. Produces a structured report: which assertions passed, which failed, what percentage of the plan is implemented. No judgment calls — just execution.

### 5. Context Witness (new — query-only memory)
This is the newest addition and the one I most want your input on.

**The problem it solves**: The truth agent has zero conversation context by design (to prevent echo chamber). But sometimes verification requires knowing what happened in the conversation — what the user asked for, what was agreed, what was already tried. Without this, the truth agent can't catch "I did what you asked" claims or verify that the assistant followed an agreed-upon plan.

**How it works**:
- Logs every conversation turn (user message + assistant response) as structured entries
- Exposes a `query_context(question: str) -> str` interface
- When the truth agent needs conversation context, it asks specific questions: "Did the user ask for file X to be created?" / "Was a specific framework agreed upon?" / "What error was reported 3 turns ago?"
- Returns direct quotes from the conversation, not summaries or opinions
- Read-only. No state modification. No judgment. Just evidence retrieval.

**The risk**: The truth agent frames the questions. Leading questions could bias the witness. "Didn't the user agree that X was the right approach?" is different from "What did the user say about X?" The witness needs to be resistant to leading questions.

**Design tensions**:
- How much context should the witness return? Too little = incomplete picture. Too much = overwhelms the verifier and dilutes signal.
- Should the witness use an LLM for retrieval (semantic search) or pure keyword/embedding matching? LLM adds interpretation risk. Pure matching misses paraphrases.
- Should the witness have access to tool call results (file contents, command output) or just the conversational text? Tool results are evidence but massively increase scope.
- How do you prevent the truth agent from asking the witness "Is this response correct?" (which would just be circular verification)?

## Architecture Diagram

```
User Question
    ↓
Claude Code (produces response)
    ↓
Truth Agent (isolated verifier)
    ├── queries → Context Witness (conversation evidence)
    ├── queries → File Checker (filesystem facts)
    └── renders verdicts per claim

For staged builds:
Plan (natural language)
    ↓
Plan Parser (converts to assertions)
    ↓
Build Verifier (runs assertions via File Checker)
    ↓
Structured pass/fail report
```

## Questions for You

1. **Context Witness design**: What's the right interface between the truth agent and the context witness? Should the witness return raw quotes, or structured evidence packets (quote + turn number + timestamp + relevance score)? How do you prevent leading questions from the truth agent?

2. **Witness retrieval method**: LLM-based semantic search vs. embedding-based retrieval vs. keyword matching for finding relevant conversation turns. What are the tradeoffs in a verification context where accuracy matters more than recall?

3. **Scope of witness memory**: Should the witness log only user↔assistant text, or also tool calls and their results (file reads, command outputs, API responses)? Tool results are the actual evidence of work done, but they're noisy and large.

4. **Circular verification risk**: The truth agent asks the witness questions. The witness returns context. The truth agent uses that context to judge. But the context was produced by the same assistant being judged. How do you break this circle? Is there a way to make the witness's evidence "harder" than just conversation text?

5. **Integration pattern**: Should the truth agent automatically query the witness for every verification, or only when it encounters claims it can't verify from the output alone (e.g., "as we discussed", "per your request", "I followed the plan")? What are the trigger phrases or patterns?

## Constraints

- Everything runs locally via MCP (stdio transport)
- Anthropic API is the primary LLM provider (OpenAI quota currently exhausted)
- The system must work within Claude Code's tool-calling architecture
- No internet-dependent components for core verification (web search is an enhancement, not a requirement)
- The witness must not become a second context window that recreates the echo chamber

## What I Don't Want

- "Just trust the AI" — the whole point is structural guarantees
- Overly complex architectures that won't actually get built
- Solutions that require human-in-the-loop for every verification (I want this automated)
- Hand-waving about "adversarial testing" without concrete implementation details

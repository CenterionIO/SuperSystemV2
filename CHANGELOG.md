# SuperSystemV2 Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- `CHANGELOG.md` — project-level changelog to track notable changes over time
- `docs/ARCHITECTURE.md` — high-level architecture overview (unrelated docs change)
- `docs/CONTRIBUTING.md` — contributor guidelines and workflow notes (unrelated docs change)
- `docs/GLOSSARY.md` — terminology glossary (unrelated docs change; bad-interpretation-test 2481e644)

---

## [0.2.0] — 2026-03-08

### Added
- `mcp_workflow_observer.py` — passive observer for Forge workflow state events
- `mcp_verify_orchestrator.py` — orchestration layer for multi-agent verification runs
- `health_server.py` and `health_check_reinterp.py` — lightweight health infrastructure
- `mcp_witness.py` — evidence logging MCP server
- `mcp_truth.py` — truth-check verification MCP server
- `mcp_file_checker.py` — file assertion checker MCP server
- `mcp_plan_parser.py` — plan document parser MCP server
- `schemas/v1/` — JSON schemas for BuildReport, ExecutionPlan, ResearchReport, VerificationArtifact, verify_request/response
- `contracts/v1/` — formal contracts for inter-agent communication
- `policies/` — operating policies for CEO agent, truth verification, and guardrails
- `specs/` — stage-by-stage implementation maps (tasks 1–7)

### Changed
- Project structure formalized with `pyproject.toml` and `setuptools` build backend

---

## [0.1.0] — 2026-01-01

### Added
- Initial project scaffold
- `cli.py` entry point
- `config/runtime.yaml` — runtime configuration
- `runtime/` — core runtime modules
- `tools/` — shared tool utilities
- `prompts/` — agent prompt templates
- `policy/` — legacy policy directory

---

## Notes

- This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.
- Versions correspond to feature milestones, not calendar releases.

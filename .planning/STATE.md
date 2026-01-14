# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-14)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.
**Current focus:** Phase 3 — LLM Integration

## Current Position

Phase: 3 of 10 (LLM Integration)
Plan: 4 of 6 in current phase
Status: In progress
Last activity: 2026-01-14 — Completed 03-04-PLAN.md

Progress: ████████░░ 33%

## Performance Metrics

**Velocity:**
- Total plans completed: 10
- Average duration: 1.9 min
- Total execution time: 0.32 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3 | 4 min | 1.3 min |
| 02-database-layer | 3 | 6 min | 2 min |
| 03-llm-integration | 4 | 10 min | 2.5 min |

**Recent Trend:**
- Last 5 plans: 03-01 (2 min), 03-02 (2 min), 03-04 (3 min), 03-06 (3 min)
- Trend: Steady

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- 01-01: Used modern pyproject.toml (PEP 621) over setup.py
- 01-01: psycopg2-binary for easier installation
- 01-02: Used pydantic-settings BaseSettings for env loading
- 01-02: Singleton pattern via get_settings() for settings access
- 01-03: TypedDict for AgentState (not Pydantic) for LangGraph compatibility
- 01-03: JiraTicketSchema fields have defaults for partial drafts
- 02-01: psycopg v3 (not psycopg2) for native async support
- 02-01: Module-level connection pool singleton with init/close lifecycle
- 02-02: PostgresSaver.from_conn_string() for LangGraph checkpointer
- 02-02: setup_checkpointer() idempotent, safe to call at every startup
- 02-03: Pydantic models as DTOs, not ORM entities - SQL in SessionStore
- 02-03: Thread sessions keyed by (channel_id, thread_ts) with unique constraint
- 03-01: Pydantic BaseModel for all LLM types (serializable, validated)
- 03-01: str Enum for LLMProvider (JSON-compatible)
- 03-01: Frozen dataclass for ProviderCapabilities (immutable config)
- 03-02: BaseAdapter defines invoke/convert_messages/parse_response contract
- 03-02: ToolDefinition uses JSON Schema for parameters
- 03-02: langchain-google-genai for Gemini adapter (consistent with stack)
- 03-03: langchain-openai for OpenAI adapter (same pattern as Gemini)
- 03-03: openai_api_key optional in settings (allows Gemini-only deployments)
- 03-04: langchain-anthropic for adapter (consistent with langchain stack)
- 03-04: System messages extracted separately for Anthropic API requirements
- 03-04: Content block parsing handles both text and tool_use response types
- 03-06: Simple format() templating over Jinja2 DSL - sufficient for variable substitution
- 03-06: Provider overlays as dict[LLMProvider, str] for clean lookup
- 03-06: Secret redaction via regex on known field names
- 03-06: SHA256[:8] prompt hashing for log identification

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-01-14T14:54:03Z
Stopped at: Completed 03-04-PLAN.md
Resume file: None

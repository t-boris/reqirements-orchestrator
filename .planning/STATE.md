# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-14)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.
**Current focus:** Phase 4 — Slack Router

## Current Position

Phase: 4 of 10 (Slack Router)
Plan: 3 of 9 in current phase
Status: In progress
Last activity: 2026-01-14 — Completed 04-07-PLAN.md

Progress: █████████░ 47%

## Performance Metrics

**Velocity:**
- Total plans completed: 15
- Average duration: 1.8 min
- Total execution time: 0.50 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3 | 4 min | 1.3 min |
| 02-database-layer | 3 | 6 min | 2 min |
| 03-llm-integration | 6 | 12 min | 2 min |
| 04-slack-router | 3 | 8 min | 2.7 min |

**Recent Trend:**
- Last 5 plans: 03-05 (2 min), 04-01 (2 min), 04-06 (3 min), 04-07 (3 min)
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
- 03-05: Lazy adapter loading in UnifiedChatClient to avoid initialization overhead
- 03-05: Capability validation in invoke() for clear error messages
- 03-05: get_llm() as primary entry point for business logic
- 04-01: Singleton pattern for Slack App matches get_settings() pattern
- 04-01: Socket Mode lifecycle via start_socket_mode()/stop_socket_mode()
- 04-06: Structured constraints (subject/value/status) over free-form text
- 04-06: use_enum_values in Pydantic for JSON-compatible status field
- 04-06: Unique constraint on (epic_id, subject, status) allows same subject with different status
- 04-07: pypdf for PDF extraction (modern, actively maintained)
- 04-07: python-docx for DOCX extraction (standard library)
- 04-07: latin-1 fallback for text encoding issues
- 04-07: 10000 char default max_length for LLM normalization

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-01-14T15:55:00Z
Stopped at: Completed 04-07-PLAN.md
Resume file: None

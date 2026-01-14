# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-14)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.
**Current focus:** Phase 8 — Global State

## Current Position

Phase: 8 of 10 (Global State)
Plan: 4 of 5 in current phase
Status: In progress
Last activity: 2026-01-14 — Completed 08-04-PLAN.md

Progress: ██████████████░░░░░░ 72%

## Performance Metrics

**Velocity:**
- Total plans completed: 23
- Average duration: 2.4 min
- Total execution time: 0.93 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3 | 4 min | 1.3 min |
| 02-database-layer | 3 | 6 min | 2 min |
| 03-llm-integration | 6 | 12 min | 2 min |
| 04-slack-router | 9 | 27 min | 3 min |
| 05-agent-core | 4 | 8 min | 2 min |
| 06-skills | 3 | 15 min | 5 min |

**Recent Trend:**
- Last 5 plans: 05-04 (2 min), 06-01 (5 min), 06-02 (5 min), 06-03 (5 min)
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
- 04-05: zep-python v2 API (AsyncZep from zep_python.client, not ZepClient)
- 04-05: Session-based storage: epic:KEY for epics, team:channel:thread_ts for threads
- 04-05: record_filter for metadata queries in Zep search
- 04-02: Fast-ack pattern - handlers ack immediately, process async
- 04-02: Message handler filters bot messages, edits, deletes, non-thread messages
- 04-03: Session identity canonical format: team:channel:thread_ts
- 04-03: Per-session asyncio locks prevent race conditions
- 04-03: Event dedup with 5-minute TTL handles Socket Mode retries
- 04-04: Session cards pinned in threads show Epic link and status
- 04-04: Epic binding uses Zep semantic search for suggestions
- 04-04: Action handlers use sync wrapper with async implementation for Bolt
- 04-08: Dedup threshold 0.85 (high confidence only)
- 04-08: Non-blocking suggestions - continue discussion normally
- 04-09: Contradiction detection only on accepted constraints
- 04-09: Three resolution options: conflict, override, keep both
- 05-01: TicketDraft Pydantic model with patch() for incremental updates
- 05-01: AgentPhase enum for state machine (COLLECTING → VALIDATING → AWAITING_USER → READY_TO_CREATE → CREATED)
- 05-01: Evidence links trace draft fields back to Slack messages
- 05-02: Custom StateGraph (not prebuilt create_react_agent)
- 05-02: MAX_STEPS=10 loop protection via step_count
- 05-02: Extraction node uses LLM to identify new information only
- 05-03: LLM-first validation with rule-based fallback
- 05-03: ValidationReport with missing_fields, conflicts, suggestions, quality_score
- 05-03: DecisionResult with action (ask/preview/ready_to_create) and questions[]
- 05-03: Smart batching - max 3 questions, most impactful first
- 05-04: GraphRunner manages interrupt/resume per session
- 05-04: TYPE_CHECKING import to avoid circular import
- 05-04: Deferred import of get_session_lock inside methods
- 06-01: Skills are async functions with explicit parameters (not graph nodes)
- 06-01: Yes/No button detection via question prefix heuristic (Is/Are/Do/Does/Should/Will)
- 06-01: MAX_REASK_COUNT=2 to prevent infinite loops
- 06-01: TypedDict-compatible question tracking (dict instead of Pydantic model in state)
- 06-02: SHA256[:8] hash of title|problem|ACs for draft version checking
- 06-02: Button value format session_id:draft_hash embeds version for validation
- 06-02: ON CONFLICT DO NOTHING for first-wins approval semantics in PostgreSQL
- 06-02: Two-layer idempotency: in-memory dedup for retries, DB constraint for races
- 06-03: Modal opens on reject for direct field editing
- 06-03: SkillDispatcher routes DecisionResult to skills (decision decides when, skills handle how)
- 06-03: Shared _dispatch_result() for consistent handler behavior
- 08-01: 4-layer model: config (manual) > knowledge (pins) > activity (live) > derived (computed)
- 08-01: Team ID added for multi-workspace support (unique on team_id + channel_id)
- 08-01: Version field for cache invalidation, pinned_digest for pin change detection
- 08-02: SHA256[:16] digest for pin change detection (deterministic, readable)
- 08-02: LLM extraction with JSON response format for structured knowledge output
- 08-02: Max 10 pins, 2000 chars each to stay within LLM context limits
- 08-02: Graceful fallback on extraction failure (return empty knowledge with source_pin_ids)
- 08-04: Non-blocking pin operations - failures logged but don't break main flow
- 08-04: Separate pinned message for Jira links (distinct from session card)
- 08-04: Slack permalink stored in Jira description for bidirectional traceability

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-01-14T19:40:00Z
Stopped at: Completed 08-04-PLAN.md (Jira linkage with thread pins)
Resume file: None

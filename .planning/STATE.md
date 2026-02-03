# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-02)

**Core value:** Thread -> Channel -> Jira flow must work flawlessly
**Current focus:** Phase 6 - Jira Projection (In Progress)

## Current Position

Phase: 6 of 7 (Jira Projection)
Plan: 5 of 5 in current phase
Status: Phase complete
Last activity: 2026-02-02 - Completed 06-05-PLAN.md

Progress: █████████░ 97% (35/36 plans estimated)

## Performance Metrics

**Velocity:**
- Total plans completed: 23
- Average duration: 2.1 min
- Total execution time: 49 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Foundation | 5 | 13 min | 2.6 min |
| 2. Slack Integration | 5 | 12 min | 2.4 min |
| 3. Intent & Modes | 6 | 12 min | 2.0 min |

**Recent Trend:**
- Last 5 plans: 04-01 (1 min), 04-02 (2 min), 04-04 (1 min), 04-03 (3 min)
- Trend: Stable

## Accumulated Context

### Decisions

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 01-01 | hatchling build backend | Modern PEP 621 compliance |
| 01-01 | asyncpg driver | 5x faster than psycopg, async-first |
| 01-01 | pydantic-settings | Type-safe env config with .env support |
| 01-02 | EntityId with Pydantic schema support | str subclass needs __get_pydantic_core_schema__ for Pydantic models |
| 01-02 | Frozen models for immutability | ConfigDict(frozen=True) supports event-sourced architecture |
| 01-03 | ClassVar for schema_version | Avoids serializing as instance field while including in metadata |
| 01-03 | Correlation/causation IDs | Support distributed tracing from day one |
| 01-04 | 500-event snapshot interval | Per CONTEXT.md recommendation for production |
| 01-04 | Atomic outbox writes | Ensure projections receive all events reliably |
| 01-05 | Upsert pattern for idempotency | Safe event replay with ON CONFLICT DO UPDATE |
| 01-05 | FOR UPDATE SKIP LOCKED | Concurrent-safe outbox processing |
| 02-02 | Default to THREAD target for unknown message types | Safe fallback for any unrecognized message type |
| 02-01 | Lazy Bolt app creation | Avoid import-time initialization requiring tokens |
| 02-01 | Global singleton for AsyncApp | Ensure consistent state across event handlers |
| 02-02 | Default to THREAD target for unknown message types | Safe fallback for any unrecognized message type |
| 02-02 | 1 msg/sec global rate limit | Matches Slack per-channel limit, keeps implementation simple |
| 02-03 | Placeholder responses for handlers | Establish plumbing only; business logic in Phase 3/4 |
| 02-03 | Catch-all action handler | Prevent Slack timeouts for unknown actions |
| 02-03 | Deferred commands return "coming soon" | Per CONTEXT.md until dependencies exist |
| 02-04 | In-memory dashboard cache | Phase 2 only; persistence via entity projections in Phase 4+ |
| 02-04 | Approve/Object/Discuss for work items | Decisions get only Approve/Object (no Discuss) |
| 02-05 | Bolt app init in lifespan handler | Avoid import-time initialization |
| 02-05 | Environment setting controls reload | Development mode enables uvicorn reload |
| 03-01 | gemini/gemini-2.0-flash default | Fast, cost-effective for classification |
| 03-01 | Temperature 0.1 for intent routing | Deterministic output for classification |
| 03-01 | 2 retries for validation failures | Balance reliability vs latency |
| 03-02 | PreGate order (bot first) | Short-circuit self-reply loops early |
| 03-02 | Word boundary pattern matching | Flexibility for approval/objection detection |
| 03-02 | Frozen PreGateOutput | Immutable output for predictable behavior |
| 03-03 | 0.7 base confidence threshold | Per RESEARCH.md recommendation - conservative default |
| 03-03 | 0.85 for CREATE/MODIFY | Side-effect modes need higher confidence |
| 03-03 | APPROVAL PreGate maps to MODIFY | Approvals change entity state (lifecycle transition) |
| 03-04 | CREATE/MODIFY/RECORD require confirmation | Per BOT_DESIGN.md: all approvals require human action |
| 03-04 | CONVERSE always allowed | No side effects means no safety restrictions |
| 03-04 | Only DRAFT/PROPOSED modifiable | Per BOT_DESIGN.md transition rules |
| 03-05 | Handler skeletons with placeholders | Full implementation in Phase 4 with entity system |
| 03-05 | Safety evaluation in dispatcher | Single point for safety checks before handler execution |
| 03-05 | Mode handlers as stateless singletons | Simple, thread-safe, no per-request state |
| 03-06 | RouterContext for dependency injection | Enables future context enrichment in Phase 4+ |
| 03-06 | Safe error handling with user-friendly messages | Don't expose internal errors to users |
| 04-01 | Objection events use index-based reference | Matches spec 3.9 pattern where objections are stored as list on ProposedEntity |
| 04-02 | Version increment on every transition | Event sourcing compatibility for replay |
| 04-02 | Objections indexed by position | Simpler than ID-based lookup, matches spec pattern |
| 04-03 | Aggregate emits events and updates state atomically | Consistent state changes with event sourcing |
| 04-03 | Auto-approve when 1 approval and no active objections | Default approval policy for entities |
| 04-04 | Reuse _add_approval for ApprovalAdded | DRY - method already handles JSONB append pattern |
| 04-04 | String interpolation for resolution JSON | Dynamic construction of resolution field in jsonb_set |
| 04-05 | Handlers create entities through ChannelAggregate | Consistent event emission for entity operations |
| 04-05 | Preview-before-create pattern | Show draft preview before actual entity creation |
| 04-05 | Decision type inference from keywords | Architecture, scope, constraint, priority keywords for RECORD mode |
| 04-06 | Functional API over class-based SafetyEvaluator | Simpler interface, no singleton management needed |
| 04-06 | Direct entity types in ActionContext | Use domain Entity types directly instead of intermediate EntityContext |
| 05-01 | str for EntityId/UserId in orchestration | Avoid circular imports between orchestration and domain packages |
| 05-01 | ConfigDict(frozen=False) for orchestration | Task/Workspace are mutable state containers |
| 05-01 | Flat context dict for Task | Flexible context accumulation, not stage-indexed |
| 05-02 | Deferred import in get_all_event_types() | Avoids circular import between domain and orchestration modules |
| 05-02 | Keep ALL_EVENT_TYPES as core only | Preserves backward compatibility, get_all_event_types() provides complete registry |
| 05-03 | Flows are guides not enforcers | Suggested context is a hint, only required_context must be present |
| 05-03 | Frozen dataclass for FlowTemplate | Immutable and hashable flow definitions |
| 05-03 | CONVERSE as default fallback | Unknown flow types default to CONVERSE for flexible conversation |
| 05-04 | Protocol type for LLM dependency | Optional LLM injection via Protocol for flexibility |
| 05-04 | Actions are immutable dataclasses | Orchestrator returns commands, caller executes |
| 05-05 | WORKSPACE before PROCESS in PreGates | New model takes precedence, backwards compat maintained |
| 05-06 | Dual data structures in projection | Workspace dict + thread-to-channel lookup for O(1) checks |
| 06-01 | asyncio.to_thread() for JiraClient | Wrap sync atlassian-python-api for async compatibility |
| 06-01 | tenacity for rate limit handling | Exponential backoff with jitter for Jira 429 responses |
| 06-01 | Frozen dataclasses for Jira models | Immutable models for thread safety |
| 06-02 | Duplicate detection MANDATORY before create | Per user requirement to prevent duplicate Jira issues |
| 06-02 | Decisions project as comments | Decisions append to linked work item's Jira issue |
| 06-02 | Field ownership determines conflict behavior | JIRA_OWNED/SHARED trigger conflicts; SLACK_OWNED always updatable |
| 06-03 | CommitHandler returns CommitResult dataclass | Structured results allow UI to handle each status appropriately |
| 06-03 | Slack handlers are placeholders with TODOs | Full wiring requires entity projection and channel config (Phase 7) |
| 06-03 | Limit duplicate display to 5 candidates | UX constraint - Slack actions block has element limits |
| 06-04 | ReconciliationReport uses tuple for immutability | Frozen dataclass pattern for thread safety |
| 06-04 | Group discrepancies by entity in UI | Show max 5 entities to prevent Slack block overflow |
| 06-04 | Resolution handlers are placeholders | Ready for wiring with entity projection in Phase 7 |

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-02-02
Stopped at: Completed 06-05-PLAN.md (BOT_DESIGN.md Jira section)
Resume file: None
Next action: Plan Phase 7 (Integration & Polish)

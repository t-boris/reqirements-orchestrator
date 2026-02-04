# MARO 2.1

## What This Is

MARO (Multi-Agent Requirements Orchestrator) is a Slack bot that treats communication as the source of truth. It transforms channel conversations into structured work items and architectural decisions, then projects them to Jira as execution artifacts. Features structured LLM interaction with button rendering, full decision lifecycle management, and intent observability.

## Core Value

**Thread -> Channel -> Jira flow must work flawlessly.** Conversations propose, channels decide through approvals, Jira executes. This is the single path that transforms messy discussions into actionable work.

## Requirements

### Validated

- [x] Event-sourced state management with single EventStore - v2.0
- [x] Unified ChannelEntity model (Draft -> Proposed -> Approved -> Committed) - v2.0
- [x] 4 SuperModes: CREATE, MODIFY, RECORD, CONVERSE - v2.0
- [x] 2-stage intent classification (PreGates + Router) - v2.0
- [x] Process/Plan/Workflow orchestration - v2.0
- [x] Multi-user support with approvals and objections - v2.0
- [x] Slack integration (Bolt) with proper message routing - v2.0
- [x] Jira projection for approved entities - v2.0
- [x] Decision conflict detection - v2.0
- [x] LLM abstraction (Gemini default, OpenAI/Anthropic adapters) - v2.0
- [x] Structured LLM questions with Slack button rendering - v2.1
- [x] Intent audit logging with classification chain tracking - v2.1
- [x] Deterministic post-filters preventing entity_id hallucination - v2.1
- [x] /maro inspect observability command - v2.1
- [x] Decision lifecycle: record, amend, deprecate with audit trail - v2.1
- [x] Jira notifications on decision changes (async via outbox) - v2.1
- [x] ADR pinned messages with lifecycle UI (status badges + action buttons) - v2.1
- [x] Dashboard with all decision state indicators and overflow handling - v2.1

### Active

(None - all v2.1 requirements shipped)

### Out of Scope

- **v1.x data migration** - Fresh start, no migration tooling
- **Multiple Jira projects** - Single project connection
- **Web UI** - Slack-only interface
- **Complex permission models** - Default: everyone can propose/approve
- **adr_message_ts cleanup on work items** - ISS-002 deferred (harmless dead weight)

## Context

**Current State:** v2.1 shipped with 13,618 lines of Python. 10 phases, 49 plans completed across 2 milestones.

**Tech Stack:** Python 3.12, FastAPI, Slack Bolt, PostgreSQL 16, Pydantic v2, LiteLLM, asyncpg, Alembic

**Reference Implementation:** `../reqirements-orchestrator-old/` contains v1.x codebase for reference patterns.

**Spec Document:** `docs/maro_2_0.md` is the comprehensive architecture specification (133KB).

**Key architectural shifts from v1.x:**
- 8 independent stores -> Single event-sourced store with outbox pattern
- 6 intent layers, 13 intents -> 2 stages, 4 modes + deterministic post-filters
- Separate Draft/Decision/WorkItem -> Unified ChannelEntity with sum types
- Ad-hoc orchestration -> Process -> Plan -> Workflow
- 7 parallel state machines -> 1 unified lifecycle (Draft -> Proposed -> Approved -> Committed -> Deprecated)

**Environment:** Credentials available in v1.x `.env` (Slack, Jira, LLM APIs).

## Constraints

- **Tech Stack**: Python 3.12, FastAPI, Slack Bolt, PostgreSQL 16, Pydantic v2
- **LLM**: Gemini default (cost-effective), with OpenAI/Anthropic adapters
- **Deployment**: Existing GCE VM infrastructure from v1.x
- **Credentials**: Reuse v1.x Slack app, Jira connection, API keys
- **Testing**: pytest + hypothesis for property-based testing

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Event sourcing over CRUD | Single source of truth, audit trail, rebuilding state | Good |
| Sum types for entities | Make illegal states unrepresentable | Good |
| 4 SuperModes only | Simplify from 13 intents, clearer mental model | Good |
| Channel as aggregate root | All mutations through channel, consistent boundaries | Good |
| Gemini default LLM | Cost-effective for classification | Good |
| Mandatory duplicate detection | Prevent duplicate Jira issues | Good |
| Field ownership model | Clear conflict detection semantics | Good |
| Decision data in action.value JSON | Decouple block format from data flow, eliminate brittle parsers | Good |
| Fixed action_id + entity in value | Exact string match vs regex, cleaner handler dispatch | Good |
| JiraNotificationProjection via outbox | Decouple external API calls from Slack handlers, 3s ack window | Good |
| Approvals preserved on amendment | Domain intentionally keeps approvals through content changes | Good |
| adr_message_ts in entities_view column | Read model consistency with aggregate state | Good |

---
*Last updated: 2026-02-04 after v2.1 milestone*

# MARO 2.0

## What This Is

MARO (Multi-Agent Requirements Orchestrator) is a Slack bot that treats communication as the source of truth. It transforms channel conversations into structured work items and architectural decisions, then projects them to Jira as execution artifacts. Complete rewrite from v1.x with event-sourced architecture.

## Core Value

**Thread → Channel → Jira flow must work flawlessly.** Conversations propose, channels decide through approvals, Jira executes. This is the single path that transforms messy discussions into actionable work.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Event-sourced state management with single EventStore
- [ ] Unified ChannelEntity model (Draft → Proposed → Approved → Committed)
- [ ] 4 SuperModes: CREATE, MODIFY, RECORD, CONVERSE
- [ ] 2-stage intent classification (PreGates + Router)
- [ ] Process/Plan/Workflow orchestration
- [ ] Multi-user support with approvals and objections
- [ ] Slack integration (Bolt) with proper message routing
- [ ] Jira projection for approved entities
- [ ] Decision conflict detection
- [ ] LLM abstraction (Gemini default, OpenAI/Anthropic adapters)

### Out of Scope

- **v1.x data migration** — Fresh start, no migration tooling
- **Multiple Jira projects** — Single project connection for v2.0
- **Web UI** — Slack-only interface
- **Complex permission models** — Default: everyone can propose/approve

## Context

**Reference Implementation:** `../reqirements-orchestrator-old/` contains v1.x codebase for reference patterns.

**Spec Document:** `docs/maro_2_0.md` is the comprehensive architecture specification (133KB).

**Key architectural shifts from v1.x:**
- 8 independent stores → Single event-sourced store
- 6 intent layers, 13 intents → 2 stages, 4 modes
- Separate Draft/Decision/WorkItem → Unified ChannelEntity
- Ad-hoc orchestration → Process → Plan → Workflow
- 7 parallel state machines → 1 unified lifecycle

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
| Event sourcing over CRUD | Single source of truth, audit trail, rebuilding state | — Pending |
| Sum types for entities | Make illegal states unrepresentable | — Pending |
| 4 SuperModes only | Simplify from 13 intents, clearer mental model | — Pending |
| Channel as aggregate root | All mutations through channel, consistent boundaries | — Pending |
| Statecharts over LangGraph | Composable machines, better debugging | — Pending |

---
*Last updated: 2026-02-02 after initialization*

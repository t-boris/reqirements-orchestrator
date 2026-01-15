# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-14)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.
**Current focus:** v1.0 shipped — planning v1.1

## Current Position

Phase: 11 of 12 (Conversation History)
Plan: 3 of 3 in current phase (COMPLETE)
Status: Phase 11 complete
Last activity: 2026-01-15 — Completed 11-03-PLAN.md

Progress: ████████████████████ 100% (Phase 11)

## v1.0 Summary

**Shipped:** 2026-01-14

**Stats:**
- 10 phases, 43 plans completed
- 84 Python files, 13,248 LOC
- 24 days development (Dec 22 → Jan 14)
- 236 commits

**What shipped:**
- Thread-first Slack bot with Socket Mode
- LangGraph ReAct agent (extraction → validation → decision)
- Multi-provider LLM (Gemini, OpenAI, Anthropic)
- Skills: ask_user, preview_ticket, jira_create, jira_search
- Channel context from pins
- Dynamic personas (PM/Architect/Security)
- Docker deployment to GCE VM

## Next Milestone: v1.1 Context

**Planned phases:**
- Phase 11: Conversation History — fetch messages before @mention
- Phase 12: Onboarding UX — improve first-time experience

**Deferred from v1.0:**
- Conversation history fetching (bot only sees @mention message)
- `/help` command UX improvements

## Accumulated Context

### Decisions

All v1.0 decisions logged in PROJECT.md Key Decisions table.

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 11-02 | Preserve summary/buffer on disable | Allows context to persist if re-enabled later |
| 11-02 | UPSERT for enable operation | Handles new and re-enable cases in one operation |
| 11-03 | Pre-graph context injection | Context available to all nodes without individual fetches |
| 11-03 | Buffer 30, keep 20 raw, compress 10+ | Balance token cost vs context quality |

### Deferred Issues

- Onboarding: Better intro when bot joins channel

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-15
Stopped at: Completed 11-03-PLAN.md (Handler Integration)
Resume file: None
Next action: Phase 12 (Onboarding UX) or v1.1 milestone wrap-up

## Phase 11 Summary (Complete)

**3 plans in 2 waves — ALL COMPLETE:**

Wave 1 (parallel):
- 11-01: History Fetching Service — `fetch_channel_history()`, `fetch_thread_history()`, `ConversationContext` [DONE]
- 11-02: Channel Listening State — DB model, `ListeningStore`, `/maro enable|disable|status` [DONE]

Wave 2:
- 11-03: Handler Integration — AgentState extension, context injection, rolling summary updates [DONE]

**Phase 11 accomplishments:**
- Two-layer context pattern (raw messages + compressed summary)
- Listening-enabled channels maintain rolling context
- Non-listening channels fetch on-demand at @mention
- Context injected into AgentState before graph runs

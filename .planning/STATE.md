# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.
**Current focus:** v1.2 Developer Experience — Phase 25: WorkItem-Centric Architecture

## Current Position

Phase: 26-context-aware-intent
Plan: 0 of 4 plans
Status: Planned (ready to execute)
Last activity: 2026-01-22 — Phase 26 plans created

Progress: ░░░░░░░░░░ 0% (v1.2 Phase 26)

## Milestones Summary

| Version | Name | Phases | Plans | Status | Shipped |
|---------|------|--------|-------|--------|---------|
| v1.0 | MVP | 1-10 | 43 | ✅ Complete | 2026-01-14 |
| v1.1 | Communication as Source of Truth | 11-23.5 | 63 | ✅ Complete | 2026-01-20 |
| v1.2 | Developer Experience | 24+ | 3+ | 🚧 In Progress | - |

**Total:** 28 phases, 106 plans shipped (v1.2: 3 plans ready)

## v1.1 Summary

**Shipped:** 2026-01-20

**What shipped:**
- Conversation history with two-layer context
- Intent routing (TICKET/REVIEW/DISCUSSION)
- Architecture decision auto-detection
- Brain refactor with new AgentState architecture
- Multi-ticket creation from reviews
- WorkItem registry with channel modes
- Bidirectional Jira sync with conflict detection

**Stats:**
- 18 phases, 63 plans
- 146 Python files, 34,567 LOC
- 6 days development (Jan 14 → Jan 20)

## Accumulated Context

### Key Decisions

All v1.0 and v1.1 decisions logged in MILESTONES archives and PROJECT.md.

Major v1.1 architectural decisions:
- Two-layer context (raw + compressed) for conversation history
- Pattern-first intent routing with LLM fallback
- WorkItem as first-class citizen with drafts before Jira
- Field ownership classification for bidirectional sync
- Section fingerprinting for conflict detection
- SessionStore deprecated in favor of WorkItemStore

### Deferred Issues

None — all planned v1.1 features shipped.

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-22
Stopped at: Completed 25-05-PLAN.md (State separation + dedupe reorder)
Resume file: None
Next action: Phase 25 complete. Create next phase or milestone.

## What's Next

**Phase 26: Context-Aware Intent Classification** — NOT STARTED

**Problem discovered:** Bot doesn't understand issue types structurally and confuses meta-questions about drafts with REVIEW mode.

**Components:**
- A: Add `issue_type`, `requested_scope` to TicketDraft schema
- B: Context-aware intent routing (message + state → intent)
- C: Extract issue_type and scope from user requests
- D: Draft continuity rule in decision node

**New Intent:** `DRAFT_REFINE` for refinement questions about active draft

**Next action:** Run `/gsd:execute-phase 26` to execute the 4 plans

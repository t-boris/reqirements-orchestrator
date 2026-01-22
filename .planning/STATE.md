# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.
**Current focus:** v1.2 Developer Experience — Phase 25: WorkItem-Centric Architecture

## Current Position

Phase: 25-workitem-centric
Plan: 5 of 5 plans complete
Status: Complete
Last activity: 2026-01-22 — Completed 25-05-PLAN.md (State separation + dedupe reorder)

Progress: ██████████ 100% (v1.2 Phase 25)

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

**Phase 25: WorkItem-Centric Architecture** — COMPLETE

All 5 plans executed:
- 25-01-PLAN.md: Documentation rewrite (Git model, system identity) ✅
- 25-02-PLAN.md: Intent rename + OPS intent (DEBUG/EXPLAIN) ✅
- 25-03-PLAN.md: CHANGE_REQUEST intent (diff-based updates) ✅
- 25-04-PLAN.md: ReviewArtifact persistence ✅
- 25-05-PLAN.md: State separation + dedupe reorder ✅

**Key accomplishments:**
- Git model documentation and system identity (Rules 1-20)
- OPS intent with DEBUG/EXPLAIN subtypes
- CHANGE_REQUEST intent for diff-based updates
- ReviewArtifact persistence in database
- Separated ChannelState/ThreadState with channel-first duplicate detection

**Next action:** Create next phase or milestone

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.
**Current focus:** v1.2 Developer Experience — Phase 28: Structured Draft Evolution (IN PROGRESS)

## Current Position

Phase: 28-structured-draft-evolution
Plan: 1 of ? in current phase
Status: In Progress
Last activity: 2026-01-23 — Completed 28.1-PLAN.md (StructuredDraft schema)

Progress: ██████████ 100% (Phase 27 COMPLETE) | Phase 28: 1 plan complete

## Milestones Summary

| Version | Name | Phases | Plans | Status | Shipped |
|---------|------|--------|-------|--------|---------|
| v1.0 | MVP | 1-10 | 43 | Complete | 2026-01-14 |
| v1.1 | Communication as Source of Truth | 11-23.5 | 63 | Complete | 2026-01-20 |
| v1.2 | Developer Experience | 24+ | 6+ | In Progress | - |

**Total:** 28 phases, 118 plans shipped (v1.2: 12 plans complete)

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
- 6 days development (Jan 14 -> Jan 20)

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

Phase 26 decisions:
- DRAFT_REFINE intent intercepts meta-questions about draft before review flow
- draft_refine routes to END (Slack handler processes refinement_prompt)
- _build_refinement_prompt offers type-specific scope options

Phase 27.1 decisions:
- Attribution on key fields only: title, problem, proposed_solution
- User metadata cached on @mention, non-blocking
- COALESCE for optional fields in upsert (preserve existing data)

Phase 27.2 decisions:
- Queue requests only for blocking pending_actions (not all pending states)
- Participation tracking is non-blocking (errors logged, don't fail requests)
- Max 2 @mentions per message to prevent notification spam

Phase 27.3 decisions:
- LLM semantic conflict detection (not just string comparison)
- Block draft updates until conflicts resolved
- Same-user updates allowed without conflict check
- ConflictSide stores both content and full attribution

Phase 27.4 decisions:
- JSON button payloads for state binding (replaces string concatenation)
- Ephemeral messages for approval errors (private feedback)
- Backward-compatible button parsing (supports legacy format)
- State-bound approvals prevent acting on outdated content

Phase 27.5 decisions:
- Creator becomes first owner on WorkItem creation
- Audit logging is non-blocking (failures logged, don't fail operations)
- Audit logging at skill layer (not low-level client) for full context
- Structured explain output for /maro explain command

Phase 27.6 decisions:
- MAX_MENTIONS=2 enforced in notification service
- MAX_PINGS=3 before logging as OPEN QUESTION
- Conservative actionable detection (prefer silence over spam)
- Status cards posted to channel (not thread) for visibility

Phase 28.1 decisions:
- Draft lifecycle uses explicit state machine with _VALID_TRANSITIONS
- DraftItem carries compatibility fields from TicketDraft for migration
- Bidirectional conversion (TicketDraft <-> StructuredDraft) enables gradual migration
- structured_draft field Optional in AgentState for dual-draft transition period

### Deferred Issues

None — all planned v1.2 Phase 26-27 features shipped.

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-23
Stopped at: Completed 28.1-PLAN.md (StructuredDraft schema)
Resume file: None
Next action: Execute next plan in Phase 28

## What's Next

**Phase 28: Structured Draft Evolution** — IN PROGRESS

**Objective:** Transform Draft from "text container for a ticket" to "typed, versioned design object with lifecycle states and structural mutations."

**Plans completed:**
- 28.1: StructuredDraft schema with lifecycle states and migration helpers

**Next action:** Execute next plan in Phase 28

---

### Roadmap Evolution

- 2026-01-23: Phase 28 ADDED — Structured Draft Evolution (typed, versioned design object)
- 2026-01-23: Phase 27 COMPLETE — Multi-User Support (auditable multi-user operation in channels)

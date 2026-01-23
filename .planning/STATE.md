# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.
**Current focus:** v1.2 Developer Experience — Phase 27: Multi-User Support (IN PROGRESS)

## Current Position

Phase: 27-multi-user-support
Plan: 3 of 6 in current phase (27.1, 27.2, 27.3 complete)
Status: In progress
Last activity: 2026-01-23 — Completed 27.3-PLAN.md (Multi-Author Drafts & Conflict Detection)

Progress: ██████████ 100% (v1.2 Phase 26) | Phase 27: 3/6 sub-phases

## Milestones Summary

| Version | Name | Phases | Plans | Status | Shipped |
|---------|------|--------|-------|--------|---------|
| v1.0 | MVP | 1-10 | 43 | ✅ Complete | 2026-01-14 |
| v1.1 | Communication as Source of Truth | 11-23.5 | 63 | ✅ Complete | 2026-01-20 |
| v1.2 | Developer Experience | 24+ | 4+ | 🚧 In Progress | - |

**Total:** 28 phases, 110 plans shipped (v1.2: 4 plans complete)

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

### Deferred Issues

None — all planned v1.2 Phase 26 features shipped.

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-23
Stopped at: Completed Phase 27.3 (Multi-Author Drafts & Conflict Detection)
Resume file: None
Next action: Execute Phase 27.4 (State-Bound Approvals)

## What's Next

**Phase 27: Multi-User Support** — PLANNED

**Objective:** Enable MARO to work in channels with multiple participants — track authorship, handle concurrent edits, route approvals correctly, and maintain auditability.

**Mantra:** Every statement has an author, every action has an approver, every conflict has a resolution path.

**Sub-phases:** 6 sub-phases planned
| Phase | Focus | Risk |
|-------|-------|------|
| 27.1 | User Identity & Attribution Foundation | Low |
| 27.2 | Participant Map & Turn-Taking | Medium |
| 27.3 | Multi-Author Drafts & Conflict Detection | High |
| 27.4 | State-Bound Approvals | Medium |
| 27.5 | WorkItem Ownership & Audit Log | Medium |
| 27.6 | Notifications & Slack UX | Low |

**Implementation plan:** `.planning/phases/27-multi-user-support/27-PLAN.md`
**Current sub-phase:** `.planning/phases/27-multi-user-support/27.4-PLAN.md`

**Next action:** Run `/gsd:execute-plan 27.4` to implement State-Bound Approvals

---

### Roadmap Evolution

- 2026-01-23: Phase 27 added — Multi-User Support (auditable multi-user operation in channels)

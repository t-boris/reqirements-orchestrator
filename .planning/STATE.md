# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.
**Current focus:** v1.2 Developer Experience — Phase 29: Sync on Demand (IN PROGRESS)

## Current Position

Phase: 29-sync-on-demand
Plan: 3 of 4 in current phase
Status: In Progress
Last activity: 2026-01-23 — Completed 29-03-PLAN.md (/maro sync diagnostic command)

Progress: ██████████ 100% (Phase 27 COMPLETE) | Phase 28: 6 plans | Phase 29: 3/4 plans

## Milestones Summary

| Version | Name | Phases | Plans | Status | Shipped |
|---------|------|--------|-------|--------|---------|
| v1.0 | MVP | 1-10 | 43 | Complete | 2026-01-14 |
| v1.1 | Communication as Source of Truth | 11-23.5 | 63 | Complete | 2026-01-20 |
| v1.2 | Developer Experience | 24+ | 6+ | In Progress | - |

**Total:** 29 phases, 119 plans shipped (v1.2: 13 plans complete)

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

Phase 28.2 decisions:
- DRAFT_TRANSFORM vs DRAFT_REFINE: commanding vs asking distinction
- 7 transform operations: split_to_plan, add_items, merge_items, elevate_to_epic, decompose_to_stories, change_scope, remove_items
- draft_transform_node returns action="transform_applied" for handler
- Transform requests logged to StructuredDraft change_log for audit

Phase 28.3 decisions:
- Mutation methods return dict with success/message for handler feedback
- Lifecycle transitions happen automatically within mutation methods
- LLM parameter extraction is optional - falls back to empty params on failure
- Cascading removal: removing parent removes children automatically

Phase 28.4 decisions:
- Form-dependent validation: EPIC doesn't require AC, STORY does
- Lifecycle-aware questions: PLAN stage doesn't ask AC, asks decomposition instead
- COMMITTED lifecycle is terminal - rejects further approvals
- Transitions logged to change_log for audit trail

Phase 28.5 decisions:
- InputClass enum: CHOICE/OPINION/QUESTION/ANSWER/UNCLEAR types
- LLM classification with keyword fallback for reliability
- Separate answered_questions table (not JSON in thread_state)
- 0.7 confidence threshold to record answer as definitive
- CHOICE inputs route to transform action (not discussion)

Phase 28.6 decisions:
- Text-based structure visualization (not complex visual diagrams) - simpler, mobile-friendly
- Stories indented under epics with '└─' prefix for hierarchy
- Ephemeral messages for stale approvals (private) rather than in-thread (public)
- Edit button prompts user to describe changes, routes to DRAFT_TRANSFORM intent
- Version binding: JSON payloads with {draft_id, version} in action buttons

Phase 29.1 decisions:
- Sync tracking via jira_updated (from API) vs last_synced (our fetch time)
- COALESCE pattern in register() to preserve existing data when new values None
- mark_deleted() uses DELETED_EXTERNALLY status (preserves registry history)
- get_stale_issues() returns NULLs first (never synced = most stale)

Phase 29.2 decisions:
- PreflightService takes JiraService and JiraRegistryStore as dependencies
- Always update registry on preflight (sync on read)
- IDEMPOTENT auto-succeeds, all others require user choice
- JSON button payloads contain jira_key, operation, fields for stateful handling

Phase 29.3 decisions:
- JiraSyncService uses JiraRegistryStore for local state comparison
- _find_missing_children() uses JQL parent filter for epic children
- Button payloads use JSON with channel_id and keys for stateful tracking
- Response URL used for updating original message after button click

### Deferred Issues

None — all planned v1.2 Phase 26-27 features shipped.

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-23
Stopped at: Completed 29-03-PLAN.md (/maro sync diagnostic command)
Resume file: None
Next action: Execute 29-04-PLAN.md or finalize Phase 29

## What's Next

**Phase 28: Structured Draft Evolution** — IN PROGRESS

**Objective:** Transform Draft from "text container for a ticket" to "typed, versioned design object with lifecycle states and structural mutations."

**Plans completed:**
- 28.1: StructuredDraft schema with lifecycle states and migration helpers
- 28.2: DRAFT_TRANSFORM intent with 7 operations and graph routing
- 28.3: Structural Mutation Engine (7 mutation methods implemented)
- 28.4: Lifecycle State Machine (form-dependent validation, lifecycle-aware questions)
- 28.5: User Input Classification (R3, R7, R10 - CHOICE/OPINION/QUESTION routing)
- 28.6: Structure Feedback UI (R8, R9 - version-bound visualization and stale detection)

**Next action:** Create 28.7-PLAN.md or finalize Phase 28

**Phase 29: Sync on Demand** — IN PROGRESS (3/4 plans)

**Objective:** Pull changes from Jira for all tracked tickets. Detect external modifications and update local database.

**Plans completed:**
- 29.1: JiraRegistryStore sync tracking fields (status, assignee, jira_updated, last_synced)
- 29.2: Preflight Sync service with 4-type conflict classification
- 29.3: /maro sync diagnostic command with JiraSyncService and UI blocks

**Plans remaining:**
- 29.4

**Next:** Execute 29-04-PLAN.md (if exists) or finalize Phase 29

---

### Roadmap Evolution

- 2026-01-23: Phase 28 ADDED — Structured Draft Evolution (typed, versioned design object)
- 2026-01-23: Phase 27 COMPLETE — Multi-User Support (auditable multi-user operation in channels)

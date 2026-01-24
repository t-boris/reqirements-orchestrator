# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-23)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.

**Mental model:** Decisions are versioned, Jira is a projection. Threads propose, channels decide, Jira executes.

**Current focus:** v1.2 Developer Experience — Phase 34: File Attachment Processing (IN PROGRESS)

## Current Position

Phase: 34-file-attachment-processing
Plan: 6 of 8 in current phase
Status: In progress
Last activity: 2026-01-23 — Completed 34-06-PLAN.md (Intent-Scoped Rules)

Progress: ███████░░░ 75% (Phase 34: 6/8 plans complete)

## Milestones Summary

| Version | Name | Phases | Plans | Status | Shipped |
|---------|------|--------|-------|--------|---------|
| v1.0 | MVP | 1-10 | 43 | Complete | 2026-01-14 |
| v1.1 | Communication as Source of Truth | 11-23.5 | 63 | Complete | 2026-01-20 |
| v1.2 | Developer Experience | 24+ | 6+ | In Progress | - |

**Total:** 29 phases, 121 plans shipped (v1.2: 15 plans complete)

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

Phase 29.4 decisions:
- Create preflight as duplicate detection via summary matching
- Update preflight uses PreflightService check_update()
- IDEMPOTENT auto-succeeds without UI (just message)
- Button payloads include pending_action for stateful handling
- preflight_use_jira same as pull_only; preflight_use_channel same as proceed

Phase 30.1 decisions:
- DecisionVersion stores snapshot before each update (immutable history)
- REPLACED status separate from DEPRECATED (tracks replacement chain via replaced_by field)
- Canonical message tracking for Slack pinned message pattern (canonical_message_ts, discussion_thread_ts)

Phase 30.2 decisions:
- JiraFieldPath enum with 7 values (6 decision types + CUSTOM_FIELD extension point)
- Sync tracking is per-link (each decision-ticket pair tracks its own sync version)
- Deterministic mapping via DECISION_MAPPING_RULES (no LLM involved in field selection)

Phase 30.4 decisions:
- post_canonical_message() stores ts in database for future updates
- update_canonical_message() uses chat_update (not new message) for update-in-place
- Thread binding queries by channel_id + canonical_message_ts

Phase 30.5 decisions:
- Four visual states match psychological weight: draft (compact) -> approval (heavy) -> approved (authoritative) -> commit log (ultra compact)
- Version-bound button payloads contain decision_id + version to prevent stale clicks
- Type emojis visually distinguish decision types (ARCH=brain, SCOPE=ruler, CONSTRAINT=lock, PRIORITY=lightning, STRUCTURE=construction, PROCESS=gear)

Phase 30.3 decisions:
- Pattern-first detection for DECISION intent with 0.9 confidence before LLM fallback
- 8 regex patterns for decision statements ("We decided to...", "Approved:", etc.)
- 6 decision type keyword categories map to DecisionType enum
- Title extraction removes "We decided to..." prefixes for cleaner display

Phase 30.6 decisions:
- Managed section markers: "## Decisions (managed by MARO)" start, "---" end
- Decisions use same 4-type conflict classification as regular preflight (no privileges)
- New links treated as SAFE_DRIFT with can_proceed=True (no prior state to conflict with)

Phase 30.8 decisions:
- Reused existing mark_synced and get_decisions_for_ticket methods (no new duplicates)
- register_decision_handlers pattern for clean handler registration (like register_preflight_handlers)
- Deprecate (not delete) for discard action to maintain audit trail

Phase 31.1 decisions:
- SuperMode enum with 5 values: BUILD, OPERATE, DECIDE, THINK, CHAT
- OPS intent maps to CHAT (meta-level operations)
- super_mode populated at classification time via get_super_mode()
- 13 intents exist for routing, 5 modes exist for user communication

Phase 31.2 decisions:
- ManagedSectionError for invariant violations (reject rather than recover)
- validate_section_boundaries() rejects nested markers and missing end markers
- verify_user_content_preserved() helper for test assertions
- INVARIANT docstring pattern for critical constraints

Phase 31.4 decisions:
- Commit log entries are immutable, canonical messages are mutable
- Preflight is blocking guard, /maro sync is informational diagnostic
- Both preflight and sync use same 4-type conflict classification (IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL)

Phase 32.2 decisions:
- InvariantViolation uses class attribute invariant_name (not instance)
- PreflightToken has 5-minute TTL, OverrideToken has 10-minute TTL
- CommitLogEntry uses __setattr__ override to enforce immutability at runtime
- CommitLogStore table named event_commit_log to avoid collision with existing commit_log

Phase 32.1 decisions:
- SuperMode.label returns action-oriented strings (Building, Operating, etc.)
- get_mode_status_line() formats as [Mode] action_description
- Debug mode can show intents (developer tool)
- INVARIANT I1 documented in intent.py, dispatch.py, scope_gate.py

Phase 32.3 decisions:
- UserDraftState enum with 3 values: DRAFTING, READY, PUBLISHED
- get_user_state() maps 4 internal states to DRAFTING, APPROVED to READY, COMMITTED to PUBLISHED
- INVARIANT I5: Users see 3 states only (internal complexity hidden)

Phase 32.4 decisions:
- INVARIANT I2 documented at module docstring level in handlers
- Truth-first ordering: Database (TRUTH) -> Jira (PROJECTION) -> Slack (PRESENTATION)
- All Slack message updates wrapped in try/except (best-effort presentation)
- Structured step comments to make invariant visible in code

Phase 32.5 decisions:
- Duplicated managed section parsing in tests to avoid circular imports
- Gateway allowlist: client.py, managed_sections.py, sync_service.py
- hypothesis>=6.92.0 for property-based testing in CI
- AST-based import scanning for gateway enforcement

Phase 32.6 decisions:
- Documentation follows same section structure as code implementation
- Invariant documentation includes code examples for enforcement
- Each invariant documented with meaning and enforcement mechanism

### Deferred Issues

None — all planned v1.2 Phase 26-27 features shipped.

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-23
Stopped at: Completed 34-06-PLAN.md (Intent-Scoped Rules)
Resume file: None
Next action: Execute 34-07-PLAN.md (Transparency UI)

## What's Next

**Phase 34: File Attachment Processing** — IN PROGRESS (6/8 plans)

**Objective:** Enable bot to read PDF, DOCX, MD attachments. Attachments as first-class entities with lifecycle states, pinning, and intent-scoped retrieval.

**Progress:**
- 34-01: Attachment Schema + AttachmentStore - COMPLETE
- 34-02: File Event Handler - COMPLETE
- 34-03: Extraction Pipeline - COMPLETE
- 34-04: Chunking + Search Index - COMPLETE
- 34-05: Pin/Unpin Mechanics - COMPLETE
- 34-06: Intent-Scoped Rules - COMPLETE
- 34-07: Transparency UI - PLANNED
- 34-08: Retrieval Context Injection - PLANNED

Phase 34-01 decisions:
- AttachmentStatus enum with 5 lifecycle states (pending, extracting, ready, failed, too_large)
- file_id UNIQUE constraint for idempotent creates via ON CONFLICT
- Partial indexes for status queries and pinned attachments

Phase 34-02 decisions:
- Use _run_async pattern for async handlers called from sync Bolt context
- Process both file_shared events AND message files array for complete coverage
- Non-blocking registration - errors logged but don't fail message processing
- Size limit set to 10MB (matching typical Slack file size limits)

Phase 34-03 decisions:
- LLM summary generation with 3000 char content preview
- Token estimation at 0.25 tokens per character
- Semaphore-limited concurrency (max 3) for extraction
- Fire-and-forget processing trigger (non-blocking via asyncio.create_task)

Phase 34-04 decisions:
- Use LangChain RecursiveCharacterTextSplitter (not hand-rolled)
- PostgreSQL full-text search via tsvector (simpler than embeddings)
- Chunk size 500 tokens with 50 token overlap
- Only chunk documents > 500 characters

Phase 34-05 decisions:
- Pin/unpin via button handlers with file_id in payload
- Ephemeral confirmation messages after pin/unpin actions
- Status card shown after file processing with pin/show buttons
- Attachment cards in processing completed handler (not shared event)

Phase 34-06 decisions:
- AttachmentPolicy enum with 6 policies (NONE, PINNED_ONLY, PINNED_RETRIEVAL, PINNED_STRUCTURAL, LOGS_RETRIEVAL, PINNED_CITED)
- MODE_POLICIES maps all 5 SuperModes to policies
- Token budgets: 2000 for pinned, 1500 for retrieval, top-5 chunks
- Non-blocking: attachment resolution failures logged but don't break requests

---

**Phase 33: Anchor Message Architecture** — COMPLETE (5/5 plans)

**Objective:** Shift from thread-centric to object-centric design. Canonical messages become anchors for entity lifecycles.

**Mantra:** "Thread exists for managing a specific object of reality, not for conversation."

**Key Rules (all implemented):**
- A1: Any "created/approved/updated" message is an anchor message
- A2: Each anchor has object_id and object_type
- A3: Messages in thread inherit object_id as context
- A4: Commands in thread default to the anchor's object

**Progress:**
- 33-01: AnchorMessage Schema - COMPLETE
- 33-02: Thread Bindings Persistence - COMPLETE
- 33-03: WorkItem Canonical Message Tracking - COMPLETE
- 33-04: Context Resolution - COMPLETE
- 33-05: Implicit Commands - COMPLETE

Phase 33-01 decisions:
- object_id as string to support both UUIDs (workitem) and formatted IDs (DEC-41)
- Use project's create_tables() pattern instead of alembic migrations
- UNIQUE constraint on (anchor_type, object_id, channel_id) for one anchor per object per channel

Phase 33-03 decisions:
- Optional anchor fields because legacy WorkItems don't have anchors
- Type emojis: purple=epic, blue=story, white=task, red=bug, orange=spike
- Status-based action buttons (draft vs active vs done)

Phase 33-04 decisions:
- ContextResolver uses multi-tier resolution: AnchorStore -> DecisionStore -> WorkItemStore -> ThreadBindingStore
- WorkItemStore resolution uses source_thread_ts (no canonical_message_ts field exists yet)
- ThreadContext as dataclass (not TypedDict) for property support
- resolve_thread_context() convenience function for single-use resolution

Phase 33-05 decisions:
- Thread context takes priority 2 in target resolution (after explicit ticket key)
- Implicit command patterns return 0.85 confidence in anchored thread context
- WorkItem reference format WI:uuid for workitems without Jira key
- Context-aware classification integrated at intent_router_node level

**Next action:** Phase 33 complete

---

**Phase 31: Architecture Hardening** — COMPLETE (4/4 plans)

**Objective:** Consolidate intents into super-modes, elevate safety invariants to hard rules, and simplify over-specified systems for production readiness.

**Plans completed:**
- 31.1: SuperMode enum with 5 values for user-facing simplicity
- 31.2: MANAGED_SECTION_ONLY invariant for decision projection safety
- 31.3: Slack as UI pattern (message failures don't block state)
- 31.4: Documentation updates (commit log vs state, sync semantics)

---

**Phase 28: Structured Draft Evolution** — COMPLETE

**Objective:** Transform Draft from "text container for a ticket" to "typed, versioned design object with lifecycle states and structural mutations."

**Plans completed:**
- 28.1: StructuredDraft schema with lifecycle states and migration helpers
- 28.2: DRAFT_TRANSFORM intent with 7 operations and graph routing
- 28.3: Structural Mutation Engine (7 mutation methods implemented)
- 28.4: Lifecycle State Machine (form-dependent validation, lifecycle-aware questions)
- 28.5: User Input Classification (R3, R7, R10 - CHOICE/OPINION/QUESTION routing)
- 28.6: Structure Feedback UI (R8, R9 - version-bound visualization and stale detection)

**Next action:** Create 28.7-PLAN.md or finalize Phase 28

**Phase 29: Sync on Demand** — COMPLETE (4/4 plans)

**Objective:** Pull changes from Jira for all tracked tickets. Detect external modifications and update local database.

**Plans completed:**
- 29.1: JiraRegistryStore sync tracking fields (status, assignee, jira_updated, last_synced)
- 29.2: Preflight Sync service with 4-type conflict classification
- 29.3: /maro sync diagnostic command with JiraSyncService and UI blocks
- 29.4: Preflight sync integration into handlers (draft commit, ticket updates, button handlers)

**Phase 30: Decision as First-Class Entity** — COMPLETE (8/8 plans)

**Objective:** Make Decision a versioned, linked entity that Jira projects from — not the other way around.

**Plans completed:**
- 30.1: Decision entity and DecisionStore with versioning
- 30.2: DecisionLink table for decision-to-Jira mappings
- 30.3: DECISION intent and detection patterns
- 30.4: DecisionManager with canonical message pattern
- 30.5: Decision UI blocks with four visual states
- 30.6: Decision Preflight and managed sections for safe Jira writes
- 30.7: Decision commands for /maro (list, show, change, deprecate)
- 30.8: Decision Jira Projection (DecisionSyncService, button handlers)

**Next:** Phase 30 COMPLETE

---

### Roadmap Evolution

- 2026-01-24: Phase 34 ADDED — File Attachment Processing (read PDF/DOCX/MD from Slack messages)
- 2026-01-24: Phase 33 COMPLETE — Anchor Message Architecture (5/5 plans)
- 2026-01-24: Phase 33 ADDED — Anchor Message Architecture (threads exist for objects, not conversation)
- 2026-01-24: Phase 32 COMPLETE — Product Invariants (6/6 plans)
- 2026-01-24: Phase 32 ADDED — Product Invariants (enforce architectural principles as hard rules)
- 2026-01-24: Phase 31 COMPLETE — Architecture Hardening (4/4 plans)
- 2026-01-23: Phase 31 ADDED — Architecture Hardening (super-modes, invariants, simplification)
- 2026-01-23: Phase 30 COMPLETE — Decision as First-Class Entity (8/8 plans)
- 2026-01-23: Phase 30 ADDED — Decision as First-Class Entity (versioned decisions, Jira as projection)
- 2026-01-23: Phase 28 ADDED — Structured Draft Evolution (typed, versioned design object)
- 2026-01-23: Phase 27 COMPLETE — Multi-User Support (auditable multi-user operation in channels)

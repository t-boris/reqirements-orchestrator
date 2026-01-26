# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-23)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.

**Mental model:** Decisions are versioned, Jira is a projection. Threads propose, channels decide, Jira executes.

**Current focus:** v1.2 Developer Experience — Phase 43 planning complete

## Current Position

Phase: 43-task-progress-ux
Plan: 2 of 4 in current phase
Status: In progress
Last activity: 2026-01-26 — Completed 43-02-PLAN.md (Specific Action Feedback)

Progress: ██░░░░░░░ 2/4 plans

## Milestones Summary

| Version | Name | Phases | Plans | Status | Shipped |
|---------|------|--------|-------|--------|---------|
| v1.0 | MVP | 1-10 | 43 | Complete | 2026-01-14 |
| v1.1 | Communication as Source of Truth | 11-23.5 | 63 | Complete | 2026-01-20 |
| v1.2 | Developer Experience | 24+ | 6+ | In Progress | - |

**Total:** 30 phases, 130 plans shipped (v1.2: 24 plans complete)

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

Phase 35-01 decisions:
- Tasks stored as JSONB array in task_plans table (not separate table)
- Optimistic locking via version check on update
- SafetyLevel maps from SuperMode: THINK/CHAT -> AUTO_EXECUTE, BUILD/OPERATE/DECIDE -> REQUIRES_CONFIRMATION
- TaskPlan.compute_status() derives plan status from aggregate task statuses

Phase 35-02 decisions:
- Two-stage classification: single-intent first, multi-intent if signals detected
- Multi-intent signals: conjunctions ("and", "also", "plus"), low confidence (<0.7), multiple action verbs (>=2)
- TaskPlanProposal wraps multiple TaskProposals with dependency tracking
- Backwards compatible via return_proposal=False default and to_single_intent()

Phase 35-03 decisions:
- MODE_SAFETY_MAP: THINK/CHAT → AUTO_EXECUTE, BUILD/OPERATE/DECIDE → REQUIRES_CONFIRMATION
- INTENT_SAFETY_OVERRIDES for specific intents (DRAFT_REFINE/DRAFT_TRANSFORM are AUTO_EXECUTE)
- JIRA side effect always forces REQUIRES_CONFIRMATION regardless of mode
- create_task_with_inferred_safety() factory for properly classified tasks

Phase 35-04 decisions:
- task_plan field added to AgentState TypedDict (Optional[TaskPlan])
- task_decomposer_node converts TaskPlanProposal to persisted TaskPlan
- Graph routes to task_decomposer when is_multi_intent=True detected in proposal
- Dependency indices resolved to task_ids after all tasks created

Phase 35-05 decisions:
- task_executor_node processes tasks recursively until blocked or done
- Auto-executable tasks run immediately, dangerous tasks block for confirmation
- handle_task_approval with version check for idempotency (rejects stale approvals)
- _cascade_cancel propagates rejections to dependent tasks

Phase 35-06 decisions:
- TaskStatusUpdater with 1.5s throttling to avoid Slack rate limits
- SIGNIFICANT_EVENTS (task_started/completed/blocked/failed, plan_completed/canceled) bypass throttle
- Status card shows plan header, task list with emoji status, control buttons
- build_multi_intent_announcement for canonical "I see N actions" UX

Phase 35-07 decisions:
- Button value format includes version: "{plan_id}:{task_id}:{version}" for task actions
- Stale actions rejected with ephemeral message + card refresh
- register_task_plan_handlers(app) pattern for clean handler registration
- validate_task_action/validate_plan_action helpers for consistent validation

Phase 35-08 decisions:
- 5 new dispatch actions: task_plan_created, task_confirmation_required, task_plan_complete, task_plan_blocked, task_failed
- intent_router_node calls classify_intent with return_proposal=True for multi-intent
- task_decomposer returns decision_result with action="task_plan_created"
- End-to-end flow: multi-intent → decompose → post card → execute/block → complete

Phase 37-01 decisions:
- Protocol pattern for QuestionProvider (not ABC) - enables structural subtyping
- ReviewState mirrors WorkItemDraft as FreeformProvider target
- OpenQuestion tracks maps_to field for answer routing

Phase 37-02 decisions:
- CatalogProvider wraps QuestionCatalog (composition over inheritance)
- Priority order: scope -> conflict -> required fields -> optional fields
- Required fields: title, problem; Optional: acceptance_criteria, proposed_solution

Phase 37-03 decisions:
- FreeformProvider uses ASK_USER question type for all generated questions
- Fallback questions provided when LLM parsing fails for reliability
- Output maps to ReviewState fields: assumptions, constraints, risks

Phase 37-04 decisions:
- AnswerMapper uses target_type parameter (not separate methods)
- ReviewState fields route to structured LLM extraction prompts
- ReviewStateStore follows TaskPlanStore pattern (conn-based, not pool)

Phase 37-05 decisions:
- QuestionEngine wraps both providers with unified interface
- Intent detection (_wants_questions_asked) happens BEFORE LLM call for determinism
- FreeformProvider generates structured questions for review flow

## Session Continuity

Last session: 2026-01-26
Stopped at: Completed 43-02-PLAN.md (Specific Action Feedback)
Resume file: None
Next action: Execute 43-03-PLAN.md (Elapsed Time Indicator)

Phase 39-01 decisions:
- IntentEnvelope unified output format with kind: single/plan/ambiguous
- RiskLevel enum ordering for max calculation in plan factory
- to_legacy_intent_result() enables gradual migration from IntentResult

Phase 39-02 decisions:
- Pre-gates are state-based invariants, NOT keyword pattern matching
- 4 gate types: terminal, taskplan continuation, draft priority, risk guard
- Gate 4 (risk guard) runs AFTER LLM classification, not in pre-gate phase
- run_pre_gates() applies gates in priority order, returns first triggered

Phase 39-03 decisions:
- Minimal STAGE1_PROMPT for speed (short, no heavy context)
- ModeCandidate with mode + score (not just top-1)
- Stage1Result exposes top_mode, top_score, margin as properties
- Fallback to CHAT with 0.5 score on parse errors
- get_stage2_hints bridges Stage 1 output to Stage 2 input

Phase 39-04 decisions:
- MODE_INTENTS maps SuperMode to valid intents (restricts LLM choices)
- INTENT_RISK classifies each intent for safety (SAFE/WRITE/MASS_WRITE/DESTRUCTIVE)
- _build_plan_envelope sorts tasks by risk (safe reads before writes)
- Deterministic Jira key extraction via JIRA_KEY_PATTERN regex (not LLM)
- build_target_hints combines anchor-based and message-based targets

Phase 39-05 decisions:
- Policy order: target ambiguity -> risk guard -> margin/confidence
- Risk guard triggers ambiguous for SINGLE, requires_confirm for PLAN
- _convert_to_ambiguous includes original intent + alternatives + safe fallback

Phase 39-06 decisions:
- route_intent() orchestrates Stage 0 -> 1 -> 2 -> Policy in sequence
- Stage 0 bypass creates deterministic envelope with confidence=1.0
- Stage 0 constraints boost priority modes by 0.2 score
- Context built using ContextSpec.for_extraction() when channel+thread available
- route_after_intent routes by envelope kind then by mode/intent
- Terminal intents are DISCUSSION and META (CHAT mode)

Phase 39-07 decisions:
- Terminal intents (DISCUSSION, META) route to terminal_response_node then END
- classify_intent_v2 wraps intent_router_node and returns both envelope and legacy intent_result
- get_intent_classifier(use_v2=False) factory defaults to legacy for safe gradual migration
- Documentation updated with Phase 39 architecture in architecture.md and HOW_THE_BOT_THINKS.md

Phase 38-01 decisions:
- ReviewArtifact stored in review_artifacts table (not checkpoint-only)
- DB is source of truth, checkpoint is cache
- CRUD operations follow existing store patterns (ThreadStateStore, DecisionStore)

Phase 38-02 decisions:
- BlockRenderer handles 9 block types: section, actions, context, header, divider, rich_text, input, image, video
- render_blocks() convenience function with singleton pattern
- Unknown blocks fallback to "[{type} block]" placeholder

Phase 38-03 decisions:
- ContextSpec is goal-driven: mode, target, purpose, budget_tokens
- Factory methods for common cases: for_extraction(), for_review(), for_ops_explain()
- ContextPacket.to_prompt() formats with "=== SECTION ===" headers

Phase 38-04 decisions:
- NormalizedMessage dataclass with message_type (user/bot/system)
- MessageIndex uses LRU cache (max 1000 entries)
- Bot messages with blocks get rendered_text via BlockRenderer

Phase 38-05 decisions:
- Three-layer context: Layer A (canonical), Layer B (history), Layer C (retrieved)
- Token budget enforcement with prioritized truncation
- build_context() convenience function exported from src.context

Phase 38-06 decisions:
- OPS EXPLAIN uses ContextBuilder instead of build_explain_output() state dump
- context_packet field added to AgentState for graph propagation
- Handler builds context packet optionally (opt-in, not breaking change)

Phase 40-01 decisions:
- Structured models (RationaleItem, Alternative, Consequence) for rich context
- RationaleItem has optional weight (primary/secondary) for importance
- Consequence has optional severity (minor/moderate/major) for impact
- DecisionVersion uses list[dict] instead of models for JSON serialization
- All rich context fields Optional for backward compatibility

Phase 40-02 decisions:
- context_before column name in DB (context is SQL keyword), maps to context in model
- JSONB columns for rationale, alternatives, consequences (structured data)
- ALTER TABLE ADD COLUMN IF NOT EXISTS for backward-compatible migrations
- psycopg.types.json.Json wrapper for JSONB serialization
- Version history preserves rich context when decisions are updated

Phase 41-01 decisions:
- 6 lifecycle states: PROPOSED, CONFIRMED, APPLYING, DONE, FAILED, CANCELLED
- State transitions validated via VALID_TRANSITIONS map
- ImpactSummary captures jira_keys, pinned_artifacts, conflict_count, total_affected
- DecisionStore.create_change_op() helper for tracked decision changes

Phase 41-02 decisions:
- ImpactTicket captures per-ticket sync_status, conflict_type, and message
- Risk levels: none (0 affected), low (1-3 safe), medium (4-10 OR pending), high (10+ OR conflicts)
- DEPRECATE operation always has_jira_writes=True (clears managed sections)
- analyze_and_update_op() convenience function for workflow integration

Phase 41-03 decisions:
- Impact preview card shows operation type, version, and affected ticket counts
- Three confirmation buttons: Apply updates (Jira), Apply to Slack only, Cancel
- DEPRECATE operation always shows confirmation (has_jira_writes=True)
- EDIT shows confirmation only if has_jira_writes, else auto-confirms
- Conflict details limited to 5 tickets with messages
- High risk warning context block for operations with risk_level="high"

Phase 41-04 decisions:
- Truth-first ordering: DB (truth) -> Slack (presentation) -> Jira (projection)
- Slack failures are logged but don't abort operations (best-effort presentation)
- Per-ticket results (ApplyTicketResult) enable granular retry capability
- Result card shows three phases: db_updated, slack_updated, jira_updated
- Retry handler (decision_change_retry) for failed ticket recovery

Phase 41-05 decisions:
- Rollback only affects Jira, database state preserved
- Rollback button requires confirmation dialog
- Retry handler validates FAILED state before executing
- Deprecation notice auto-detected from decision status

## What's Next

**Phase 43: Task Progress UX** — IN PROGRESS (2/4 plans)

**Objective:** Improve task progress feedback so users always know what MARO is working on.

**Plans:**
- 43-01: Single-Task Status Card Display — COMPLETE
- 43-02: Specific Action Feedback — COMPLETE
- 43-03: Elapsed Time Indicator — PENDING
- 43-04: Visual State Transition Feedback — PENDING

**Wave structure:**
- Wave 1: 43-01, 43-02 (no dependencies, can run in parallel) — COMPLETE
- Wave 2: 43-03 (depends on 43-02 for combined display)
- Wave 3: 43-04 (depends on 43-02, 43-03)

Phase 43-02 decisions:
- Active step displayed with em dash separator: "Generate stories — Parsing requirements"
- Step text should be concise (<40 chars) for clean UI display
- Step changes use regular throttling (not bypassing like significant events)
- Intent-specific step descriptions in task executor

---

**Phase 41: Decision Change Propagation** — COMPLETE (5/5 plans)

**Objective:** Track decision changes through impact analysis, confirmation UI, transactional apply, and rollback support.

**Progress:**
- 41-01: DecisionChangeOp Schema + Store - COMPLETE
- 41-02: Impact Analysis - COMPLETE
- 41-03: Confirmation UI - COMPLETE
- 41-04: Transactional Apply - COMPLETE
- 41-05: Rollback Support - COMPLETE

**What shipped:**
- DecisionChangeOp model with 6 lifecycle states
- DecisionChangeOpStore with CRUD and state machine validation
- ImpactSummary model for tracking affected entities
- DecisionStore integration via create_change_op() helper
- ImpactAnalysisService with preflight-based analysis
- ImpactTicket model for per-ticket impact details
- Risk level computation (none/low/medium/high)
- Impact preview card UI (build_impact_preview_card)
- Confirmation button handlers (Apply updates, Apply to Slack only, Cancel)
- Integration with decision change/deprecate modal handlers
- ApplyResult and ApplyTicketResult models for execution tracking
- DecisionChangeExecutor with truth-first ordering
- Result card UI (build_change_result_card) with retry button
- Handler integration connecting confirmation to executor
- DecisionRollbackService for reverting Jira managed sections
- Rollback button with confirmation dialog
- Deprecation notice format in managed sections

**Next action:** Plan next phase or add new phase

---

**Phase 34: File Attachment Processing** — COMPLETE (8/8 plans)

**Objective:** Enable bot to read PDF, DOCX, MD attachments. Attachments as first-class entities with lifecycle states, pinning, and intent-scoped retrieval.

**Progress:**
- 34-01: Attachment Schema + AttachmentStore - COMPLETE
- 34-02: File Event Handler - COMPLETE
- 34-03: Extraction Pipeline - COMPLETE
- 34-04: Chunking + Search Index - COMPLETE
- 34-05: Pin/Unpin Mechanics - COMPLETE
- 34-06: Intent-Scoped Rules - COMPLETE
- 34-07: Transparency UI - COMPLETE
- 34-08: Prompt Integration - COMPLETE

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

Phase 34-07 decisions:
- Transparency footer uses context block for "Used:" text, actions block for buttons
- Sources modal displays up to 5 chunks per file, truncated at 1000 chars
- Stop using button delegates to existing unpin handler (code reuse)
- Created response.py module with post_response helper (separation of concerns)

Phase 34-08 decisions:
- Call resolve_attachment_context in intent_router_node after classification
- Trim retrieved_chunks before pinned when enforcing token budget (pinned is user choice)
- Store super_mode in state for downstream nodes (review uses for cite mode)
- Default max_total_tokens=4000 to prevent context explosion

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

- 2026-01-26: Phase 43 ADDED — Task Progress UX (always show task list, specific action feedback, elapsed time)
- 2026-01-26: Phase 42 COMPLETE — Code Modularization (9/9 plans, 14 files split into packages)
- 2026-01-26: Phase 42 ADDED — Code Modularization (split 23 files >600 lines into logical components)
- 2026-01-26: Phase 41 ADDED — Decision Change Propagation (impact analysis, confirmation UI, transactional apply, rollback support)
- 2026-01-25: Phase 40 ADDED — Decision v2: Rich Context & Versioning (rationale, context, alternatives, consequences, DecisionHead/Version split)
- 2026-01-25: Phase 39 ADDED — Intent Classification v2 (2-stage architecture, state gates, unified IntentEnvelope, margin-based ambiguity)
- 2026-01-25: Phase 38 ADDED — Context Architecture (goal-driven context building, three-layer model)
- 2026-01-24: Phase 37 COMPLETE — Unified Question Engine (5/5 plans, QuestionEngine facade + review integration)
- 2026-01-24: Phase 37 ADDED — Unified Question Engine (one mechanism, two providers: CatalogProvider for tickets, FreeformProvider for review)
- 2026-01-24: Phase 36 COMPLETE — Question Engine: Conversation Driver (7/7 plans, 4 waves)
- 2026-01-24: Phase 36 CONTEXT GATHERED — Question Engine vision documented (questions as tasks, active/passive mode, question budget, hybrid catalog/mapper)
- 2026-01-24: Phase 36 ADDED — Question Engine: Conversation Driver (questions as first-class tasks)
- 2026-01-24: Phase 35 COMPLETE — Multi-Intent Task Orchestration (8/8 plans, 4 waves)
- 2026-01-24: Phase 35-01 COMPLETE — TaskPlan/Task schemas, TaskPlanStore persistence
- 2026-01-24: Phase 35 RESEARCHED — Multi-Intent Task Orchestration (architecture gaps identified, integration points documented)
- 2026-01-24: Phase 35 ADDED — Multi-Intent Task Orchestration (TaskPlan replaces single-intent classification)
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

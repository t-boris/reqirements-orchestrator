# Issues

Deferred issues discovered during code review and development.

## Open

_No open issues_

## Closed

### ISS-015: Bot doesn't understand compound requests (analyze X and create Y)

**Source:** Production usage (2026-02-05)
**Severity:** Functional gap / core UX
**Closed:** 2026-02-05

Fixed: Implemented plan-based execution system for compound requests. Added `PlanStep` and `ExecutionPlan` schemas to `schemas.py`. Updated intent prompts to detect compound requests (`is_compound_request` field). Added `generate_execution_plan()` to `router.py` that detects patterns like "analyze X and create Y" and generates multi-step plans. Updated `ModeDispatcher` with `_execute_plan()` method that executes steps sequentially, passing context between them. Added `plan_step_context` and `is_plan_step` fields to `ModeContext`. Updated CREATE mode with `_create_batch_from_plan_context()` that uses ARCHITECT's analysis to generate batch work items.

### ISS-014: CONVERSE mode has no entity awareness

**Source:** Production usage (2026-02-05)
**Severity:** Functional gap / core UX
**Closed:** 2026-02-05

Fixed: Added `_build_entity_context()` to `ConverseModeHandler` (same pattern as ARCHITECT mode). Updated `CONVERSE_SYSTEM` prompt to instruct LLM to check existing entities when answering questions about ADRs, decisions, work items, and duplication. Updated `CONVERSE_USER` template with `{entity_context}` placeholder. LLM now receives full entity list (title, type, state, rationale/description) and can answer questions about existing entities directly.

### ISS-011: No way to discard/delete a Draft or Proposed ADR

**Source:** Production usage (2026-02-05)
**Severity:** UX gap / functional
**Closed:** 2026-02-05

Fixed: Added `DecisionDiscarded` event, `discard_decision()` aggregate method, "Discard" button on Draft and Proposed ADR pinned messages, `adr_discard` lifecycle handler that removes entity from aggregate, updates pinned message to ":x: Discarded" state with no buttons, unpins the message, and refreshes the dashboard. Projection DELETEs entity from `entities_view`.

### ISS-013: CREATE mode has no awareness of existing entities and can't batch-create work items

**Source:** Production usage (2026-02-05)
**Severity:** Functional gap / core UX
**Closed:** 2026-02-05

Fixed: Added `ExtractedWorkItems` batch schema, `_build_entity_context()` method (reuses ARCHITECT pattern), batch intent detection via regex patterns, `_create_batch_work_items_preview()` with entity-aware LLM prompt, and `_build_work_items_preview_blocks()` for multi-item preview with per-item Propose/Delete buttons and global Propose All/Cancel All. Action handlers added: `WORK_ITEM_PREVIEW_PATTERN` for per-item actions, `WORK_ITEM_BATCH_PATTERN` for global actions, plus `_propose_single_work_item()` and `_propose_all_work_items()` helpers.

### ISS-012: Channel Status dashboard truncates items with no way to expand

**Source:** Production usage (2026-02-05)
**Severity:** UX gap
**Closed:** 2026-02-05

Fixed: Added "Show all items" button to dashboard when any section overflows its display limit. Button click handler (`dashboard_show_all`) loads the aggregate and posts a full untruncated list as a thread reply on the dashboard message, grouped by section (active decisions, deprecated decisions, pending work items, approved, committed).

## Closed

### ISS-002: `adr_message_ts` field on work item entities is dead weight

**Source:** Code review (2026-02-04)
**Severity:** Minor / design smell
**Closed:** 2026-02-05 (acknowledged — not worth migration risk)

The field is `None` on work items and costs nothing at runtime. Removing it from entity types would require schema migration of all 5 frozen entity types plus transitions.py, projections.py, serialization.py — high churn, zero functional benefit.

### ISS-009: Bot responds to every message — no "should I respond?" gate

**Source:** Production testing (2026-02-04)
**Severity:** Critical / UX + functional
**Closed:** 2026-02-04

Fixed: Added `src/slack/response_gate.py` with `BotThreadTracker` (in-memory + negative cache) and `check_response_gate()` implementing 3-tier bot thread detection: in-memory set, entity store query, Slack API fallback. Gate allows DMs, bot threads, and entity threads; blocks top-level channel messages and threads without bot participation. Wired into `handle_message` before intent classification.

### ISS-010: Thread context not fetched in handle_message

**Source:** Production testing (2026-02-04)
**Severity:** Critical / functional gap
**Closed:** 2026-02-04

Fixed: `handle_message` now fetches `conversations_replies(limit=50)` when `thread_ts` is present, builds `thread_messages` and `thread_summary`, and passes both to `RouterContext` and `dispatch_mode()`. Same pattern as `handle_app_mention`. Bot participation recorded via `BotThreadTracker` after every `say()` call across event and action handlers.

### ISS-003: Block parsers are brittle — coupled to mrkdwn format

**Source:** Code review (2026-02-04)
**Severity:** Fragility / maintainability
**Closed:** 2026-02-04 (Plan 10-01)

Fixed: Deleted `_parse_record_mode_preview()` and `_parse_amend_preview()`. Decision data now stored as JSON in `action.value`. Handlers use `json.loads()` instead of mrkdwn string parsing.

### ISS-004: Entity IDs embedded in action_id instead of value

**Source:** Code review (2026-02-04)
**Severity:** Minor / convention
**Closed:** 2026-02-04 (Plan 10-01)

Fixed: Deprecation buttons use fixed `action_id` ("deprecate_decision", "confirm_deprecate", "cancel_deprecate") with entity ID in `action.value`. Removed `DEPRECATE_DECISION_PATTERN` regex.

### ISS-001: Pinned ADR messages have no lifecycle UI

**Source:** Code review (2026-02-04)
**Severity:** UX gap
**Closed:** 2026-02-04 (Plan 10-05)

Fixed: Added status badges (Draft/Proposed/Approved/Committed/Deprecated) and lifecycle action buttons to `build_adr_post_blocks`. Registered `adr_propose`, `adr_approve`, `adr_object`, `adr_deprecate` action handlers. Created `_update_adr_pinned_message` helper that rebuilds pinned ADR blocks on every lifecycle transition. Wired into all existing handlers that change decision state.

### ISS-005: Action handlers do too much — Jira calls block user response

**Source:** Code review (2026-02-04)
**Severity:** Performance / architecture
**Closed:** 2026-02-04 (Plan 10-04)

Fixed: Removed synchronous Jira call from `handle_deprecate_confirm`. Created JiraNotificationProjection that handles DecisionDeprecated and DecisionAmended events asynchronously via the outbox pattern. Wired inline outbox processing into `save_events` so all projections run after event persistence.

### ISS-008: Amendment projection doesn't update approvals or adr_message_ts

**Source:** Code review (2026-02-04)
**Severity:** Data inconsistency
**Closed:** 2026-02-04 (Plan 10-03)

Fixed: Added `adr_message_ts` column to `entities_view` (migration 003). Updated `_amend_decision_content` to store `new_adr_message_ts` and `_create_entity` to store `adr_message_ts` on initial recording. Approvals not reset on amendment because the aggregate intentionally preserves them (decision documented).

### ISS-006: Dashboard does not distinguish Draft from Proposed decisions

**Source:** Code review (2026-02-04)
**Severity:** UX gap
**Closed:** 2026-02-04 (Plan 10-02)

Fixed: Added :pencil2: indicator for Draft and :hourglass: for Proposed decisions on dashboard.

### ISS-007: Dashboard truncation has no overflow indicator

**Source:** Code review (2026-02-04)
**Severity:** Minor / UX
**Closed:** 2026-02-04 (Plan 10-02)

Fixed: Added overflow context blocks showing "...and N more active decisions" / "...and N more deprecated" when items exceed display limits.

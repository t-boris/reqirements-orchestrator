# Issues

Deferred issues discovered during code review and development.

## Open

### ISS-002: `adr_message_ts` field on work item entities is dead weight

**Source:** Code review (2026-02-04)
**Severity:** Minor / design smell
**Phase:** Future

`adr_message_ts` was added to all 5 entity types (DraftEntity, ProposedEntity, etc.) but is only meaningful for decisions. Work item entities always have `adr_message_ts = None`. Consider moving to `DecisionContent` or a decision-specific entity variant.

### ISS-009: `handle_message` doesn't fetch thread history — breaks RECORD and CONVERSE in threads

**Source:** Production testing (2026-02-04)
**Severity:** Critical / functional gap
**Phase:** Next

`handle_message` in `events.py` does not call `conversations_replies()` to fetch thread context. Only `handle_app_mention` fetches thread history. This causes two failures:

1. **RECORD/CREATE mode**: User says "record all decisions" as a regular message in a thread with rich discussion. LLM receives `"(No thread history)"` — extracts 0 decisions. User sees "Draft Decision Records (0 found)".
2. **CONVERSE mode in ADR threads**: User replies to a pinned ADR message asking "list advantages and disadvantages of this decision". Bot has no thread context, doesn't know what decision is being discussed, responds with generic "I don't have context" message.

Both work correctly when using `@MARO` (app_mention), because that handler fetches thread history.

**Root cause:** Asymmetry between `handle_message` (lines ~65-133) and `handle_app_mention` (lines ~160-231) in `src/slack/handlers/events.py`. The message handler skips `conversations_replies()` — likely for performance (avoids extra API call per message).

**Suggested fix:**
- Fetch thread history in `handle_message` when `thread_ts` is present (message is in a thread)
- Or: fetch lazily — only when the classified intent needs thread context (CREATE+decision, RECORD, CONVERSE in thread)
- Cost: one extra Slack API call per in-thread message, but thread context is essential for correct behavior

## Closed

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

## Closed

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

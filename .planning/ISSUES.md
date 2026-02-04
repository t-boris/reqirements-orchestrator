# Issues

Deferred issues discovered during code review and development.

## Open

### ISS-002: `adr_message_ts` field on work item entities is dead weight

**Source:** Code review (2026-02-04)
**Severity:** Minor / design smell
**Phase:** Future

`adr_message_ts` was added to all 5 entity types (DraftEntity, ProposedEntity, etc.) but is only meaningful for decisions. Work item entities always have `adr_message_ts = None`. Consider moving to `DecisionContent` or a decision-specific entity variant.

### ISS-009: Bot responds to every message — no "should I respond?" gate

**Source:** Production testing (2026-02-04)
**Severity:** Critical / UX + functional
**Phase:** Next

Two related problems in `handle_message` (`src/slack/handlers/events.py`):

**Problem 1: Bot responds to ALL human messages in channels it's in.**

There is no gate to decide whether the bot should respond. Every regular message passes filters (subtype, bot_id, @mention dedup) and goes to intent classification. Since CONVERSE is the safe default, the bot replies to every message — even human-to-human conversations where nobody asked the bot anything. This is disruptive in active channels.

**When bot SHOULD respond:**
- `@mention` — explicit request (already handled by `app_mention`)
- DM — user is talking directly to bot
- Bot-initiated thread — bot started or was invited into the thread
- Approval/objection keywords in proposal threads — "lgtm", "approved" (already in PreGates)

**When bot should NOT respond:**
- Human-to-human conversation in channel (no @mention)
- Thread where bot wasn't mentioned or involved
- Messages clearly not directed at the bot

**Problem 2: `handle_message` doesn't fetch thread history.**

When the bot IS supposed to respond in a thread, it doesn't call `conversations_replies()`. Only `handle_app_mention` fetches thread context. This causes:
1. "Record all decisions" in thread → 0 decisions found (LLM has no thread context)
2. Asking about a pinned ADR in its thread → bot says "I don't have context"

**Suggested fix:**
1. Add a response gate to `handle_message`:
   - **Channel messages**: Only respond to @mentions (handled by `app_mention`), approval keywords, or messages in bot-initiated threads
   - **DMs**: Always respond
   - **Bot threads** (threads where bot previously posted): Respond and fetch thread history
2. When responding in threads, always fetch `conversations_replies()` for context
3. Track "bot threads" — threads where the bot has participated (via a set of `thread_ts` values, or check if bot has posted in thread)

### ISS-010: Thread context not fetched in handle_message

**Source:** Production testing (2026-02-04)
**Severity:** Critical / functional gap
**Phase:** Next (blocked by ISS-009)

Extracted from ISS-009 as a separate concern. When `handle_message` does process a thread message (after ISS-009 adds proper gating), it must fetch thread history via `conversations_replies()`. Currently only `handle_app_mention` does this.

**Symptoms:**
1. "Record all decisions" as regular message in thread → "Draft Decision Records (0 found)"
2. "List advantages of this decision" in ADR thread → "I don't have the context of which decision"

**Suggested fix:**
- In `handle_message`, when `thread_ts` is present and bot decides to respond, call `conversations_replies(channel, ts=thread_ts, limit=50)` and pass `thread_messages` to the dispatcher
- Same pattern as `handle_app_mention` lines ~177-190

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

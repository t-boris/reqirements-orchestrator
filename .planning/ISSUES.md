# Issues

Deferred issues discovered during code review and development.

## Open

### ISS-001: Pinned ADR messages have no lifecycle UI

**Source:** Code review (2026-02-04)
**Severity:** UX gap
**Phase:** Future

Pinned ADR messages in the channel are plain formatted text with no interactive elements. Users cannot tell whether a decision is Draft, Proposed, Approved, or Committed by looking at the pinned message. The only way to advance the lifecycle is through the original thread — which is easy to lose.

**Missing:**
- No status indicator (Draft / Proposed / Approved / Committed) on pinned message
- No action buttons (Propose for Approval, Approve, Deprecate) on pinned message
- `chat_update` not called on the pinned message when lifecycle transitions happen

**Suggested fix:**
- Add status badge + action buttons to `build_adr_post_blocks`
- Update pinned message on each lifecycle transition via `chat_update`
- Buttons: "Propose for Approval" on Draft, "Approve / Object" on Proposed, "Deprecate" on Committed

### ISS-002: `adr_message_ts` field on work item entities is dead weight

**Source:** Code review (2026-02-04)
**Severity:** Minor / design smell
**Phase:** Future

`adr_message_ts` was added to all 5 entity types (DraftEntity, ProposedEntity, etc.) but is only meaningful for decisions. Work item entities always have `adr_message_ts = None`. Consider moving to `DecisionContent` or a decision-specific entity variant.

### ISS-003: Block parsers are brittle — coupled to mrkdwn format

**Source:** Code review (2026-02-04)
**Severity:** Fragility / maintainability
**Phase:** Future

`_parse_record_mode_preview` and `_parse_amend_preview` in `actions.py` extract decision data by parsing mrkdwn text from Slack Block Kit sections. They are tightly coupled to the exact output format of `_build_decision_preview_blocks` and `_build_amendment_preview_blocks` in `record.py`. Any change to the block format silently breaks the parsers.

**Suggested fix:**
- Store decision data as JSON in `private_metadata` of the message or in `action.value` (Slack limit: 2000 chars — sufficient for most decisions)
- Parsers become `json.loads()` instead of string manipulation
- Single source of truth for data, blocks become purely presentational

### ISS-004: Entity IDs embedded in action_id instead of value

**Source:** Code review (2026-02-04)
**Severity:** Minor / convention
**Phase:** Future

Several action patterns embed entity UUID in the `action_id` string: `deprecate_decision_{uuid}`, `confirm_deprecate_{uuid}`, `cancel_deprecate_{uuid}`. This requires regex parsing and inflates `action_id` length (UUID = 36 chars). Slack limits `action_id` to 255 chars.

**Suggested fix:**
- Use fixed `action_id` values (e.g., `"deprecate_decision"`, `"confirm_deprecate"`)
- Pass entity ID via `action.value` (already done for amend button)
- Simplifies patterns: exact string match instead of regex

## Closed

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

# UAT Issues: Phase 22 - Multi-Ticket from Review

**Tested:** 2026-01-16
**Source:** .planning/phases/22-multi-ticket-from-review/22-*-SUMMARY.md
**Tester:** User via /gsd:verify-work

## Open Issues

### UAT-003: Duplicate detection not implemented for multi-ticket creation

**Discovered:** 2026-01-16
**Phase/Plan:** 22 (all plans)
**Severity:** Enhancement (not a bug)
**Feature:** Multi-ticket preview
**Description:** When creating multiple tickets from a review, the system does not check for potential duplicates before creation.
**Expected:** Each item in preview should show duplicate warnings like "⚠️ Similar: SCRUM-123" with option to "Link instead"
**Actual:** Tickets created without duplicate detection

**Implementation Notes:**
- Run duplicate search for each item during `extract_multi_items_from_review()`
- Store potential duplicates in each item's metadata
- Show warnings in preview blocks
- Add "Link instead" button per item
- Skip duplicate items during batch creation if user chose to link

**Related:** Phase 11.1 (Jira Duplicate Handling) has the duplicate detection logic that could be reused.

## Resolved Issues

### UAT-001: Multi-ticket approve handler not matched (FIXED)
**Resolved:** 2026-01-16 - Fixed in c9c1ca2
**Severity:** Blocker
**Description:** Clicking "Create All in Jira" returned "unhandled request"
**Root cause:** Handler registered as `multi_ticket_approve` but action_id was `multi_ticket_approve:1`
**Fix:** Changed to regex pattern `^multi_ticket_approve(?::\d+)?$`

### UAT-002: Remove item doesn't update preview (FIXED)
**Resolved:** 2026-01-16 - Fixed in 3034ee1
**Severity:** Major
**Description:** Click remove, handler called but item stays in list
**Root cause:** `runner.update_state()` method didn't exist (was `_update_state`)
**Fix:** Added public alias `update_state = _update_state` to GraphRunner

### UAT-004: Pinned board not refreshed after batch creation (FIXED)
**Resolved:** 2026-01-16 - Fixed in d939859
**Severity:** Minor
**Description:** After batch ticket creation, pinned board doesn't update
**Root cause:** `_track_created_tickets` didn't call `trigger_board_refresh()`
**Fix:** Added board refresh call after auto-tracking

---

*Phase: 22-multi-ticket-from-review*
*Tested: 2026-01-16*

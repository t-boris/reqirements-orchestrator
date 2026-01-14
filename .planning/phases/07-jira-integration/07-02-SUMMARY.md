---
phase: 07-jira-integration
plan: 02
subsystem: jira
tags: [jira, skill, approval, idempotency, audit-trail]

# Dependency graph
requires:
  - phase: 07-01
    provides: JiraService client for API calls
  - phase: 06-02
    provides: ApprovalStore for approval records
provides:
  - jira_create skill with strict approval validation
  - JiraOperationStore for idempotency and audit trail
  - jira_operations table with unique constraint
affects: [07-03 jira_search skill, Slack approval flow]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Idempotency key pattern (session_id, draft_hash, operation)
    - First-wins semantics with unique constraint
    - All-or-nothing transactional semantics
    - Audit trail for Jira operations

key-files:
  created:
    - src/db/jira_operations.py
    - src/skills/jira_create.py
  modified:
    - src/db/__init__.py
    - src/skills/__init__.py
    - src/slack/handlers.py

key-decisions:
  - "Idempotency key: (session_id, draft_hash, operation)"
  - "First-wins with unique constraint prevents duplicate creates"
  - "All-or-nothing: Jira failure doesn't advance session state"
  - "Audit trail records created_by, approved_by, status, error_message"
  - "Approval validated before Jira create (not just recorded)"

patterns-established:
  - "Operation stores for dangerous actions with idempotency"
  - "Skill validation pipeline: approval -> hash check -> idempotency -> execute"
  - "Preview message update to show created state with Jira link"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-14
---

# Phase 7 Plan 2: Jira Create Skill Summary

**jira_create skill with strict approval validation, idempotency, and audit trail**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-14
- **Completed:** 2026-01-14
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- JiraOperationRecord Pydantic model with all audit fields
- JiraOperationStore class with 6 methods for idempotent operations
- jira_operations table with unique constraint on (session_id, draft_hash, operation)
- JiraCreateResult dataclass with success/error/was_duplicate fields
- jira_create skill with full validation pipeline
- Integration with approval handler for end-to-end flow
- _update_preview_to_created helper for Slack UI update

## Verification Results

All verification commands passed:

```
python -c "from src.skills.jira_create import jira_create, JiraCreateResult"
# Result: jira_create import: OK

python -c "from src.db.jira_operations import JiraOperationStore"
# Result: JiraOperationStore import: OK

python -c "from src.slack.handlers import handle_approve_draft"
# Result: handle_approve_draft import: OK

grep "UNIQUE" src/db/jira_operations.py
# Result: UNIQUE(session_id, draft_hash, operation)
```

## Files Created/Modified

- `src/db/jira_operations.py` (new) - JiraOperationStore, JiraOperationRecord, table definition
- `src/skills/jira_create.py` (new) - jira_create skill, JiraCreateResult, validation pipeline
- `src/db/__init__.py` - Added exports for JiraOperationStore, JiraOperationRecord
- `src/skills/__init__.py` - Added exports for jira_create, JiraCreateResult
- `src/slack/handlers.py` - Updated handle_approve_draft to call jira_create

## Implementation Details

### JiraOperationStore Methods

1. `record_operation_start()` - Insert pending record, return True if new (first wins)
2. `mark_success(jira_key)` - Update status to success, store jira_key
3. `mark_failed(error)` - Update status to failed, store error
4. `get_operation()` - Get operation record if exists
5. `was_already_created()` - Check if operation succeeded (for idempotency)
6. `get_session_operations()` - Get all operations for audit trail

### jira_create Validation Pipeline

1. **Validate approval exists:** Query ApprovalStore for (session_id, current_hash)
2. **Check draft_hash matches:** Ensure approval status is "approved"
3. **Check idempotency:** Use was_already_created() then record_operation_start()
4. **Create Jira issue:** Call JiraService.create_issue()
5. **Record in audit trail:** mark_success() or mark_failed()

### Approval Handler Integration

- After approval recorded, immediately calls jira_create skill
- On success: updates preview message with Jira link, posts confirmation
- On duplicate: notifies user with existing Jira link
- On failure: posts error message, doesn't advance session state

### Preview Update on Create

New helper `_update_preview_to_created()`:
- Header: "Ticket Created: PROJ-123"
- Title with Jira link
- Abbreviated problem statement
- AC count
- Context: "Created by @user at TIME | View in Jira"

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Steps

- Plan 07-03: Create jira_search skill for duplicate detection
- Test end-to-end flow: approve -> create -> Slack update

---
*Phase: 07-jira-integration*
*Completed: 2026-01-14*

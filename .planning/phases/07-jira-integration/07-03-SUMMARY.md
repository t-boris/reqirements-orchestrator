---
phase: 07-jira-integration
plan: 03
subsystem: jira, skills, slack
tags: [jira-search, duplicate-detection, preview-ui, skills]

# Dependency graph
requires:
  - phase: 07-01
    provides: JiraService.search_issues() for JQL queries
provides:
  - jira_search skill for fast duplicate detection
  - search_similar_to_draft convenience function
  - potential_duplicates field in DecisionResult
  - Duplicate display in preview UI
affects: [decision flow, ticket preview workflow]

# Tech tracking
tech-stack:
  patterns:
    - JQL text search with status exclusion
    - Graceful failure (empty results on error)
    - Decision node integrates duplicate check before preview

key-files:
  created:
    - src/skills/jira_search.py
  modified:
    - src/skills/__init__.py
    - src/graph/nodes/decision.py
    - src/slack/blocks.py

key-decisions:
  - "JQL excludes Done/Closed/Resolved tickets automatically"
  - "Duplicate search fails gracefully - never blocks workflow"
  - "Max 3 duplicates shown in preview UI"
  - "Draft title used as search query, fallback to problem statement"

patterns-established:
  - "Skills handle service instantiation internally for standalone use"
  - "Preview UI warns before approval buttons, doesn't block"
  - "Potential duplicates displayed as clickable Jira links"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-14
---

# Phase 7 Plan 3: Jira Search Skill for Duplicate Detection Summary

**jira_search skill as "last defense" before ticket creation - fast JQL search for potential duplicates**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-14
- **Completed:** 2026-01-14
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

### Task 1: jira_search Skill
- `JiraSearchResult` dataclass with issues, total_count, query
- `jira_search()` async function with JQL query building
- JQL excludes closed tickets (Done, Closed, Resolved)
- Escapes special characters in search query
- Orders by updated date (recent first)
- `search_similar_to_draft()` convenience function
- Extracts project from epic_id if available
- Falls back to problem statement if no title
- Graceful failure returns empty results
- Exported from `src/skills/__init__.py`

### Task 2: Decision Node Integration
- Added `potential_duplicates` field to `DecisionResult` model
- New `_search_for_duplicates()` helper function
- Searches before showing preview (when draft is valid)
- Max 3 duplicates returned for display
- Reason message updated to show duplicate count
- Fails gracefully - doesn't block workflow on search errors
- Service instantiated per-call with proper cleanup

### Task 3: Preview UI Display
- Added `potential_duplicates` parameter to `build_draft_preview_blocks_with_hash()`
- Shows duplicates section before approval buttons
- Each duplicate shows as clickable link: `<url|KEY>: summary...`
- Context message: "Review these before creating a new ticket"
- Summary truncated to 50 chars with ellipsis
- Updated legacy `build_draft_preview_blocks()` for compatibility

## Verification Results

All verification commands passed:

```
python -c "from src.skills.jira_search import jira_search, JiraSearchResult"
# Result: ok

python -c "from src.skills.jira_search import jira_search, search_similar_to_draft"
# Result: ok

python -c "from src.skills import jira_search, search_similar_to_draft"
# Result: ok

python -m py_compile src/graph/nodes/decision.py
# Result: Syntax OK

python -m py_compile src/skills/jira_search.py
# Result: Syntax OK

python -m py_compile src/slack/blocks.py
# Result: Syntax OK

python -c "import inspect; from src.slack.blocks import build_draft_preview_blocks_with_hash; ..."
# Result: Has potential_duplicates: True
```

## Files Created/Modified

- `src/skills/jira_search.py` (new) - JiraSearchResult, jira_search(), search_similar_to_draft()
- `src/skills/__init__.py` - Added jira_search exports
- `src/graph/nodes/decision.py` - Added potential_duplicates to DecisionResult, _search_for_duplicates()
- `src/slack/blocks.py` - Added potential_duplicates parameter and display logic

## Implementation Details

### JQL Query Construction

```python
jql_parts = [f'text ~ "{escaped_query}"']  # Search summary + description
if project:
    jql_parts.append(f'project = "{project}"')
jql_parts.append("status NOT IN (Done, Closed, Resolved)")
jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
```

### Duplicate Display Format

```
*Potential duplicates found:*
- <url|PROJ-123>: Existing ticket summary...
- <url|PROJ-456>: Another similar ticket...
_Review these before creating a new ticket_
```

### Graceful Failure Pattern

```python
try:
    result = await search_similar_to_draft(draft, jira_service)
    # ... process results
except Exception as e:
    logger.warning("Failed to search for duplicates", extra={"error": str(e)})
    return []  # Don't block workflow
```

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Circular import issue when testing full module chain (existing architecture issue)
- Workaround: Direct module imports and syntax validation instead of full graph imports

## Next Steps

- Phase 7 complete: All 3 plans executed
- Next phase: Integration testing with real Jira environment
- Future enhancement: LLM semantic comparison on top-5 results (currently fast JQL only)

---
*Phase: 07-jira-integration*
*Completed: 2026-01-14*

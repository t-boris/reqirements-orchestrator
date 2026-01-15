# Phase 18: Clean Code - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## Goal

Apply clean code principles across the codebase:
1. Split large files (>600 lines) into logical modules
2. Add/update documentation (docstrings, module-level docs)
3. Capture all TODOs and known issues in ISSUES.md
4. Ensure consistent code style

</vision>

<analysis>
## Files Exceeding 600 Lines

| File | Lines | Action |
|------|-------|--------|
| `src/slack/handlers.py` | 3193 | CRITICAL - Split into 5+ modules |
| `src/slack/blocks.py` | 850 | Split into 2 modules |
| `src/jira/client.py` | 726 | Split into 2 modules |

## Files Near Threshold (300-600 lines)

| File | Lines | Action |
|------|-------|--------|
| `src/slack/progress.py` | 538 | Review, may be OK |
| `src/graph/intent.py` | 506 | Review, may be OK |
| `src/db/channel_context_store.py` | 500 | Review, may be OK |
| `src/graph/nodes/extraction.py` | 490 | Review, may be OK |
| `src/graph/nodes/decision.py` | 375 | OK |
| `src/slack/modals.py` | 364 | OK |

## TODOs Found in Codebase

From `src/slack/handlers.py`:
- Line 1001: "Route to session creation in 04-04"
- Line 1008: "Implement Jira search in Phase 7"
- Line 1012: "Query session status in 04-04"
- Line 1252: "Update session card with linked thread reference"
- Line 1253: "Update Epic summary with cross-reference"
- Line 1290: "Update constraint status to 'conflicted' in KG"
- Line 1291: "Add to Epic summary as unresolved conflict"
- Line 1316: "Mark old constraint as 'deprecated'"
- Line 1317: "Mark new constraint as 'accepted'"
- Line 1342: "Mark both as 'accepted' with note about intentional dual values"

From `src/slack/binding.py`:
- Line 61: "Fetch from Jira" (epic_summary)
- Line 148: "Fetch from Jira" (epic_summary)

## handlers.py Logical Split Analysis

Current structure shows these handler groups:

1. **Core Event Handlers** (~300 lines)
   - `handle_app_mention()` + `_process_mention()`
   - `handle_message()` + `_process_thread_message()`
   - Background loop management

2. **Dispatch Logic** (~500 lines)
   - `_dispatch_result()` - main dispatcher
   - `_extract_update_content()`, `_extract_comment_content()`
   - `_check_persona_switch()`

3. **Draft Approval Handlers** (~500 lines)
   - `handle_approve_draft()` + async
   - `handle_reject_draft()` + async
   - `handle_edit_draft_submit()` + async
   - `_build_approved_preview_blocks()`, `_build_rejected_preview_blocks()`

4. **Duplicate Handling** (~400 lines)
   - `handle_link_duplicate()` + async
   - `handle_create_anyway()` + async
   - `handle_add_to_duplicate()` + async
   - `handle_show_more_duplicates()` + async
   - `handle_modal_link_duplicate()` + async
   - `handle_modal_create_anyway()` + async

5. **Command Handlers** (~400 lines)
   - `handle_maro_command()` + subcommands
   - `handle_persona_command()`
   - `handle_jira_command()`
   - `handle_help_command()`

6. **Onboarding/UX Handlers** (~300 lines)
   - `handle_member_joined_channel()`
   - `handle_hint_selection()`
   - `handle_help_example()`

7. **Review Flow Handlers** (~200 lines)
   - `handle_review_to_ticket()`
   - `handle_scope_gate_submit()`

8. **Other Handlers** (~200 lines)
   - Epic selection
   - Contradiction handling
   - Context merge

</analysis>

<plan>
## Recommended Split Structure

```
src/slack/handlers/
├── __init__.py          # Re-export all handlers for bot registration
├── core.py              # App mention, message, background loop
├── dispatch.py          # _dispatch_result(), extraction helpers
├── draft.py             # Approve, reject, edit draft
├── duplicates.py        # Duplicate handling actions
├── commands.py          # /maro, /persona, /jira, /help
├── onboarding.py        # Channel join, hints, help examples
├── review.py            # Review-to-ticket, scope gate
└── misc.py              # Epic selection, contradictions, context merge
```

Each file stays under 500 lines, has clear responsibility.

## blocks.py Split

```
src/slack/blocks/
├── __init__.py          # Re-export all block builders
├── draft.py             # Draft preview blocks, approved/rejected blocks
├── duplicates.py        # Duplicate match blocks, modal blocks
├── decisions.py         # Architecture decision blocks
└── ui.py                # Buttons, hints, help blocks
```

## jira/client.py Split

```
src/jira/
├── client.py            # JiraService class (core methods)
├── operations.py        # update_issue, add_comment, create_subtask (new in Phase 16)
└── types.py             # (already exists) JiraIssue, JiraCreateRequest, etc.
```

</plan>

<notes>
## DoD (Definition of Done)

- [ ] No Python file exceeds 600 lines
- [ ] All modules have docstrings explaining purpose
- [ ] All public functions have docstrings
- [ ] All TODOs captured in .planning/ISSUES.md
- [ ] Imports work correctly after refactoring
- [ ] Tests still pass after refactoring

## Out of Scope

- Adding new features
- Changing functionality
- Performance optimization
- Adding new tests (only ensuring existing pass)

</notes>

---

*Phase: 18-clean-code*
*Context gathered: 2026-01-15*

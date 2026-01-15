# Phase 18: Clean Code - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning (updated)

<vision>
## How This Should Work

When I open any file in this codebase, I should immediately understand what it does. Each file has ONE clear responsibility — I know exactly where to look for any functionality.

The goal is **maintainability**: make it easy for future me (or others) to navigate and modify the code without fear of breaking something or getting lost in a 3000-line file.

</vision>

<essential>
## What Must Be Nailed

- **Clear boundaries** — Each file has ONE responsibility, no god-classes or catch-all modules
- **File size limit** — No Python file exceeds 600 lines
- **Naming conventions** — Functions and variables with clear, descriptive names (no cryptic abbreviations)
- **Function length** — Functions do ONE thing, ideally 20-30 lines max
- **DRY** — No code duplication, common patterns extracted
- **TODOs tracked** — All deferred work visible in ISSUES.md, not buried in code
- **Documentation** — Module and function docstrings explain purpose

</essential>

<specifics>
## Specific Requirements

1. **handlers.py (3193 lines)** — CRITICAL. Split into logical modules:
   - core.py — App mention, message, background loop
   - dispatch.py — Result dispatching, extraction helpers
   - draft.py — Approve, reject, edit draft
   - duplicates.py — Duplicate handling actions
   - commands.py — /maro, /persona, /jira, /help
   - onboarding.py — Channel join, hints, help examples
   - review.py — Review-to-ticket, scope gate
   - misc.py — Epic selection, contradictions

2. **blocks.py (850 lines)** — Split by block type:
   - draft.py — Draft preview blocks
   - duplicates.py — Duplicate match blocks
   - decisions.py — Architecture decision blocks
   - ui.py — Buttons, hints, help blocks

3. **jira/client.py (726 lines)** — Organize or split:
   - Core methods (init, session, request)
   - CRUD (create_issue, get_issue, search_issues)
   - Operations (update_issue, add_comment, create_subtask)

4. **Full clean code audit**:
   - Check all files for naming issues
   - Identify long functions that need splitting
   - Find and extract duplicated patterns
   - Ensure consistent style across codebase

</specifics>

<analysis>
## Files Exceeding 600 Lines

| File | Lines | Action |
|------|-------|--------|
| `src/slack/handlers.py` | 3193 | CRITICAL - Split into 8 modules |
| `src/slack/blocks.py` | 850 | Split into 4 modules |
| `src/jira/client.py` | 726 | Split or organize with sections |

## Files Near Threshold (300-600 lines)

| File | Lines | Action |
|------|-------|--------|
| `src/slack/progress.py` | 538 | Review for clean code |
| `src/graph/intent.py` | 506 | Review for clean code |
| `src/db/channel_context_store.py` | 500 | Review for clean code |
| `src/graph/nodes/extraction.py` | 490 | Review for clean code |
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

</analysis>

<notes>
## DoD (Definition of Done)

- [ ] No Python file exceeds 600 lines
- [ ] All modules have docstrings explaining purpose
- [ ] All public functions have docstrings
- [ ] All TODOs captured in .planning/ISSUES.md
- [ ] Imports work correctly after refactoring
- [ ] Tests still pass after refactoring
- [ ] No obvious naming convention violations
- [ ] No functions exceeding 50 lines without good reason
- [ ] No duplicated code blocks (>10 lines)

## Out of Scope

- Adding new features
- Changing functionality
- Performance optimization
- Adding new tests (only ensuring existing pass)

## Clean Code Principles Checklist

Based on "Clean Code" by Robert C. Martin:

1. **Meaningful Names**
   - Use intention-revealing names
   - Avoid disinformation
   - Make meaningful distinctions
   - Use pronounceable names
   - Use searchable names

2. **Functions**
   - Small (20-30 lines ideally)
   - Do one thing
   - One level of abstraction
   - Descriptive names
   - Few arguments (0-3 ideally)

3. **Comments**
   - Code should be self-explanatory
   - TODOs must be tracked elsewhere
   - Don't comment bad code — rewrite it

4. **Formatting**
   - Vertical openness between concepts
   - Related code together
   - Consistent indentation

5. **Objects and Data Structures**
   - Hide internal structure
   - Law of Demeter

6. **Error Handling**
   - Don't return None
   - Don't pass None
   - Use exceptions, not error codes

</notes>

---

*Phase: 18-clean-code*
*Context gathered: 2026-01-15*
*Updated: 2026-01-15 — Expanded scope to full clean code audit*

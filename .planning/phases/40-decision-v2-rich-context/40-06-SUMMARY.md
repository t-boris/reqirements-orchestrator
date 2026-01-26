---
phase: 40-decision-v2-rich-context
plan: 06
status: complete
---

## Summary

Added migration support and backfill commands for enriching existing decisions with rich context. This enables users to retroactively add rationale, context, alternatives, and consequences to decisions that were created before Phase 40.

## Changes Made

- `src/db/decision_store.py`:
  - Added `update_rich_context()` method for backfill operations (no version increment)
  - Added `list_without_rich_context()` method to find decisions needing enrichment

- `src/slack/handlers/commands.py`:
  - Added `/maro decision enrich <id>` command to extract rich context from discussion thread
  - Added `/maro decision needs-context` command to list decisions without rich context
  - Updated help text and docstrings with new commands

## Commits

- `1c3330a`: feat(40-06): add update_rich_context() and list_without_rich_context() to DecisionStore
- `5c2da3a`: feat(40-06): add /maro decision enrich command handler
- `cb44f4d`: feat(40-06): add /maro decision needs-context command

## Verification

- [x] update_rich_context() updates fields without version increment
- [x] list_without_rich_context() returns correct decisions (all 4 fields NULL)
- [x] /maro decision enrich DEC-xxx works end-to-end (fetches thread, extracts, updates)
- [x] /maro decision needs-context lists decisions correctly
- [x] Error handling for invalid/not-found decisions
- [x] Decision ID normalization (DEC-xxx format and prefix matching)

## Notes

- `update_rich_context()` intentionally does NOT increment version or create history since it's a backfill operation for missing context, not a semantic change to the decision itself
- The enrich command uses ephemeral messages for all feedback to avoid cluttering the channel
- If a decision already has rich context, the enrich command informs the user rather than overwriting
- Type emojis in needs-context output use Slack emoji names (e.g., `:brain:`, `:lock:`)

---
*Phase: 40-decision-v2-rich-context*
*Completed: 2026-01-25*

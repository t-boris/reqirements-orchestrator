---
phase: 40-decision-v2-rich-context
plan: 05
status: complete
---

## Summary

Updated Slack UI to display rich context in decision cards. Enhanced decision cards with formatted sections for rationale, context, alternatives, and consequences.

## Changes Made

- `src/slack/blocks/decision_cards.py`: Added `build_rich_context_blocks()` function to create Slack blocks for rich context with visual formatting (primary rationale markers, severity emojis)
- `src/slack/blocks/decision_cards.py`: Updated `build_approval_block()` to include rich context sections when decision has rationale, context, alternatives, or consequences
- `src/slack/blocks/decision_cards.py`: Updated `build_approved_card()` to show rationale preview (first item truncated to 80 chars plus count)
- `src/slack/blocks/decision_cards.py`: Added `build_decision_details_blocks()` for full decision view with header, metadata fields, and complete rich context

## Commits

- `62a3729`: feat(40-05): add build_rich_context_blocks function
- `ba32308`: feat(40-05): update build_approval_block with rich context
- `7ce685e`: feat(40-05): add rich context to approved card and decision show

## Verification

- [x] build_rich_context_blocks() creates correct Slack blocks
- [x] build_approval_block() shows rich context sections
- [x] build_approved_card() shows rationale preview
- [x] build_decision_details_blocks() shows full rich context
- [x] All block builders handle decisions without rich context

## Notes

- Rich context visual formatting:
  - Primary rationale items use triangle marker (▸), secondary use bullet (•)
  - Consequence severity uses colored circles: green=minor, yellow=moderate, red=major
  - Each rich context field is a separate section block for visual clarity
- Changed "Show history" button to "Show details" with new action_id `decision_show_details` for triggering full detail view
- All functions are backward compatible with decisions that lack rich context fields

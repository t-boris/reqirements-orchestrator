---
phase: 44-questions-first-collection-stage
plan: 05
status: complete
---

# 44-05 Summary: Triage UI Handlers

## What Was Built

Created Slack UI components for triage questions - both block builders for rendering questions and handlers for processing button clicks.

### Files Created

1. **src/slack/blocks/triage.py**
   - `build_triage_question_blocks(question, thread_ts)`: Builds Slack Block Kit UI for triage questions
     - Friendly intro text: "Before I get started, I'd like to understand what you need:"
     - Question text in bold
     - Button options with primary style for recommended
     - JSON-encoded button values with question_id, target_field, value, thread_ts
     - Action IDs following pattern: `triage_answer_{target_field}_{option_id}`
     - Context help text for free-form or button responses
   - `build_triage_complete_blocks()`: Acknowledgment UI when triage finishes

2. **src/slack/handlers/triage.py**
   - `register_triage_handlers(app)`: Registers handlers with pattern `triage_answer_*`
   - `handle_triage_answer()`: Async handler for button clicks
     - Parses JSON-encoded button value
     - Updates original message to show selection
     - Saves answer to TriageStore via `update_field()`
     - Computes remaining gaps with `_compute_remaining_gaps()`
     - Posts next question if gaps remain
     - Triggers re-classification when complete
   - `_compute_remaining_gaps(answers)`: Determines which gaps still need addressing
     - UNKNOWN_MODE: needs mode_hint
     - UNKNOWN_TARGET: needs target_hint, topic, or jira_key
     - UNKNOWN_SCOPE: needs scope_hint (only for build mode)
     - MISSING_TOPIC: needs topic (only for think mode)
   - `_trigger_reclassification()`: Re-invokes graph with enriched triage context

### Files Modified

3. **src/slack/handlers/__init__.py**
   - Imported `register_triage_handlers` from triage module
   - Added to `__all__` exports

## Design Decisions

1. **JSON Button Values**: Button values are JSON-encoded to carry structured data (question_id, target_field, value, thread_ts). More robust than colon-separated strings.

2. **Action ID Pattern**: Uses `triage_answer_{field}_{option_id}` pattern to allow regex matching while preserving field context.

3. **Incremental Gap Checking**: After each answer, recomputes remaining gaps rather than tracking a question queue. This allows dynamic question ordering.

4. **Mode-Dependent Gaps**: UNKNOWN_SCOPE only applies when mode is "build", MISSING_TOPIC only applies when mode is "think". This prevents irrelevant questions.

5. **Re-classification Flow**: When triage completes, posts acknowledgment message then re-runs graph with triage_answers in state. The graph's triage gate sees answers exist and proceeds to classification.

## Verification

```bash
# Block builder import
python -c "from src.slack.blocks.triage import build_triage_question_blocks; print('OK')"
# Output: OK

# Handler import
python -c "from src.slack.handlers.triage import handle_triage_answer; print('OK')"
# Output: OK

# Package export
python -c "from src.slack.handlers import register_triage_handlers; print('OK')"
# Output: OK
```

## Integration Points

- **TriageProvider (44-02)**: Generates QuestionTask objects consumed by block builder
- **TriageStore (44-04)**: Persists answers via update_field() from handler
- **GraphRunner**: Re-invoked with enriched state after triage complete
- **Triage Gate**: Checks triage_answers in state to determine fast path

## Button Value Format

```json
{
  "question_id": "uuid-string",
  "target_field": "mode_hint",
  "value": "build",
  "thread_ts": "1234567890.123456"
}
```

## Commits

1. `feat(44-05): create triage block builder`
2. `feat(44-05): create triage button handler`
3. `feat(44-05): register triage handlers in app`

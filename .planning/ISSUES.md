# Known Issues and TODOs

Captured from codebase during Phase 18 (Clean Code).

## Open Issues

### Session/Epic Features (Deferred)

| ID | Source | Description | Status |
|----|--------|-------------|--------|
| ISS-001 | commands.py:63 | Route to session creation in 04-04 | Deferred |
| ISS-002 | commands.py:70 | Implement Jira search in Phase 7 | Completed (Phase 7) |
| ISS-003 | commands.py:74 | Query session status in 04-04 | Deferred |
| ISS-004 | duplicates.py:524 | Update session card with linked thread reference | Deferred |
| ISS-005 | duplicates.py:525 | Update Epic summary with cross-reference | Deferred |
| ISS-006 | binding.py:61,148 | Fetch epic_summary from Jira | Deferred |

### Constraint/Contradiction Features (Deferred)

| ID | Source | Description | Status |
|----|--------|-------------|--------|
| ISS-007 | misc.py:312 | Update constraint status to 'conflicted' in KG | Deferred |
| ISS-008 | misc.py:313 | Add to Epic summary as unresolved conflict | Deferred |
| ISS-009 | misc.py:338 | Mark old constraint as 'deprecated' | Deferred |
| ISS-010 | misc.py:339 | Mark new constraint as 'accepted' | Deferred |
| ISS-011 | misc.py:364 | Mark both as 'accepted' with note | Deferred |

## Resolved Issues

| ID | Description | Resolution | Phase |
|----|-------------|------------|-------|
| - | Jira search implementation | Implemented | Phase 7 |
| - | Intent detection for review vs ticket | Implemented | Phase 13 |

## Accepted Complexity (Long Functions)

The following functions exceed 100 lines but are considered acceptable complexity. They are dispatchers, UI builders, or state machines where splitting would make code harder to follow.

### Dispatchers/Routers (action switch/match logic)

| Function | Location | Lines | Reason |
|----------|----------|-------|--------|
| `_dispatch_result()` | dispatch.py:104 | 235 | Routes 10+ action types; splitting would scatter logic |
| `classify_intent_patterns()` | intent.py:200 | 109 | Pattern matching for 6 intent types |
| `_llm_classify()` | intent.py:311 | 116 | LLM classification with multiple fallbacks |
| `_handle_ticket_action()` | dispatch.py:341 | 125 | Routes 5 ticket action types |
| `evaluate_switch()` | switcher.py:57 | 114 | Persona evaluation with multiple criteria |

### State Machine Nodes (multi-step processing)

| Function | Location | Lines | Reason |
|----------|----------|-------|--------|
| `extraction_node()` | extraction.py:190 | 301 | 7-step extraction pipeline with context handling |
| `decision_node()` | decision.py:196 | 168 | Completeness check + duplicate detection |
| `review_node()` | review.py:136 | 136 | Persona-based review generation |
| `review_continuation_node()` | review_continuation.py:46 | 107 | Answer synthesis for review conversations |

### UI Block Builders (Slack-specific verbosity)

| Function | Location | Lines | Reason |
|----------|----------|-------|--------|
| `build_draft_preview_blocks_with_hash()` | blocks/draft.py:181 | 222 | Complex draft preview with sections |
| `build_edit_draft_modal()` | modals.py:11 | 195 | Modal with all draft fields |
| `build_duplicate_modal()` | modals.py:259 | 106 | Duplicate selection UI |
| `build_duplicate_blocks()` | blocks/duplicates.py:4 | 125 | Duplicate display with metadata |
| `build_contradiction_alert_blocks()` | contradiction.py:48 | 108 | Contradiction UI with options |
| `build_findings_blocks()` | blocks/draft.py:405 | 107 | Validation findings display |

### Handler Workflows (multi-step async operations)

| Function | Location | Lines | Reason |
|----------|----------|-------|--------|
| `_handle_approve_draft_async()` | draft.py:35 | 257 | 7-step approval pipeline with retries |
| `jira_create()` | jira_create.py:103 | 235 | 5-step Jira creation with validation |
| `ask_user()` | ask_user.py:50 | 162 | Question formatting + Slack posting |
| `_request()` | jira/client.py:133 | 172 | HTTP request with retries and error handling |
| `_handle_edit_draft_submit_async()` | draft.py:399 | 121 | Draft edit with validation |
| `match_answers()` | answer_matcher.py:58 | 101 | Question-answer matching logic |

**Decision:** These functions remain as-is. Each follows a single logical operation or is a well-organized dispatcher. Splitting would harm readability without improving maintainability.

## Notes

- Session and Epic features were part of original design but deprioritized for v1.0
- Constraint/contradiction features relate to knowledge graph updates (not yet implemented)
- These issues are tracked here for future reference; no immediate action required

---

*Last updated: 2026-01-15 (Phase 18-04)*

# Phase 42: Code Modularization — Context

## Objective

Split files exceeding 600 lines into logical components. Improve maintainability without changing behavior.

## Scope

**23 files** exceed 600 lines (total: ~25,000 lines to reorganize):

| File | Lines | Priority | Suggested Split |
|------|-------|----------|-----------------|
| `slack/handlers/dispatch.py` | 2717 | P0 | By action type (draft, decision, review, jira, task_plan) |
| `slack/handlers/commands.py` | 1650 | P0 | By command group (debug, sync, decisions, explain) |
| `slack/handlers/multi_ticket.py` | 1538 | P1 | By flow (creation, linking, UI) |
| `slack/handlers/decision_buttons.py` | 1433 | P1 | By operation (approve, change, deprecate, link) |
| `graph/nodes/extraction.py` | 1290 | P1 | By extraction type (draft, decision, review) |
| `slack/handlers/draft.py` | 1288 | P1 | By lifecycle stage (create, transform, approve) |
| `slack/handlers/sync.py` | 1251 | P1 | By sync type (preflight, manual, conflict) |
| `slack/handlers/review.py` | 1247 | P1 | By review phase (start, continue, complete) |
| `graph/intent.py` | 1149 | P0 | By stage (pre-gates, mode, intent, policy) |
| `slack/handlers/duplicates.py` | 1054 | P2 | By operation (detect, resolve, UI) |
| `jira/client.py` | 979 | P1 | By operation type (read, write, search) |
| `graph/nodes/decision.py` | 961 | P1 | By operation (create, update, deprecate, link) |
| `slack/blocks/decision_cards.py` | 922 | P2 | By card type (draft, approval, approved, deprecated) |
| `db/decision_store.py` | 920 | P2 | By entity (Decision, DecisionVersion, DecisionLink) |
| `db/workitem_store.py` | 852 | P2 | By operation (CRUD, queries, sync) |
| `slack/handlers/core.py` | 843 | P2 | By concern (context, routing, response) |
| `schemas/structured_draft.py` | 829 | P2 | By component (models, mutations, validation) |
| `graph/nodes/review.py` | 805 | P2 | By phase (analysis, questions, artifacts) |
| `slack/handlers/decision_change_handlers.py` | 767 | P2 | By operation (change, deprecate, rollback) |
| `db/jira_registry.py` | 735 | P2 | By operation (register, sync, queries) |
| `slack/handlers/preflight.py` | 633 | P3 | By conflict type (idempotent, drift, conflict) |
| `slack/decision_linker.py` | 607 | P3 | By concern (linking, UI, sync) |
| `slack/blocks/draft.py` | 607 | P3 | By card type (preview, approval, status) |

## Principles

1. **No behavior changes** — Pure refactoring, no new features
2. **Logical cohesion** — Group by domain concept, not by size
3. **Import hygiene** — Re-export from `__init__.py` for backward compatibility
4. **Test stability** — Existing tests must pass without modification
5. **Incremental** — One file per plan, verify after each

## Priority Order

**Wave 1 (P0):** Core routing files
- dispatch.py → handlers/dispatch/ (5-6 modules)
- intent.py → intent/ (4 modules)
- commands.py → commands/ (4-5 modules)

**Wave 2 (P1):** Handler files
- decision_buttons.py, draft.py, review.py, sync.py
- multi_ticket.py, extraction.py, jira/client.py

**Wave 3 (P2):** Store and schema files
- decision_store.py, workitem_store.py
- structured_draft.py, decision_cards.py

**Wave 4 (P3):** Smaller files
- preflight.py, decision_linker.py, draft.py (blocks)

## Success Criteria

- [ ] No file exceeds 600 lines
- [ ] All existing tests pass
- [ ] Import paths preserved via re-exports
- [ ] No new functionality added
- [ ] Each module has clear single responsibility

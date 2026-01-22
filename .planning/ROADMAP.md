# Roadmap: Proactive Jira Analyst Bot

## Milestones

- ✅ **v1.0 MVP** — Phases 1-10 (shipped 2026-01-14) → [Archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Communication as Source of Truth** — Phases 11-23.5 (shipped 2026-01-20) → [Archive](milestones/v1.1-ROADMAP.md)
- 🚧 **v1.2 Developer Experience** — Phases 24+

---

## v1.2 Developer Experience

**Goal:** Improve debugging and observability for bot operators.

### Phase 24: Debug Mode (COMPLETE)

**Objective:** Per-channel debug mode that shows internal processing details.

**Features:**
- `/maro debug on/off` - Enable/disable per channel
- `/maro debug status` - Quick health check (mode, project, counts)
- `/maro debug state` - Full internal dump (context, registry, activity)
- Verbose output after each message processing (intent, duplicates, decision, LLM calls)

**Design decisions:**
- Output: Same thread as user message
- Timing: Single consolidated message after processing
- LLM content: Truncated (300 chars) + .txt file attachment for full content
- Errors: Last 5 stack frames

**Components:**
1. `DebugStore` - Per-channel debug settings persistence
2. `DebugCollector` - Accumulate debug data during processing
3. `/maro debug` handler - Slash command for on/off/status/state
4. Dispatch integration - Post debug output after processing

### Phase 25: WorkItem-Centric Architecture

**Status:** COMPLETE → [Discussion Doc](phases/25-workitem-centric/DISCUSSION.md)

**Objective:** Shift from Jira-centric to WorkItem-centric model.

**Mantra:** "Threads propose. Channels decide. Jira executes."

**Decisions:**
- `OPS` intent with `subtype: DEBUG | EXPLAIN` (not two separate intents)
- `TICKET` → `WORKITEM_CREATE` rename with dual-stack migration
- All 5 sub-phases in scope for v1.2

**Sub-phases:**

| Phase | Focus | Risk |
|-------|-------|------|
| 25.1 | Documentation rewrite (Git model, system identity) | Low |
| 25.2 | Intent rename + OPS intent (DEBUG/EXPLAIN subtypes) | Medium |
| 25.3 | CHANGE_REQUEST intent (diff-based updates) | Medium |
| 25.4 | ReviewArtifact persistence | Medium |
| 25.5 | State separation + dedupe reorder | High |

**Dependencies:**
- 25.1 parallel with 25.2-25.4
- 25.5 depends on 25.2-25.4

### Phase 26: Context-Aware Intent Classification

**Status:** Not started

**Objective:** Make intent classification context-aware so MARO understands issue types structurally and doesn't confuse meta-questions about drafts with REVIEW requests.

**Problem:**
1. No `issue_type` field in draft — "only epics" becomes "Epic:" in title
2. Intent router ignores active draft context — "one epic enough?" routes to REVIEW
3. LLM classifies message text only, not message + state

**Components:**

| Component | Focus | Changes |
|-----------|-------|---------|
| A | Draft Schema | Add `issue_type`, `requested_scope` to TicketDraft |
| B | Intent Router | Context-aware classification: message + state → intent + relation |
| C | Extraction | Extract `issue_type` and `scope` from user requests |
| D | Decision | Draft continuity rule to prevent premature mode switch |

**New Intent:**
- `DRAFT_REFINE` — Refinement questions about active draft structure

**Key Rule:**
When active draft exists and user asks "Do you think X is enough?", classify as `DRAFT_REFINE` (not REVIEW).

**Expected Behavior After Fix:**
```
User: "formulate only epic(s) for this task"
→ issue_type=EPIC, requested_scope=EPICS_ONLY
→ draft.title = "Voice-controlled Remote Command Execution System" (clean, no "Epic:" prefix)

User: "Do you think only one epic is enough?"
→ intent=DRAFT_REFINE (not REVIEW)
→ Bot proposes decomposition options, asks clarifying question
```

## Completed Milestones

<details>
<summary>✅ v1.0 MVP (Phases 1-10) — SHIPPED 2026-01-14</summary>

- [x] Phase 1: Foundation (3/3 plans) — completed 2026-01-14
- [x] Phase 2: Database Layer (3/3 plans) — completed 2026-01-14
- [x] Phase 3: LLM Integration (6/6 plans) — completed 2026-01-14
- [x] Phase 4: Slack Router (9/9 plans) — completed 2026-01-14
- [x] Phase 5: Agent Core (4/4 plans) — completed 2026-01-14
- [x] Phase 6: Skills (3/3 plans) — completed 2026-01-14
- [x] Phase 7: Jira Integration (3/3 plans) — completed 2026-01-14
- [x] Phase 8: Global State (5/5 plans) — completed 2026-01-14
- [x] Phase 9: Personas (4/4 plans) — completed 2026-01-14
- [x] Phase 10: Deployment (3/3 plans) — completed 2026-01-14

**Total:** 10 phases, 43 plans, 13,248 LOC

Full details: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

<details>
<summary>✅ v1.1 Communication as Source of Truth (Phases 11-23.5) — SHIPPED 2026-01-20</summary>

- [x] Phase 11: Conversation History (3/3 plans) — completed 2026-01-14
- [x] Phase 11.1: Jira Duplicate Handling (1/1 plan) — completed 2026-01-15
- [x] Phase 11.2: Progress & Status Indicators (4/4 plans) — completed 2026-01-15
- [x] Phase 12: Onboarding UX (3/3 plans) — completed 2026-01-15
- [x] Phase 13: Intent Router (4/4 plans) — completed 2026-01-15
- [x] Phase 13.1: Ticket Reference Handling (1/1 plan) — completed 2026-01-15
- [x] Phase 14: Architecture Decisions (1/1 plan) — completed 2026-01-15
- [x] Phase 15: Review Conversation Flow (1/1 plan) — completed 2026-01-15
- [x] Phase 16: Ticket Operations (1/1 plan) — completed 2026-01-15
- [x] Phase 18: Clean Code (4/4 plans) — completed 2026-01-15
- [x] Phase 20: Brain Refactor (12/12 plans) — completed 2026-01-15
- [x] Phase 21: Jira Sync & Management (5/5 plans) — completed 2026-01-16
- [x] Phase 22: Multi-Ticket from Review (4/4 plans) — completed 2026-01-16
- [x] Phase 23.1: WorkItem Registry (4/4 plans) — completed 2026-01-20
- [x] Phase 23.2: Channel Mode (4/4 plans) — completed 2026-01-20
- [x] Phase 23.3: Commit Semantics (5/5 plans) — completed 2026-01-20
- [x] Phase 23.4: Jira Sync Engine (6/6 plans) — completed 2026-01-20
- [x] Phase 23.5: Integration (5/5 plans) — completed 2026-01-20

**Total:** 18 phases, 63 plans, 34,567 LOC

**Key accomplishments:**
- Conversation history with two-layer context
- Intent routing (TICKET/REVIEW/DISCUSSION)
- Brain refactor with new AgentState architecture
- Multi-ticket creation from reviews
- WorkItem registry with channel modes
- Bidirectional Jira sync with conflict detection

Full details: [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md)

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 3/3 | Complete | 2026-01-14 |
| 2. Database Layer | v1.0 | 3/3 | Complete | 2026-01-14 |
| 3. LLM Integration | v1.0 | 6/6 | Complete | 2026-01-14 |
| 4. Slack Router | v1.0 | 9/9 | Complete | 2026-01-14 |
| 5. Agent Core | v1.0 | 4/4 | Complete | 2026-01-14 |
| 6. Skills | v1.0 | 3/3 | Complete | 2026-01-14 |
| 7. Jira Integration | v1.0 | 3/3 | Complete | 2026-01-14 |
| 8. Global State | v1.0 | 5/5 | Complete | 2026-01-14 |
| 9. Personas | v1.0 | 4/4 | Complete | 2026-01-14 |
| 10. Deployment | v1.0 | 3/3 | Complete | 2026-01-14 |
| 11. Conversation History | v1.1 | 3/3 | Complete | 2026-01-14 |
| 11.1 Jira Duplicate Handling | v1.1 | 1/1 | Complete | 2026-01-15 |
| 11.2 Progress & Status Indicators | v1.1 | 4/4 | Complete | 2026-01-15 |
| 12. Onboarding UX | v1.1 | 3/3 | Complete | 2026-01-15 |
| 13. Intent Router | v1.1 | 4/4 | Complete | 2026-01-15 |
| 13.1 Ticket Reference Handling | v1.1 | 1/1 | Complete | 2026-01-15 |
| 14. Architecture Decisions | v1.1 | 1/1 | Complete | 2026-01-15 |
| 15. Review Conversation Flow | v1.1 | 1/1 | Complete | 2026-01-15 |
| 16. Ticket Operations | v1.1 | 1/1 | Complete | 2026-01-15 |
| 18. Clean Code | v1.1 | 4/4 | Complete | 2026-01-15 |
| 20. Brain Refactor | v1.1 | 12/12 | Complete | 2026-01-15 |
| 21. Jira Sync & Management | v1.1 | 5/5 | Complete | 2026-01-16 |
| 22. Multi-Ticket from Review | v1.1 | 4/4 | Complete | 2026-01-16 |
| 23.1 WorkItem Registry | v1.1 | 4/4 | Complete | 2026-01-20 |
| 23.2 Channel Mode | v1.1 | 4/4 | Complete | 2026-01-20 |
| 23.3 Commit Semantics | v1.1 | 5/5 | Complete | 2026-01-20 |
| 23.4 Jira Sync Engine | v1.1 | 6/6 | Complete | 2026-01-20 |
| 23.5 Integration | v1.1 | 5/5 | Complete | 2026-01-20 |
| 24. Debug Mode | v1.2 | 3/3 | Complete | 2026-01-22 |
| 25.1 Documentation | v1.2 | 1/1 | Complete | 2026-01-22 |
| 25.2 Intent Rename + OPS | v1.2 | 1/1 | Complete | 2026-01-22 |
| 25.3 CHANGE_REQUEST | v1.2 | 1/1 | Complete | 2026-01-22 |
| 25.4 ReviewArtifact | v1.2 | 1/1 | Complete | 2026-01-22 |
| 25.5 State + Dedupe | v1.2 | 1/1 | Complete | 2026-01-22 |
| 26. Context-Aware Intent | v1.2 | 3/4 | In progress | - |

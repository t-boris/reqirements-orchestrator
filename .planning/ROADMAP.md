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

**Status:** COMPLETE (4/4 plans)

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

### Phase 27: Multi-User Support

**Status:** COMPLETE (6/6 sub-phases)

**Objective:** Enable MARO to work in channels with multiple participants — track authorship, handle concurrent edits, route approvals correctly, and maintain auditability.

**Mantra:** Every statement has an author, every action has an approver, every conflict has a resolution path.

**Sub-Phases:**

| Phase | Focus | Risk | Status |
|-------|-------|------|--------|
| 27.1 | User Identity & Attribution Foundation | Low | Complete |
| 27.2 | Participant Map & Turn-Taking | Medium | Complete |
| 27.3 | Multi-Author Drafts & Conflict Detection | High | Complete |
| 27.4 | State-Bound Approvals | Medium | Complete |
| 27.5 | WorkItem Ownership & Audit Log | Medium | Complete |
| 27.6 | Notifications & Slack UX | Low | Complete |

**What shipped:**
- User identity with metadata caching (display name, avatar)
- Field attribution tracking (who said what)
- Thread participant tracking with activity windows
- Multi-author draft support with semantic conflict detection
- State-bound approvals preventing stale button clicks
- WorkItem ownership with audit logging
- Targeted notifications (owners/watchers, not everyone)
- Low-noise filtering for listening mode
- Status cards at channel level for Jira visibility
- Open question tracking with no-response policy

**Full requirements:** `.planning/phases/27-multi-user-support/REQUIREMENTS.md`
**Implementation plan:** `.planning/phases/27-multi-user-support/27-PLAN.md`

### Phase 28: Structured Draft Evolution

**Status:** IN PROGRESS (5/? plans complete)

**Objective:** Transform Draft from "text container for a ticket" to "typed, versioned design object with lifecycle states and structural mutations."

**Mantra:** Draft is a data structure representing the shape of work, not a paragraph of text.

**Core Shift:** From "bot collects text for a ticket" to "bot manages the form of a design object and the evolution of its structure."

**Key Concepts:**

1. **DraftKind** — SINGLE_ITEM vs PLAN (multiple items with structure)
2. **DraftScope** — SINGLE, EPICS_ONLY, FULL_PLAN
3. **DraftItemStatus** — PROPOSED → APPROVED → COMMITTED
4. **DraftLifecycle** — EMPTY → SINGLE_ITEM → PLAN → PLAN_REFINED → APPROVED → COMMITTED
5. **DRAFT_TRANSFORM intent** — Semantic triggers like "split into...", "merge these...", "break this down"

**Requirements:**

| Rule | Description |
|------|-------------|
| R1 | Draft must be a typed object, not text |
| R2 | User decisions must mutate Draft form, not just be answered with text |
| R3 | Bot must transition from questions to action |
| R4 | New intent: DRAFT_TRANSFORM |
| R5 | Draft must have a lifecycle |
| R6 | Validation must depend on Draft form |
| R7 | Distinguish between choice, opinion, and question |
| R8 | After each Draft form change, show the new form |
| R9 | Draft must be versioned |
| R10 | Bot cannot repeat a question after receiving a direct answer |
| R11 | Transition from decision to action is mandatory |
| R12 | Draft is no longer "text draft", it's a "design model" |

**DoD Tests:**
- T1: Structural decision mutates state (e.g., "Split into epics" → Draft.kind = PLAN)
- T2: Lifecycle enforced (PLAN stage → ask decomposition, not acceptance criteria)
- T3: No question repetition after direct answer
- T4: Version-bound approvals reject outdated buttons
- T5: Form-dependent validation (Epic validates goal/scope, Story validates AC)

**Full requirements:** `.planning/phases/28-structured-draft-evolution/REQUIREMENTS.md`

### Phase 29: Sync on Demand

**Status:** COMPLETE (4/4 plans)

**Objective:** Pull changes from Jira for all tracked tickets. Detect external modifications and update local database.

**Two Components:**

| Component | Purpose | Trigger |
|-----------|---------|---------|
| **Preflight Sync** | Automatic safety layer before Jira operations | Before jira_create/update/transition |
| **/maro sync** | Diagnostic and reconciliation command | Manual operator command |

**Conflict Types:**
1. **Idempotent** - Operation already done in Jira, auto-success + sync
2. **Safe Drift** - Changes don't overlap, ask but default to proceed
3. **Real Conflict** - Same fields changed, block + choice
4. **Structural** - Invalid operation, block + explanation

**Philosophy:** "Distributed version control for meaning" - never auto-fix, always human choice.

**Full context:** `.planning/milestones/v1.2/phase-29-CONTEXT.md`

### Phase 30: Decision as First-Class Entity

**Status:** COMPLETE (8/8 plans)

**Objective:** Make Decision a versioned, linked entity that Jira projects from — not the other way around.

**Mantra:** "Decisions are versioned, Jira is a projection."

**Key Concepts:**

1. **Decision Entity** — id, channel_id, type, title, description, status, version
2. **Decision Types** — ARCH | SCOPE | CONSTRAINT | PRIORITY | STRUCTURE | PROCESS
3. **Decision Status** — PROPOSED → APPROVED → DEPRECATED/REPLACED
4. **DecisionLink** — Mapping between Decision and Jira fields
5. **Jira as Projection** — Read-only view of decisions, not source of truth

**Requirements Summary:**

| Rule | Description |
|------|-------------|
| R1 | Decision entity with full lifecycle |
| R2 | DecisionLink for Jira field mappings |
| R3 | Jira as projection (changes flow decision → Jira) |
| R4 | Full CRUD: create, read, update, deprecate |
| R5 | Mapping rules: decision type → Jira field |
| R6 | Decision preflight before Jira sync |
| R7 | Version history with linked ticket notifications |
| R8 | Per-channel decision registry |
| R9 | UX commands: /maro decisions, decision show/change/deprecate |
| R10 | Decision detection from conversation |
| R11 | Decision cards with status-dependent buttons |
| R12 | Active decisions in context (draft, review, duplicate) |

**Full requirements:** `.planning/phases/30-decision-as-entity/REQUIREMENTS.md`

### Phase 31: Architecture Hardening

**Status:** COMPLETE (4/4 plans)

**Objective:** Consolidate intents into super-modes, elevate safety invariants to hard rules, and simplify over-specified systems.

**Mantra:** "Feel like a product, not an OS kernel."

**Key Changes:**

| Area | Current | Target |
|------|---------|--------|
| **Intents** | 13 fine-grained intents | 5 super-modes (BUILD, OPERATE, DECIDE, THINK, CHAT) |
| **Classifier** | Heavy "parse universe" prompt | Two-stage: lightweight classify + conditional extract |
| **Decision projection** | Design note | Hard invariant: MANAGED_SECTION_ONLY |
| **Canonical messages** | Implicit | Explicit: idempotent, version-checked, failure-safe |
| **Commit log vs state** | Blurred | Clear: log=append-only, messages=mutable |
| **Sync semantics** | Implied | Explicit: preflight=blocking, sync=informational |

**Requirements:**
- R1: Intent super-modes (5 conceptual groups)
- R2: Two-stage intent classification
- R3: Decision projection invariants (hard rules)
- R4: Slack as UI, not authority
- R5: Canonical message idempotency
- R6: Commit log vs state separation
- R7: Simplified draft lifecycle (evaluate)
- R8: Sync semantics clarity

**Full requirements:** `.planning/phases/31-architecture-hardening/REQUIREMENTS.md`

### Phase 32: Product Invariants

**Status:** In Progress (5/6 plans)

**Objective:** Formalize the system's architectural principles as enforced invariants. Stop being "smart" and become reliable.

**Mantra:** "This is no longer a bot. It's a conversation-native version control system."

**Invariants:**

| ID | Invariant | Enforcement |
|----|-----------|-------------|
| I1 | SuperMode = Sole UI Contract | User messages use super-modes only, intents hidden |
| I2 | Slack = UI (State Ownership) | Handlers read-only, mutations via graph dispatch |
| I3 | Commit Log = Append-Only | Event-sourced history, canonical messages rebuildable |
| I4 | MANAGED_SECTION = Law | CI gate, lint rules, never-catch ManagedSectionError |
| I5 | Draft Lifecycle = 3 States | Drafting/Ready/Published (internal complexity hidden) |

**Implementation Waves:**
- Wave 1: Foundations (32-01 to 32-03) — SuperMode UI, Commit log schema, Draft states
- Wave 2: Enforcement (32-04 to 32-05) — Slack layer separation, CI gate
- Wave 3: Documentation (32-06) — Architecture docs update

**Full requirements:** `.planning/phases/32-product-invariants/REQUIREMENTS.md`

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
| 26. Context-Aware Intent | v1.2 | 4/4 | Complete | 2026-01-22 |
| 27.1 User Identity & Attribution | v1.2 | 1/1 | Complete | 2026-01-23 |
| 27.2 Participant Map & Turn-Taking | v1.2 | 1/1 | Complete | 2026-01-23 |
| 27.3 Multi-Author Drafts & Conflicts | v1.2 | 1/1 | Complete | 2026-01-23 |
| 27.4 State-Bound Approvals | v1.2 | 1/1 | Complete | 2026-01-23 |
| 27.5 WorkItem Ownership & Audit | v1.2 | 1/1 | Complete | 2026-01-23 |
| 27.6 Notifications & Slack UX | v1.2 | 1/1 | Complete | 2026-01-23 |
| 28. Structured Draft Evolution | v1.2 | 5/? | In Progress | - |
| 29. Sync on Demand | v1.2 | 4/4 | Complete | 2026-01-23 |
| 30. Decision as First-Class Entity | v1.2 | 8/8 | Complete | 2026-01-23 |
| 31. Architecture Hardening | v1.2 | 4/4 | Complete | 2026-01-24 |
| 32. Product Invariants | v1.2 | 5/6 | In Progress | - |

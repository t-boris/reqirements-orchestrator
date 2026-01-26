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

**Status:** COMPLETE (6/6 plans)

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

### Phase 33: Anchor Message Architecture

**Status:** COMPLETE (5/5 plans)

**Objective:** Shift from thread-centric to object-centric design. Canonical messages become anchors for entity lifecycles — threads exist to manage objects, not for conversation.

**Mantra:** "Thread exists for managing a specific object of reality, not for conversation."

**Core Insight:**
```
Channel = Repository
Canonical Message = Object HEAD
Thread = Working Tree for that object
Registry = Database of objects
Jira = Projection
```

**Key Rules:**

| Rule | Description |
|------|-------------|
| A1 | Any "created/approved/updated" message is an anchor message |
| A2 | Each anchor has object_id (DEC-41, SCRUM-166) and object_type (Decision, WorkItem) |
| A3 | Messages in thread inherit object_id as context automatically |
| A4 | Commands in thread default to the anchor's object ("update", "deprecate", "add story") |

**What Changes:**

| Current | Target |
|---------|--------|
| Thread exists → discussion happens → tickets emerge | Object created → canonical message → thread = lifecycle |
| Thread binding is optional metadata | Thread binding is mandatory object reference |
| Commands require explicit ID | Commands inherit ID from anchor |
| Bot is chat participant | Bot is state management interface |

**Depends on:** Phase 32 (invariants provide foundation)

**Full requirements:** `.planning/phases/33-anchor-message-architecture/REQUIREMENTS.md`

### Phase 34: File Attachment Processing

**Status:** COMPLETE (8/8 plans)

**Objective:** Enable bot to read PDF, DOCX, Markdown attachments from Slack messages. Policy-based hybrid: deterministic rules + LLM for chunk retrieval.

**Mantra:** "Attachments are opt-in by default, pinned attachments become part of context, everything else is retrieval-based."

**Core Model:**

1. **Attachment = First-Class Entity** (not just text in history)
   - id, file_id, filename, mimetype, extracted_text, summary, status, pinned

2. **Two Usage Modes:**
   - **Pinned** — User controls via button, auto-included in BUILD/THINK
   - **On-Demand** — Retrieval-based, only when relevant + user references

3. **Intent-Scoped Rules:**

   | Mode | Attachment Policy |
   |------|-------------------|
   | CHAT | Don't include. Offer: "I see an attachment, want me to use it?" |
   | THINK | Pinned auto + top-K chunks from retrieval |
   | BUILD | Pinned auto + structural fragments (requirements, AC) |
   | OPERATE | Only logs, JSON, stacktraces — via retrieval |
   | DECIDE | Pinned + cited chunks with source references |

4. **Never "include whole file"** — only chunks (300-800 tokens), top 3-6 per retrieval

5. **Transparency UI:** `📎 Used: spec.pdf (sections: Auth, Permissions)` + `[Show sources]` + `[Stop using]`

**Implementation Waves:**

| Wave | Plans | Focus |
|------|-------|-------|
| 1 | 34-01, 34-02 | Foundation: Attachment schema/store, file event handling |
| 2 | 34-03, 34-04 | Processing: Extraction pipeline, chunking + search index |
| 3 | 34-05, 34-06 | Integration: Pin/unpin mechanics, intent-scoped rules |
| 4 | 34-07, 34-08 | Polish: Transparency UI, retrieval context injection |

**Plans:**

- [x] 34-01: Attachment Schema + AttachmentStore (2026-01-23)
- [x] 34-02: File Event Handler (file_shared, message files) (2026-01-23)
- [x] 34-03: Extraction Pipeline (download → extract → summarize) (2026-01-23)
- [x] 34-04: Chunking + Full-Text Search Index (2026-01-24)
- [x] 34-05: Pin/Unpin Mechanics + UI Buttons (2026-01-24)
- [x] 34-06: Intent-Scoped Inclusion Rules (2026-01-23)
- [x] 34-07: Transparency UI (Used, Show Sources, Stop Using) (2026-01-24)
- [x] 34-08: Retrieval Context Injection into Prompts (2026-01-24)

**Existing Infrastructure:**
- `src/documents/extractor.py` — PDF, DOCX, TXT, MD extraction (pypdf, python-docx)
- `src/documents/slack.py` — `download_and_extract()` for Slack files

**Full context:** `.planning/phases/34-file-attachment-processing/34-CONTEXT.md`
**Research:** `.planning/phases/34-file-attachment-processing/34-RESEARCH.md`

**Depends on:** Phase 33 (anchor messages for file-based WorkItems)

### Phase 35: Multi-Intent Task Orchestration

**Status:** COMPLETE (8/8 plans)

**Objective:** Replace single-intent classification with TaskPlan orchestration. Messages become task lists where each intent is a task with priority and side-effect type.

**Mantra:** "Parse the universe of user intent, not just the top-1 classification."

**Problem:**
- Users write compound requests: "create stories, check duplicates, and review architecture"
- Single-winner classification loses context and frustrates users
- Bot appears to "not understand" multi-part requests

**Solution (Variant 3: TaskPlan):**

1. **LLM returns TaskPlan** instead of single intent:
   ```
   TaskPlan:
     - task_id, intent, mode (BUILD/OPERATE/DECIDE/THINK/CHAT)
     - requires_user_input: bool
     - side_effects: NONE | SLACK | JIRA | REGISTRY
     - dependencies: [task_id...]
     - confidence
   ```

2. **Executor applies ordering rules:**
   - First: OPERATE/SAFETY (preflight, duplicates, conflicts)
   - Then: BUILD (draft/transform)
   - Then: THINK (review)
   - Last: DECIDE (approval) — only with explicit user confirmation

3. **Canonical UX response:**
   ```
   I see 3 actions:
   1. Create Epics from Decisions
   2. Check Jira duplicates
   3. Provide architecture recommendations

   Executing 1 and 2 now. For 3 — OK?
   ```

**Key Rules:**
- Safe tasks execute automatically (analysis, preview, search, draft collection)
- Dangerous tasks require confirmation (Jira create/update, deprecate, mass changes)
- History determines context/anchor, but new tasks come only from trigger message
- Multi-intent detection: multiple intents returned, low top-1 confidence, or "and/also/plus" in text

**Depends on:** Phase 34 (attachment context in task execution)

**Implementation Waves:**

| Wave | Plans | Focus |
|------|-------|-------|
| 1 | 35-01, 35-02 | Foundation: TaskPlan schema/store, multi-intent classification |
| 2 | 35-03, 35-04 | Integration: Safety classification, state integration |
| 3 | 35-05, 35-06 | Execution: Task executor, Status Card UI |
| 4 | 35-07, 35-08 | Polish: Button handlers, dispatch integration |

**Plans:**

- [x] 35-01: TaskPlan Schema + Store (2026-01-24)
- [x] 35-02: Multi-Intent Classification (2026-01-24)
- [x] 35-03: Task Safety Classification (2026-01-24)
- [x] 35-04: TaskPlan State Integration (2026-01-24)
- [x] 35-05: Task Executor Orchestration (2026-01-24)
- [x] 35-06: UI Status Card (2026-01-24)
- [x] 35-07: Button Handlers + Version Binding (2026-01-24)
- [x] 35-08: Integration + Dispatch Updates (2026-01-24)

**Full context:** `.planning/phases/35-multi-intent-task-orchestration/35-CONTEXT.md`
**Research:** `.planning/phases/35-multi-intent-task-orchestration/35-RESEARCH.md`

### Phase 36: Question Engine — Conversation Driver

**Status:** COMPLETE (7/7 plans)

**Objective:** Transform MARO from "event recorder" to "conversation leader". Questions become first-class tasks in TaskPlan, and the bot actively drives toward complete information.

**Mantra:** "Questions are actions, not text responses."

**Problem:**
- Bot reacts but doesn't lead — it records events but doesn't drive conversations
- When information is missing, bot loops silently or asks generic questions
- No structured question types — "acceptance criteria?" is too philosophical
- No question budget — bot can become annoying or give up too early

**Solution: Question Engine as State Machine**

1. **Question Tasks in TaskPlan:**
   ```
   TaskType:
     - ASK_USER (side_effect: SLACK) — generic question
     - COLLECT_FIELD — get specific field value
     - CONFIRM_SCOPE — choice from options
     - RESOLVE_CONFLICT — pick A or B
   ```

2. **Two Triggers for Bot-Led Questions:**
   - **Trigger A:** Blocked by missing info → generate ASK_USER task
   - **Trigger B:** High uncertainty (2-3 interpretations close in confidence) → CONFIRM_SCOPE

3. **Question Budget:**
   - Max 2 questions in a row without new user signal
   - After 2 unanswered → show partial preview with [Proceed] [Wait] [Cancel]

4. **Structured Question Types:**
   | Type | Example |
   |------|---------|
   | Scope | "Stories only under SCRUM-166?" [Yes] [Different parent] [New epic] |
   | Enumeration | "Give me 5-10 story titles or workstreams" |
   | Constraint | "Must-have: auth? audit logging?" |
   | Conflict | "Epic can't have parent. Remove parent or change type?" |

5. **Active/Passive Mode:**
   - **Active:** On @mention, /command, or BLOCKED task — bot leads
   - **Passive:** Plan DONE/CANCELED or 10min timeout — bot listens

**Canonical UX:**
```
User: "@Maro create all user stories under SCRUM-166"

Bot: "Got it. I see parent SCRUM-166. Creating stories plan."
Card:
  ✅ Duplicate check
  ⏳ Draft stories
  ⏸ Create in Jira (needs approval)

Bot: "To draft stories, pick approach:"
  [5 workstreams] (Bot suggests categories)
  [Give me titles] (User provides list)
  [Infer from decisions] (if decisions exist)
```

**Key Requirement:**
> When TaskPlan is BLOCKED due to missing info or ambiguity, MARO must generate an ASK_USER task and ask the minimal question needed to unblock progress, with buttons/options whenever possible. MARO must not silently stop or loop on empty extraction.

**Depends on:** Phase 35 (TaskPlan foundation)

**Implementation Waves:**

| Wave | Plans | Focus |
|------|-------|-------|
| 1 | 36-01, 36-02 | Foundation: QuestionTask schema, ConversationMode, StatePatch |
| 2 | 36-03, 36-04 | Core: QuestionCatalog, AnswerMapper, BudgetTracker |
| 3 | 36-05, 36-06 | Integration: Question executor, Mode integration |
| 4 | 36-07 | UI: Question blocks, Button handlers |

**Plans:**
- [x] 36-01: QuestionTask Schema (extends Task with question fields)
- [x] 36-02: ConversationMode + StatePatch (Active/Passive state machine)
- [x] 36-03: QuestionCatalog (hybrid template/LLM question generators)
- [x] 36-04: AnswerMapper + BudgetTracker (button/text processing, limits)
- [x] 36-05: Question Executor Integration (task_executor changes)
- [x] 36-06: Mode Integration + Budget Handler (dispatch integration)
- [x] 36-07: Question UI + Button Handlers (Slack UI)

### Phase 37: Unified Question Engine

**Status:** COMPLETE (5/5 plans)

**Objective:** Abstract Question Engine from providers. Unify the mechanism for asking questions while allowing different sources (catalog vs LLM-generated).

**Mantra:** "One engine, two providers, two target states."

**Architecture:**

1. **Question Engine (unified mechanism):**
   - When to ask (BLOCKED / ambiguity / conflict)
   - How to display (buttons, budget, active/passive)
   - How to accept answers (button→deterministic, text→LLM parse)
   - How to map to state (patch)
   - How to not spam (throttle, 2-question budget)

2. **QuestionProvider interface:**
   - `CatalogProvider` — for tickets/structured work (existing QuestionCatalog)
   - `FreeformProvider` — for review/architecture (LLM-generated but structured)

3. **ReviewState schema:**
   ```python
   ReviewState:
     topic: str
     assumptions: list[dict]
     constraints: list[dict]
     risks: list[dict]
     open_questions: list[dict]
     proposed_decisions: list[dict]
   ```

4. **FreeformProvider output (structured ReviewQuestion):**
   ```python
   ReviewQuestion:
     goal: str  # "disambiguate transport layer"
     question: str  # "Do we need real-time guarantees?"
     expected_answer_type: Literal["choice", "text", "number"]
     options: list[str]  # For choice type
     maps_to: str  # "review_state.assumptions.realtime"
   ```

**Key Insight:** Same UX (buttons, budget, throttle) for both ticket collection and architecture review. Different content sources, unified mechanism.

**Depends on:** Phase 36 (Question Engine foundation)

**Implementation Waves:**

| Wave | Plans | Focus |
|------|-------|-------|
| 1 | 37-01, 37-02 | Foundation: QuestionProvider interface, ReviewState schema, CatalogProvider |
| 2 | 37-03, 37-04 | Providers: FreeformProvider, AnswerMapper extension, ReviewStateStore |
| 3 | 37-05 | Integration: QuestionEngine facade, review_continuation |

**Plans:**
- [x] 37-01: QuestionProvider interface + ReviewState schema (2026-01-24)
- [x] 37-02: CatalogProvider extraction (2026-01-24)
- [x] 37-03: FreeformProvider implementation (2026-01-24)
- [x] 37-04: AnswerMapper extension + ReviewStateStore (2026-01-24)
- [x] 37-05: QuestionEngine + review_continuation integration (2026-01-24)

**Full context:** `.planning/phases/37-unified-question-engine/37-CONTEXT.md`

### Phase 38: Context Architecture

**Status:** COMPLETE (6/6 plans)

**Objective:** Refactor context building from "load everything we can" to "build from goal". Context is determined by task, not by what's available.

**Mantra:** "Context is built from goal, not from availability."

**Key Concepts:**

1. **ContextSpec** — Goal-driven context request:
   ```python
   ContextSpec:
     mode: SuperMode  # BUILD, OPERATE, etc.
     target: str  # channel_id, thread_ts, workitem_id
     purpose: str  # "extract draft fields", "explain decision"
     budget_tokens: int
     required_artifacts: list[str]  # ["review_artifact", "decisions"]
   ```

2. **Three-Layer Context Model:**
   - **Layer A: Canonical State (DB)** — Registry, anchors, decisions, workitems, TaskPlan
   - **Layer B: Working History** — Normalized messages with rendered blocks (bot blocks → text)
   - **Layer C: Retrieval Add-ons** — Attachments, Jira snapshots, summaries

3. **Block Rendering:**
   - Slack blocks converted to `rendered_text` for bot messages
   - MessageIndex cache for expensive conversions
   - `message_type: "user" | "bot" | "system"`

4. **ContextPacket Output:**
   ```
   === SYSTEM STATE ===
   [canonical from Layer A]

   === CONVERSATION ===
   [normalized history from Layer B]

   === RETRIEVED ===
   [chunked add-ons from Layer C]
   ```

**Key Changes:**
- `review_artifact` moves from checkpoint to DB (source of truth, not cache)
- `thread_state` narrows to binding + execution only
- `conversation_context` gets block renderer + MessageIndex cache
- `channel_decisions` is Layer A, not fallback

**Depends on:** Phase 37 (Question Engine provides structured state patterns)

**Implementation Waves:**

| Wave | Plans | Focus |
|------|-------|-------|
| 1 | 38-01, 38-02, 38-03 | Foundation: ReviewArtifactStore, BlockRenderer, ContextSpec/Packet |
| 2 | 38-04 | MessageIndex with LRU cache |
| 3 | 38-05 | ContextBuilder three-layer assembly |
| 4 | 38-06 | Integration: OPS explain fix, handler context building |

**Plans:**
- [x] 38-01: ReviewArtifactStore (DB persistence for review artifacts) (2026-01-25)
- [x] 38-02: BlockRenderer (Slack blocks to readable text) (2026-01-25)
- [x] 38-03: ContextSpec + ContextPacket models (2026-01-25)
- [x] 38-04: MessageIndex (LRU cache for rendered messages) (2026-01-25)
- [x] 38-05: ContextBuilder (three-layer context assembly) (2026-01-25)
- [x] 38-06: Integration (OPS explain fix, handler updates) (2026-01-25)

**Full context:** `.planning/phases/38-context-architecture/38-CONTEXT.md`
**Research:** `.planning/phases/38-context-architecture/38-RESEARCH.md`

### Phase 39: Intent Classification v2

**Status:** In Progress (2/7 plans)

**Objective:** Rebuild intent classification with 2-stage architecture, state-based gates, unified IntentEnvelope output, and margin-based ambiguity policy.

**Mantra:** "State gates before LLM. Margin before action. Ambiguity before wrong action."

**Key Changes:**

| Current | Target |
|---------|--------|
| Single IntentResult OR TaskPlanProposal | Unified IntentEnvelope (single/plan/ambiguous) |
| confidence only | confidence + margin + alternatives |
| LLM-first classification | Stage 0 gates → Stage 1 mode → Stage 2 intent |
| REVIEW allowed with active draft | Draft priority gate blocks REVIEW |
| DISCUSSION can loop | Terminal intents = single response → END |
| Implicit target resolution | Explicit target from anchor, LLM confirms |

**Architecture:**

1. **Stage 0: Deterministic pre-gates** (state-based, no LLM)
   - Terminal handling (commands, CHAT intents → END)
   - Active TaskPlan continuation (bypass classifier)
   - Draft priority gate (BUILD intents prioritized)
   - Risk guard (low margin + write → ambiguous)

2. **Stage 1: Mode classification** (lightweight LLM)
   - Returns mode_candidates with scores
   - Detects multi_intent signal

3. **Stage 2: Intent/TaskPlan** (full LLM)
   - Returns IntentEnvelope (single/plan/ambiguous)
   - Minimal extraction (identifiers only)

**IntentEnvelope Output:**
```json
{
  "kind": "single|plan|ambiguous",
  "mode": "BUILD|THINK|DECIDE|OPERATE|CHAT",
  "intent": "...",
  "confidence": 0.0,
  "margin": 0.0,
  "risk_level": "safe|write|mass_write|destructive",
  "targets": {"jira_key": null, "decision_id": null, "workitem_id": null},
  "alternatives": [...]
}
```

**Acceptance Criteria:**
1. Active draft + "Do you think only one epic is enough?" → DRAFT_REFINE, not REVIEW
2. "hello" → CHAT → single response → END (no loops)
3. Multi-intent "create stories and check duplicates" → kind=plan, tasks ordered safely
4. Any Jira write with low margin → kind=ambiguous with choices
5. BLOCKED Question task + user reply → bypass classifier, route to AnswerMapper
6. All outputs match JSON schema, parse errors → fallback to ambiguous

**Depends on:** Phase 38 (Context Architecture provides ContextSpec/ContextPacket)

**Full spec:** `.planning/phases/39-intent-classification-v2/39-CONTEXT.md`

**Implementation Waves:**

| Wave | Plans | Focus |
|------|-------|-------|
| 1 | 39-01, 39-02 | Foundation: IntentEnvelope schema, Stage 0 pre-gates |
| 2 | 39-03, 39-04 | Classification: Stage 1 mode, Stage 2 intent |
| 3 | 39-05, 39-06 | Policy: Ambiguity policy, Unified router |
| 4 | 39-07 | Integration: Graph routing, terminal handling |

**Plans:**
- [x] 39-01: IntentEnvelope schema (unified output format) (2026-01-26)
- [x] 39-02: Stage 0 pre-gates (deterministic state-based gates) (2026-01-26)
- [ ] 39-03: Stage 1 mode classification (lightweight LLM)
- [ ] 39-04: Stage 2 intent extraction (full LLM)
- [ ] 39-05: Ambiguity policy + risk guards
- [ ] 39-06: Unified intent router
- [ ] 39-07: Graph integration + terminal handling

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
| 32. Product Invariants | v1.2 | 6/6 | Complete | 2026-01-24 |
| 33. Anchor Message Architecture | v1.2 | 5/5 | Complete | 2026-01-24 |
| 34. File Attachment Processing | v1.2 | 8/8 | Complete | 2026-01-24 |
| 35. Multi-Intent Task Orchestration | v1.2 | 8/8 | Complete | 2026-01-24 |
| 36. Question Engine | v1.2 | 7/7 | Complete | 2026-01-24 |
| 37. Unified Question Engine | v1.2 | 5/5 | Complete | 2026-01-24 |
| 38. Context Architecture | v1.2 | 6/6 | Complete | 2026-01-25 |
| 39. Intent Classification v2 | v1.2 | 2/7 | In Progress | - |

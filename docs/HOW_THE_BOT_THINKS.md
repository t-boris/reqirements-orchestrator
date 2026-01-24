# How MARO Thinks: Complete Bot Intelligence Guide

This document explains the complete decision-making logic, rules, prompts, and behavior patterns of the MARO (Managed Automated Requirements Orchestrator) Slack bot.

---

## Table of Contents

1. [Core Architecture](#1-core-architecture)
   - 1.1 High-Level Flow
   - 1.2 Identity & State
   - 1.3 Git Model
   - 1.4 LLM Providers
   - 1.5 StructuredDraft: The Design Model (Phase 28)
   - 1.6 Preflight: Universal Guardrail (Phase 29)
   - 1.7 Decision: First-Class Entity (Phase 30)
   - 1.8 Product Invariants (Phase 32)
   - 1.9 Multi-Intent Task Orchestration (Phase 35)
   - 1.10 Question Engine — Conversation Driver (Phase 36)
2. [Intent Classification](#2-intent-classification)
   - 2.0 User Modes (Phase 31)
   - 2.6 Multi-Intent Detection (Phase 35)
3. [Governance Rules](#3-governance-rules)
   - 3.1 Core Model
   - 3.2 Duplicate Handling Rules
   - 3.3 Registry Rules
   - 3.4 Context Rules
   - 3.5 Commit Semantics
   - 3.6 Commit Log vs State (Phase 31)
   - 3.7 Sync Semantics (Phase 31)
4. [LLM Prompts Reference](#4-llm-prompts-reference)
5. [State Machine & Workflows](#5-state-machine--workflows)
6. [Decision Logic](#6-decision-logic)
   - 6.1 Decision Node Flow
   - 6.2 Extraction Continuation Logic
   - 6.3 Question Batching
   - 6.4 User Input Classification (Phase 28)
   - 6.5 Form-Dependent Validation (Phase 28)
   - 6.6 Lifecycle-Aware Questions (Phase 28)
7. [Response Generation](#7-response-generation)
8. [Key Behavior Patterns](#8-key-behavior-patterns)

---

## 1. Core Architecture

### 1.1 High-Level Flow

```
User Message
    ↓
Event Router (pre-graph filtering)
    ↓
Intent Classification (LLM)
    ↓
Graph Routing (LangGraph)
    ├─→ WorkItem Flow (extraction → validation → decision)
    ├─→ Draft Refine Flow (meta-questions about draft → clarification)
    ├─→ Draft Transform Flow (structural mutations → show new form)
    ├─→ Review Flow (persona-based analysis)
    ├─→ Discussion Flow (brief conversational)
    ├─→ Scope Gate Flow (ambiguous → 3-button UI)
    ├─→ Change Request Flow (modify existing Jira issues)
    ├─→ Jira Command Flow (field modifications)
    ├─→ Sync Flow (bulk channel sync)
    ├─→ Jira Search Flow (search existing)
    └─→ Decision Flow (Phase 30) (extract decision → create entity → show card)
    ↓
Slack Response
```

### 1.2 Identity & State

**Canonical Identity:** `session_id = team:channel:thread_ts`

Every interaction is tracked per-thread with:
- Step count (loop protection, MAX_STEPS = 10)
- Phase (COLLECTING, AWAITING_USER, APPROVED, REJECTED)
- Draft state (accumulated requirements)
- Pending questions (for re-ask logic)
- Workflow step (for button validation)

### 1.3 Git Model

MARO follows a Git-like model for truth management:

| Git Concept | MARO Equivalent | Description |
|-------------|-----------------|-------------|
| Repository | Channel | Source of truth, owns work item registry |
| Working Tree | Thread | Exploration/drafting space |
| Commit | Approved Decision | Immutable truth entry in channel log |
| Remote | Jira | Deployment target (replica of truth) |
| Push | Sync/Publish | Propagate truth to Jira |

**Key insight:** Jira is not the source of truth. Jira is where truth gets *deployed* after being decided in the channel.

**Mantra:** "Threads propose. Channels decide. Jira executes."

```
Thread: "We need rate limiting"
    ↓ (draft)
Channel: "Approved as WORK-123"
    ↓ (sync)
Jira: "SCRUM-456 created"
```

### 1.4 LLM Providers

The bot uses a provider-agnostic adapter layer supporting:

| Provider | Default Model | Use Case |
|----------|--------------|----------|
| Gemini | `gemini-3-flash-preview` | Primary (default) |
| OpenAI | `gpt-4o-mini` | Backup |
| Anthropic | `claude-3-5-sonnet-latest` | Backup |

**Default Parameters:**
- Temperature: 0.7
- Max tokens: 4096
- Timeout: 30 seconds

### 1.5 StructuredDraft: The Design Model (Phase 28)

**Core shift:** From "bot collects text for a ticket" to "bot manages a typed design object with lifecycle states and structural mutations."

**Mantra:** Draft is a data structure representing the shape of work, not a paragraph of text.

#### Draft as Design Object

The traditional TicketDraft was a text container:
```python
# OLD: Text container
class TicketDraft:
    title: str
    problem: str
    acceptance_criteria: list[str]
    # Just fields holding text
```

The new StructuredDraft is a **typed design object**:
```python
# NEW: Typed design object with structure
class StructuredDraft:
    kind: DraftKind           # SINGLE_ITEM vs PLAN
    scope: DraftScope         # SINGLE, EPICS_ONLY, FULL_PLAN
    lifecycle: DraftLifecycle # State machine position
    version: int              # Every mutation increments
    items: list[DraftItem]    # Multiple items with hierarchy
    change_log: list[DraftChange]  # Audit trail
```

#### DraftKind: Shape of the Draft

| Kind | Description | Example |
|------|-------------|---------|
| `SINGLE_ITEM` | One ticket | "Create a login page" |
| `PLAN` | Multiple items with structure | "Build auth system" (3 epics, 12 stories) |

#### DraftScope: Generation Intent

| Scope | Description | Typical Use |
|-------|-------------|-------------|
| `SINGLE` | Just this one item | Single story or task |
| `EPICS_ONLY` | Only epics, no stories | High-level planning |
| `FULL_PLAN` | Epics + stories | Complete breakdown |

#### DraftLifecycle: State Machine

```
EMPTY → SINGLE_ITEM → PLAN → PLAN_REFINED → APPROVED → COMMITTED
  │         │           │          │            │           │
  └─ No content yet     │          │            │           └─ In Jira
                        │          │            └─ User approved
                        │          └─ User refined items
                        └─ Multiple items exist
```

**Key insight:** The lifecycle determines what questions to ask and what validation to apply.

#### DraftItem: Individual Work Items

Each item in the draft has:
```python
class DraftItem:
    id: str                    # UUID for reference
    issue_type: IssueType      # EPIC, STORY, TASK, BUG
    title: str
    goal: str
    status: DraftItemStatus    # PROPOSED → APPROVED → COMMITTED
    parent_id: Optional[str]   # For stories under epics
    acceptance_criteria: list[str]
    jira_key: Optional[str]    # Set after Jira creation
```

#### Structural Mutations

User decisions **mutate draft form**, not just update text:

| User Says | Mutation | Result |
|-----------|----------|--------|
| "Split into epics" | `split_to_plan()` | kind → PLAN, lifecycle → PLAN |
| "Add a story for auth" | `add_items()` | New DraftItem appended |
| "Merge the first two" | `merge_items()` | Items combined, count reduced |
| "Make this an epic" | `elevate_to_epic()` | issue_type → EPIC |
| "Break down into stories" | `decompose_to_stories()` | Stories created under epic |
| "Only epics" | `change_scope()` | scope → EPICS_ONLY |
| "Remove the second one" | `remove_items()` | Item deleted from list |

Every mutation:
1. Updates the draft structure
2. Increments `version`
3. Logs to `change_log`
4. Shows updated structure to user (R8)

### 1.6 Preflight: Universal Guardrail (Phase 29)

**Core principle:** Every write operation goes through preflight — no exceptions.

Preflight is the "distributed version control for meaning". Before any Jira write:

```
Local State (what we think is true)
    ↓
Preflight Check (fetch current Jira state)
    ↓
Conflict Classification
    ↓
[IDEMPOTENT] → Auto-succeed, sync local
[SAFE_DRIFT] → Proceed with warning
[REAL_CONFLICT] → Block, require choice
[STRUCTURAL] → Block, explain why
```

#### Conflict Types

| Type | Meaning | Bot Action |
|------|---------|------------|
| **IDEMPOTENT** | Operation already done in Jira | Auto-succeed, update local to match |
| **SAFE_DRIFT** | Changes don't overlap | Ask but default to proceed |
| **REAL_CONFLICT** | Same fields changed | Block until user explicitly chooses |
| **STRUCTURAL** | Invalid operation (ticket deleted, type mismatch) | Block with explanation |

**Key insight:** IDEMPOTENT auto-succeeds. All others require user choice.

#### Sync Tracking

Each tracked issue has:
```python
jira_updated: datetime  # When Jira was last modified
last_synced: datetime   # When we last fetched from Jira
status: str             # Current Jira status
assignee: str           # Current Jira assignee
```

This enables detecting external changes since last sync.

#### Never Auto-Fix

Conflicts are never auto-resolved. Human choice required:
- "Use Jira version"
- "Use channel version"
- "Manual merge"

This preserves the "communication is source of truth" principle.

### 1.7 Decision: First-Class Entity (Phase 30)

**Core shift:** Decisions are versioned entities. Jira is a projection, not the source.

**Mantra:** "Decisions are versioned, Jira is a projection."

#### Decision Entity

```python
class Decision:
    id: str                    # UUID
    channel_id: str            # Channel that owns this decision
    decision_type: DecisionType  # ARCH, SCOPE, CONSTRAINT, PRIORITY, STRUCTURE, PROCESS
    title: str
    description: str
    status: DecisionStatus     # PROPOSED → APPROVED → DEPRECATED/REPLACED
    version: int               # Increments on every change
    canonical_message_ts: str  # Slack message that represents this decision
```

#### Decision Types

| Type | Description | Jira Projection |
|------|-------------|-----------------|
| **ARCH** | Architecture decisions | Description → Architecture section |
| **SCOPE** | Scope boundaries | Description → Scope section |
| **CONSTRAINT** | Technical constraints | Description → Constraints section |
| **PRIORITY** | Priority decisions | Priority field / Labels |
| **STRUCTURE** | Work structure (epic/story breakdown) | Parent/Link relations |
| **PROCESS** | Process decisions | Labels / Custom field |

#### Decision Lifecycle

```
PROPOSED → APPROVED → DEPRECATED/REPLACED
    │          │              │
    └─ Draft   └─ Active      └─ Historical (with pointer to replacement)
```

Same object, four visual identities:
1. **Idea** → Compact card during discussion
2. **Proposal** → Full block for approval ("are you sure?" moment)
3. **Law** → Authoritative reference (no longer conversational)
4. **Record** → Commit log entry (pure signal)

#### Canonical Message Pattern

Each Decision has **one canonical message** in the channel — like HEAD in git:

```
Channel (what is true now)
    │
    ├── Decision DEC-41 (canonical message, updated in place)
    │       │
    │       └── Thread (discussion, examples, wording changes)
    │
    ├── Decision DEC-42 (canonical message)
    │       │
    │       └── Thread
    ...
```

- Canonical message is pinned
- Always reflects current version
- Never deleted, only updated or marked deprecated
- Thread = working area for discussion

**Key insight:** Channel shows "what is true now", not "what happened".

#### Decision → Jira Projection

When a decision is approved:
1. Decision status → APPROVED
2. Linked tickets identified (DecisionLink)
3. Preflight runs on all linked tickets
4. Managed sections updated in Jira descriptions

#### Managed Sections

MARO writes only to clearly marked sections:

```markdown
## Decisions (managed by MARO)
• DEC-41 v4 – Use ISO 8601 dates
• DEC-57 v2 – PostgreSQL for persistence
---
```

Everything outside this block is user-owned. MARO never overwrites hand-written content.

#### DecisionLink

Maps decisions to Jira tickets:

```python
class DecisionLink:
    decision_id: str
    jira_key: str
    field_path: JiraFieldPath  # Where in Jira this projects
    synced_version: int        # Last version synced to this ticket
    synced_at: datetime
```

This enables:
- Deterministic mapping (decision type → known field)
- Incremental sync (only update if version changed)
- Audit trail (which version is in Jira)

#### Version-Bound Approvals

Every button includes decision ID + version:

```json
{
  "decision_id": "abc-123",
  "version": 4
}
```

When clicked:
- If `button.version == decision.version`: Proceed
- If `button.version != decision.version`: "Decision updated, please review"

This prevents acting on stale decisions after changes.

#### Version-Bound Approvals (Drafts)

Every button includes the draft version:
```json
{
  "draft_id": "abc-123",
  "version": 4
}
```

When clicked:
- If `button.version == draft.version`: Proceed
- If `button.version != draft.version`: "Outdated, please review new structure"

This prevents acting on stale state after transforms.

### 1.8 Product Invariants (Phase 32)

**Core principle:** Invariants are physics, not rules. The system makes wrong paths hard, not just discouraged.

#### The 5 Invariants

| ID | Invariant | Enforcement |
|----|-----------|-------------|
| **I1** | SuperMode = Sole UI Contract | Type + display helpers |
| **I2** | Slack = UI | Handlers dispatch, don't write |
| **I3** | Commit Log = Append-Only | CommitLogStore has no update/delete |
| **I4** | MANAGED_SECTION = Law | CI property tests |
| **I5** | Draft Lifecycle = 3 States | UserDraftState enum |

#### 4-Layer Protection

1. **Layer 0: Types** — InvariantViolation hierarchy makes wrong path hard
2. **Layer 1: Boundaries** — Gateway pattern (one door, one key)
3. **Layer 2: Tokens** — PreflightToken proves check passed
4. **Layer 3: CI Gates** — Property tests, forbidden imports
5. **Layer 4: Runtime** — Structured logs, metrics

#### Slack Handler Invariant (I2)

Handlers are READ-ONLY for truth stores:

```python
# WRONG (violates I2)
async def handle_decision_approve(ack, body, client):
    async with get_connection() as conn:
        store = DecisionStore(conn)
        await store.transition_to_approved(decision_id)  # Direct write!

# CORRECT (respects I2)
async def handle_decision_approve(ack, body, client):
    await dispatch_action(
        action_type="decision_approve",
        payload={"decision_id": decision_id},
        channel_id=channel_id,
    )
```

**Key insight:** Message failures don't block state updates. State is truth, message is presentation.

#### Commit Log Invariant (I3)

CommitLogStore is append-only:

```python
class CommitLogStore:
    async def append(self, entry: CommitLogEntry) -> None
    async def get_by_entity(self, entity_type, entity_id) -> list
    async def get_latest_snapshot(self, entity_type, entity_id) -> dict

    # NO update() method
    # NO delete() method
```

Canonical messages can be rebuilt from log at any time.

#### Escape Hatch

When invariants must be bypassed (production emergency):

1. Request override (admin/owner only)
2. Provide reason (mandatory text)
3. TTL = 10 minutes or single action
4. Posted to channel + audit log
5. Suggested: `/maro sync` to reconcile

**Must feel like pulling a fire alarm.** If override becomes habit, invariants are dead.

### 1.9 Multi-Intent Task Orchestration (Phase 35)

**Core shift:** Parse the full universe of user intent, not just top-1 classification.

**Mantra:** "Safe tasks execute. Dangerous tasks wait."

#### The Problem

Users write compound requests:
```
"Create stories from the decisions, check for duplicates, and review the architecture"
```

Single-winner classification loses context:
- Only one intent wins (e.g., WORKITEM_CREATE)
- Other intents (JIRA_SEARCH, REVIEW) are lost
- User must repeat themselves or feels "not understood"

#### The Solution: TaskPlan

Instead of single IntentResult, classification returns a **TaskPlan**:

```python
class TaskPlan:
    plan_id: str
    channel_id: str
    thread_ts: str
    tasks: list[Task]
    status: TaskPlanStatus  # PENDING → RUNNING → BLOCKED → DONE
    version: int            # For idempotent button handling

class Task:
    task_id: str
    mode: SuperMode         # BUILD, OPERATE, DECIDE, THINK, CHAT
    intent: Intent          # Fine-grained routing
    title: str              # Human-readable description
    status: TaskStatus      # PENDING → RUNNING → BLOCKED → DONE → CANCELED
    safety_level: SafetyLevel
    side_effects: list[SideEffect]
    depends_on: list[str]   # Task IDs this depends on
```

#### Safety Classification

Tasks are classified by safety level based on mode and side effects:

| Mode | Safety Level | Auto-Execute? |
|------|--------------|---------------|
| THINK | AUTO_EXECUTE | Yes |
| CHAT | AUTO_EXECUTE | Yes |
| BUILD | REQUIRES_CONFIRMATION | No |
| OPERATE | REQUIRES_CONFIRMATION | No |
| DECIDE | REQUIRES_CONFIRMATION | No |

**Override rule:** Any task with `SideEffect.JIRA` always requires confirmation.

```python
# Safe: runs immediately
Task(mode=THINK, intent=REVIEW) → AUTO_EXECUTE

# Dangerous: blocks for approval
Task(mode=BUILD, intent=WORKITEM_CREATE) → REQUIRES_CONFIRMATION
```

#### Canonical UX Response

When multi-intent detected, bot shows:

```
I see 3 actions:
1. Check Jira duplicates
2. Create stories from decisions
3. Review the architecture

Executing 1 now. For 2 and 3 — OK?
```

- Safe tasks execute immediately
- Dangerous tasks listed with approval prompt
- User can approve/reject each task

#### Status Card

A single editable message tracks all tasks:

```
🛠 MARO Plan — BUILD (2/3 tasks)

1) ✅ THINK: Check Jira duplicates
2) ⏳ BUILD: Create stories (waiting approval)
3) ⏸ THINK: Review architecture (blocked)

[Cancel plan]
(2) [Approve] [Reject]
```

**Throttling:** Updates limited to 1 every 1.5 seconds to avoid Slack rate limits. Significant events (task_completed, plan_completed) bypass throttle.

#### Two-Stage Classification

To avoid LLM overhead on simple messages:

1. **Stage 1:** Quick single-intent classification
2. **Stage 2:** Re-classify with multi-intent if signals detected

**Multi-intent signals:**
- Conjunctions: "and", "also", "plus", "then", "after that"
- Low confidence: <0.7 on single-intent
- Multiple action verbs: ≥2 verbs detected

```python
def should_use_multi_intent_classification(message, single_result):
    if has_multi_intent_markers(message):  # "and", "also"
        return True
    if single_result.confidence < 0.7:
        return True
    if count_action_verbs(message) >= 2:
        return True
    return False
```

#### Task Execution Flow

```
Multi-intent detected
    ↓
task_decomposer_node
    ├─ Convert TaskPlanProposal → TaskPlan
    ├─ Set dependencies between tasks
    ├─ Classify safety levels
    └─ Persist to database
    ↓
task_executor_node (recursive)
    ├─ Find next PENDING task (deps satisfied)
    ├─ If AUTO_EXECUTE → run immediately
    ├─ If REQUIRES_CONFIRMATION → set BLOCKED, show buttons
    └─ Continue until all DONE or BLOCKED
    ↓
dispatch handlers
    ├─ task_plan_created → post status card
    ├─ task_confirmation_required → show approval buttons
    ├─ task_plan_complete → post summary
    └─ task_failed → show error
```

#### Version-Bound Buttons

All buttons include plan version to prevent stale actions:

```python
# Button value format
value = f"{plan_id}:{task_id}:{plan.version}"

# On click
if plan.version != button_version:
    respond("⚠️ This action is outdated. The plan has been updated.")
    return
```

#### Cascade Cancel

When a task is rejected, all dependent tasks are canceled:

```python
def _cascade_cancel(task_plan, canceled_task_id):
    for task in task_plan.tasks:
        if canceled_task_id in task.depends_on:
            task.status = TaskStatus.CANCELED
            task.last_error = f"Dependency {canceled_task_id} was canceled"
            _cascade_cancel(task_plan, task.task_id)  # Recursive
```

### 1.10 Question Engine — Conversation Driver (Phase 36)

**Core shift:** From event recorder to conversation leader. Questions become first-class tasks.

**Mantra:** "Questions are tasks. Mode drives behavior. Budget prevents spam."

#### The Three Core Concepts

| Concept | Description |
|---------|-------------|
| **Questions as Tasks** | QuestionTask extends Task — questions are planned, prioritized, tracked |
| **Active/Passive Mode** | ACTIVE = bot leads, PASSIVE = bot listens |
| **Question Budget** | Max 2 unanswered questions before partial preview |

#### QuestionTask in TaskPlan

Questions are now tasks within the TaskPlan:

```python
class Task(BaseModel):
    # ... existing fields ...
    question_task: Optional[QuestionTask] = None  # For question-type tasks

    @property
    def is_question(self) -> bool:
        return self.question_task is not None

class QuestionTask(BaseModel):
    question_id: str
    question_type: QuestionType  # CONFIRM_SCOPE, COLLECT_FIELD, RESOLVE_CONFLICT, ASK_USER
    question_text: str
    target_field: Optional[str]  # Draft field this fills
    options: Optional[list[QuestionOption]]  # For button-based questions
    status: QuestionStatus  # PENDING, ANSWERED, SKIPPED
    answer: Optional[str]
```

#### Question Types

| Type | Purpose | Answer |
|------|---------|--------|
| **CONFIRM_SCOPE** | "Stories under this epic?" | Button click |
| **COLLECT_FIELD** | "What are the AC?" | Text reply |
| **RESOLVE_CONFLICT** | "Slack or Jira version?" | Button click |
| **ASK_USER** | Freeform fallback | Text reply |

#### Active/Passive Mode

```
PASSIVE ──@mention──→ ACTIVE
PASSIVE ──/command──→ ACTIVE
PASSIVE ──BLOCKED───→ ACTIVE

ACTIVE ──COMPLETE──→ PASSIVE
ACTIVE ──TIMEOUT───→ PASSIVE
ACTIVE ──CANCEL────→ PASSIVE
```

| Mode | Bot Behavior |
|------|--------------|
| ACTIVE | Leads conversation, posts questions, follows up |
| PASSIVE | Listens, acknowledges, doesn't ask unprompted |

#### Question Budget

Prevents bot spam by limiting consecutive questions:

```
Budget = 2 max unanswered questions

ask_question() → budget++
receive_answer() → budget = 0
budget >= 2 → show partial preview
```

Partial preview UI:
```
⏸️ I've hit my question limit

Still missing:
• acceptance_criteria
• scope

[Proceed with gaps] [Wait for input] [Cancel]
```

#### QuestionCatalog: Hybrid Generation

Templates for known patterns, LLM for flexibility:

| Type | Generation |
|------|------------|
| CONFIRM_SCOPE | Template ("Stories under {epic}?") |
| COLLECT_FIELD | LLM-generated (flexible prompts) |
| RESOLVE_CONFLICT | Template ("A or B?") |
| ASK_USER | LLM fallback |

#### AnswerMapper: Hybrid Processing

| Input | Processing | Confidence |
|-------|------------|------------|
| Button click | Deterministic → StatePatch | 1.0 |
| Text reply | LLM parsing → StatePatch | Varies |

Low confidence (<0.7) triggers clarification:
```
🤔 I'm not quite sure I understood.
Please reply again or use buttons if available.
```

#### Question Execution Flow

```
question_task detected in TaskPlan
    ↓
question_executor_node
    ├─ Check budget (is_exhausted?)
    │   └─ Yes → return budget_exhausted action
    ├─ Record question asked
    ├─ Set task → BLOCKED
    └─ Return question_posted action
    ↓
dispatch → post question UI
    ↓
User clicks button or replies
    ↓
handle_question_answer
    ├─ Apply StatePatch to state
    ├─ Mark task → DONE
    ├─ Reset budget
    └─ Continue execution
```

---

## 2. Intent Classification

### 2.0 User Modes (Phase 31)

Users should think in **5 modes**, not 13 intents. This simplifies user-facing communication while preserving fine-grained routing internally.

| Mode | User Perception | Internal Intents |
|------|-----------------|------------------|
| **BUILD** | "I'm building something" | WORKITEM_CREATE, DRAFT_REFINE, DRAFT_TRANSFORM |
| **OPERATE** | "I'm managing Jira" | JIRA_COMMAND, CHANGE_REQUEST, SYNC_REQUEST, TICKET_ACTION |
| **DECIDE** | "I'm recording a decision" | DECISION |
| **THINK** | "Help me think" | REVIEW, JIRA_SEARCH |
| **CHAT** | "Just talking" | DISCUSSION, META, AMBIGUOUS |

**Key insight:** 13 intents exist for fine-grained routing. 5 modes exist for user communication.

The `super_mode` field on `IntentResult` is populated on every classification, derived from the fine-grained intent via the `get_super_mode()` helper function.

**Example mappings:**
- User says "create a ticket" → Intent: `WORKITEM_CREATE` → SuperMode: `BUILD`
- User says "we decided to use PostgreSQL" → Intent: `DECISION` → SuperMode: `DECIDE`
- User says "help me design the API" → Intent: `REVIEW` → SuperMode: `THINK`
- User says "sync Jira" → Intent: `SYNC_REQUEST` → SuperMode: `OPERATE`
- User says "hi" → Intent: `DISCUSSION` → SuperMode: `CHAT`

### 2.1 Intent Types

The bot classifies every message into one of 9 intent types:

| Intent | Description | Example |
|--------|-------------|---------|
| **WORKITEM_CREATE** | Create NEW work item | "create a ticket for authentication" |
| ~~TICKET~~ | *Deprecated alias for WORKITEM_CREATE* | - |
| **DRAFT_REFINE** | Clarify/refine active draft structure | "is one epic enough?" |
| **DRAFT_TRANSFORM** | Structurally change active draft (Phase 28) | "split into multiple epics" |
| **CHANGE_REQUEST** | Modify existing Jira issue | "update the description" |
| **TICKET_ACTION** | Create items linked to existing ticket | "create stories for SCRUM-123" |
| **JIRA_COMMAND** | Modify existing ticket fields | "change priority to high" |
| **SYNC_REQUEST** | Bulk sync channel with Jira | "update Jira issues" |
| **JIRA_SEARCH** | Search Jira for existing issues | "check if we have a ticket for this" |
| **DECISION** | User stating a decision to record (Phase 30) | "we decided to use PostgreSQL" |
| **REVIEW** | Analysis/feedback without Jira ops | "help me design the API" |
| **DISCUSSION** | Greeting or simple question | "hi", "thanks" |
| **META** | Questions about the bot | "what can you do?" |
| **AMBIGUOUS** | Truly unclear intent (rare) | Shows scope gate UI |

### 2.1.1 DRAFT_TRANSFORM vs DRAFT_REFINE (Phase 28)

These intents serve different purposes:

| Aspect | DRAFT_REFINE | DRAFT_TRANSFORM |
|--------|--------------|-----------------|
| **Nature** | Asking | Commanding |
| **User says** | "Is one epic enough?" | "Split into multiple epics" |
| **Bot response** | Proposes options, asks question | Mutates draft immediately |
| **Draft change** | No structural change | Kind, scope, items change |

**DRAFT_TRANSFORM triggers:**
- "Split into..." → `split_to_plan()`
- "Merge these..." → `merge_items()`
- "Add a story for..." → `add_items()`
- "Make this an epic" → `elevate_to_epic()`
- "Break this down" → `decompose_to_stories()`
- "Only epics" → `change_scope(EPICS_ONLY)`
- "Remove the second one" → `remove_items()`

Detection uses semantic meaning, not keywords. The LLM understands "just epics for now" means `change_scope(EPICS_ONLY)`.

### 2.2 Intent Classification Prompt

```
You are classifying user intent for a Slack bot that helps with Jira tickets
and architecture discussions.

CONVERSATION CONTEXT:
{summary + last 15 messages}

CURRENT USER MESSAGE: "{message}"

Classify the user's intent into ONE category:

- SYNC_REQUEST: User wants to SYNC channel decisions with Jira (bulk update)
  Key phrases: "update Jira issues", "sync Jira", "sync tickets"

- JIRA_COMMAND: User wants to CHANGE/MODIFY an existing Jira ticket's field values
  Key verbs: change, update, set, modify, edit, delete, remove, close, mark
  Key fields: priority, status, assignee, description, summary, labels

- TICKET_ACTION: User wants to CREATE NEW items linked to an existing ticket
  Examples: "create stories for SCRUM-123", "add subtasks"

- TICKET: User wants to create a NEW Jira ticket (no existing ticket referenced)

- JIRA_SEARCH: User wants to SEARCH Jira for existing issues
  Key phrases: "check Jira", "do we have a ticket", "similar issue"

- REVIEW: User wants help, analysis, discussion, or feedback
  This is the DEFAULT for most help/discussion requests!

- DISCUSSION: Pure greeting with no actionable request

- META: Questions about the bot itself

- AMBIGUOUS: ONLY when truly unclear (should be RARE)

IMPORTANT RULES:
1. "Help me with X" or "I need help with X" = REVIEW (not AMBIGUOUS)
2. When in doubt between REVIEW and AMBIGUOUS, choose REVIEW
3. TICKET requires EXPLICIT new ticket creation language
4. For contextual references ("that ticket"), extract from CONVERSATION CONTEXT

Respond in this exact format:
INTENT: <...>
CONFIDENCE: <0.0-1.0>
PERSONA: <pm|architect|security|none>
TICKET_KEY: <SCRUM-123 or "none">
ACTION_TYPE: <create_stories|create_subtask|update|add_comment|none>
COMMAND_TYPE: <update|delete|none>
COMMAND_FIELD: <priority|status|assignee|none>
COMMAND_VALUE: <value or "none">
SEARCH_QUERY: <query or "none">
REASON: <brief explanation>
```

### 2.3 Context-Aware Classification (Phase 26)

The intent classifier now receives **active draft state** in addition to the message:

```
ACTIVE DRAFT CONTEXT:
- Title: Voice-controlled Remote Command Execution
- Issue Type: epic
- Status: Draft in progress
NOTE: If user asks questions about this draft (structure, scope, decomposition),
      classify as DRAFT_REFINE, NOT REVIEW.
```

**Key rule:** When active draft exists and user asks "Do you think X is enough?" or "Should we split this?", classify as `DRAFT_REFINE` (not REVIEW).

### 2.4 Classification Rules

1. **Default to REVIEW** - When uncertain, classify as REVIEW (not AMBIGUOUS)
2. **Draft-aware** - Meta-questions about active draft → DRAFT_REFINE
3. **Context-aware** - Extracts ticket keys from conversation history for contextual references
4. **Persona detection** - Captures PM/Architect/Security hints for review personas
5. **Metadata extraction** - Extracts command fields, search queries, action types

### 2.5 Context Relation

Each intent classification now includes a `context_relation` field:

| Relation | Meaning |
|----------|---------|
| `continue` | Message continues current flow |
| `refine` | Message refines/clarifies current draft |
| `change` | Message requests changes to existing truth |
| `new_topic` | Message is unrelated to current context |

### 2.6 Multi-Intent Detection (Phase 35)

When a message may contain multiple intents, the classifier returns a `TaskPlanProposal`:

```python
class TaskPlanProposal:
    tasks: list[TaskProposal]
    is_multi_intent: bool
    low_confidence_signal: bool
    trigger_message: str

class TaskProposal:
    intent: Intent
    super_mode: SuperMode
    confidence: float
    title: str
    params: dict
    depends_on_indices: list[int]  # References other tasks in list
```

**Detection triggers:**
1. **Explicit conjunctions:** "and", "also", "plus", "then", "as well as"
2. **Low single-intent confidence:** <0.7 suggests multiple possible intents
3. **Multiple action verbs:** "create... and check... and review..."

**Backwards compatibility:**
- `return_proposal=False` (default) returns single `IntentResult`
- `TaskPlanProposal.to_single_intent()` converts for legacy code

**Routing:**
```python
def route_after_intent(state):
    proposal = state["intent_result"].get("task_plan_proposal")
    if proposal and proposal.get("is_multi_intent"):
        return "task_decomposer"  # Multi-intent flow
    return existing_routing(state)  # Single-intent flow
```

---

## 3. Governance Rules

### 3.1 Core Model (Phase 23 - Current)

#### Channel = Source of Truth
> Channel owns a registry of WorkItems, not just Epics

The model shifted from "thread binds to Epic" to "Channel owns WorkItems":

- **Channel** contains a registry of WorkItems (0..N): Epics, Stories, Bugs, Tasks, Spikes
- **Thread** is a working branch where exploration/drafting happens
- **Jira** is a projection/replica of channel truth (not the source)

| Entity | Role |
|--------|------|
| Channel | Source of truth, owns WorkItem registry |
| Thread | Working session, drafts committed to channel |
| Jira | Execution replica, receives "deployments" |

#### Rule 1: WorkItem Registry (replaces Epic binding)
> Contribution binds to WorkItem (any type), not just Epic

- WorkItem types: Epic, Story, Bug, Task, Spike
- Each has: local_id, jira_key (nullable), status (draft/active/done), summary, facts
- **Drafts are first-class citizens** - live in registry, sync to Jira only on explicit action
- No orphan contributions - everything lands in a WorkItem or Untriaged Inbox
- Status: **IMPLEMENTED** (WorkItemStore)

#### Rule 2: Traffic Cop / Dedup
> Suggest similar threads without blocking workflow

- Only triggers on extremely high similarity (0.85+ threshold)
- Non-blocking suggestions: "Related thread exists; want me to link it?"
- Logs similarity score and rationale
- Status: **NON-BLOCKING**

#### Rule 3: Explicit Approval (Commit Semantics)
> Nothing becomes channel truth without explicit approval

- MARO detects "significant events" (decision approved, ticket created)
- Shows commit preview with summary
- User clicks "Approve & Commit"
- Entry added to Channel Work Board log
- **No silent auto-commits**
- Status: **ENFORCED**

#### Rule 4: Aggregation
> Write to Epic description in batches with full changelog

- Batch writes (per N decisions or manual command)
- Every write includes changelog entry + source thread links
- Status: **BATCH WRITES**

### 3.2 Duplicate Handling Rules (Phase 23)

#### Rule 6: Blocking Duplicate Detection
> Block ticket creation on EXACT_MATCH duplicates until user explicitly chooses

| Match State | Confidence | Behavior |
|-------------|------------|----------|
| EXACT_MATCH | >85% | **Blocks creation** until user chooses |
| LIKELY_DUPLICATE | 60-85% | Shows warning, allows creation |
| NO_MATCH | <60% | Proceeds normally |

**Confidence Scoring:**
```python
score = 0.0
# Title word overlap (up to 0.5)
# Problem description overlap (up to 0.3)
# Active ticket boost (up to 0.2)
```

#### Rule 7: Explicit Choice Buttons
> Force explicit user decision with 3 choices

For EXACT_MATCH:
- **Link to existing** (Primary, Recommended)
- **Update existing with new info**
- **Create new anyway** (Danger, requires confirmation)

For LIKELY_DUPLICATE:
- Same buttons, equal weight (no recommendation)

### 3.3 Registry Rules

#### Rule 8: Channel Jira Registry
> Channel explicitly owns list of Jira issues (central to new model)

This is the **key implementation** of the "Channel = Source of Truth" model:

| Link Type | Description |
|-----------|-------------|
| `owned` | Created from this channel (primary owner) |
| `tracked` | Explicitly tracked via `/maro track` command |
| `mentioned` | Referenced in discussions (passive) |

**Key Properties:**
- Central, queryable registry per channel
- Not scattered across multiple stores
- Includes both synced (has jira_key) and draft (no jira_key) items
- Supports WorkItems of any type: Epic, Story, Bug, Task, Spike

### 3.4 Context Rules

#### Rule 15: Complete Channel Snapshot
> Include ALL active work items in context, not just last 10

Enhanced snapshot includes:
- All active epics with child counts
- Work items grouped by status
- Item counts by type (epic: 5, story: 12, bug: 3)
- Up to 50 recent tickets (increased from 10)

### 3.5 Commit Semantics

#### What is a Commit?

A **commit** is an approved decision that becomes channel truth. Commits are:
- Immutable once created
- Linked to source thread
- Optionally synced to Jira

#### Commit Triggers

| Event | Creates Commit? |
|-------|-----------------|
| Draft approved | Yes |
| WorkItem created | Yes |
| Decision approved | Yes |
| Review approved | Yes (as artifact) |
| Jira field updated | Yes (change record) |
| Discussion message | No |

#### Commit Structure

```python
class Commit:
    commit_id: str
    channel_id: str
    source_thread_ts: str
    commit_type: Literal["workitem", "decision", "artifact", "change"]
    summary: str
    details: dict
    created_at: datetime
    created_by: str
    jira_synced: bool
    jira_key: Optional[str]
```

#### Commit Log

Each channel maintains a commit log (append-only):

```
[2026-01-22 10:30] WORKITEM: Created "Rate limiting API" (draft)
[2026-01-22 10:45] DECISION: Approved rate limiting approach
[2026-01-22 11:00] WORKITEM: Published to Jira as SCRUM-456
[2026-01-22 14:00] CHANGE: Updated priority High → Critical
```

#### Relation to Jira Sync

- Commits exist independently of Jira
- `jira_synced=false` means local-only truth
- Sync is explicit: "Publish to Jira" or `/maro sync`
- Jira updates flow back as CHANGE commits

### 3.6 Commit Log vs State (Phase 31)

**Core distinction:** Canonical messages and commit logs serve different purposes.

| Concept | Nature | Mutability | Purpose |
|---------|--------|------------|---------|
| **Canonical Message** | Current state (HEAD) | Mutable (updated in place) | What IS true now |
| **Commit Log** | Historical record | Append-only (never edited) | What BECAME true |

**Rules:**
1. **Commit log entries are immutable after creation** — Once a commit is recorded, it cannot be modified or deleted
2. **Canonical messages are updated to reflect current version** — The pinned message always shows the latest state
3. **Never merge these concepts in code or docs** — They serve different purposes and have different lifecycles

**Example flow:**
```
Decision approved
    ↓
Commit log entry created (immutable historical record)
    ↓
Canonical message updated (mutable current state)
```

**Key insight:** The commit log is like git history — it records what happened. The canonical message is like the working tree — it shows what is true now. Never confuse these: you read the canonical message to know current state, you read the commit log to know history.

### 3.7 Sync Semantics (Phase 31)

**Core distinction:** Preflight and `/maro sync` serve different purposes.

| Operation | Blocking? | Purpose |
|-----------|-----------|---------|
| **Preflight** | Yes | Guard before any Jira write |
| **/maro sync** | No | Informational reconciliation |

**Preflight (Blocking Guard):**
- Called before create/update operations
- Fetches current Jira state
- Classifies conflicts (IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL)
- Preflight result determines if operation proceeds
- IDEMPOTENT auto-succeeds, all others require user choice

**`/maro sync` (Informational Diagnostic):**
- Reports drift between local state and Jira
- Does NOT block any operation
- Used for visibility and manual reconciliation
- Shows which tickets have diverged and how

**Both use the same conflict classification:**

| Type | Meaning |
|------|---------|
| IDEMPOTENT | Already done in Jira |
| SAFE_DRIFT | Changes don't overlap |
| REAL_CONFLICT | Same fields changed |
| STRUCTURAL | Invalid operation |

**Key rule:** "Preflight = write guard. Sync = read-only diagnostic."

Preflight is mandatory before writes. Sync is optional for visibility.

---

## 4. LLM Prompts Reference

### 4.1 System Identity

```
You are a requirements orchestrator. Your role is to:
1. Capture decisions from conversations
2. Build complete, unambiguous work items
3. Maintain channel truth (the registry of work items)
4. Sync truth to external systems (Jira) on explicit request

Core principle: Chat is the source of truth. Jira is where truth gets deployed.

You work with these work item types:
- Epic: High-level features (needs: summary, description)
- Story: User-facing features (needs: summary, description, acceptance_criteria)
- Task: Technical work (needs: summary, description)
- Bug: Defects (needs: summary, description, steps_to_reproduce, expected/actual behavior)
- Spike: Research/exploration (needs: summary, question to answer)

Be conversational, not robotic. Ask one question at a time when possible.
Never create half-baked items. Never auto-sync without explicit approval.
```

### 4.2 Extraction Prompt

```
You are extracting requirements from a conversation to build a Jira ticket draft.

Current draft state:
{draft_json}

{conversation_context}

New message to process:
{message}

Extract any new information that should update the draft. Return a JSON object
with ONLY the fields that have new information. Do not repeat existing values.

Fields you can update:
- title: Clear, concise ticket title
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria
- constraints: List of {"key", "value"} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks
- issue_type: Type of work item (epic, story, task, bug)
  Only set if user explicitly mentions: "create an epic", "make a story", "this is a bug"
- requested_scope: What to generate (epics_only, full_plan, single_item)
  - epics_only: User says "only epic(s)", "just epics", "epic-level only"
  - full_plan: User says "full breakdown", "complete plan", "with stories"
  - single_item: Default for normal requests

IMPORTANT: Do NOT put "Epic:" or "Story:" prefixes in the title. Use issue_type field instead.

Return empty object {} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message. Do not invent or assume.
```

### 4.3 Validation Prompt

```
You are a Jira ticket validator. Review this draft for completeness and conflicts.

Current draft:
{draft_json}

Channel context:
{channel_context}

Validate the draft and return:
1. is_valid: boolean - Does it meet MINIMUM requirements?
2. missing_fields: list - What's still needed?
3. conflicts: list - Any logical contradictions?
4. suggestions: list - Optional improvements
5. quality_score: 0-100

MINIMUM REQUIREMENTS (must ALL be present for is_valid=true):
- title: Clear, concise (not empty)
- problem: Describes what needs solving (not empty)
- acceptance_criteria: At least 1 testable criterion

DO NOT require:
- proposed_solution (optional - user may want team to decide)
- constraints/dependencies/risks (optional extras)

Return JSON matching the ValidationReport schema.
```

### 4.4 Review Prompt (Persona-Based)

```
You are an experienced {persona} reviewing a software architecture or design proposal.

Topic: {topic}
User's question/request: {message}

Provide a thoughtful analysis covering:

1. **Understanding** - Confirm what you understand about the proposal
2. **Components & Flows** - Key elements and how they interact
3. **Risks** - Technical, operational, or business concerns
4. **Alternatives** - Other approaches worth considering
5. **Open Questions** - What needs clarification?

Keep your response focused and actionable. Use bullet points.

FORMATTING RULES (for Slack):
- Use *single asterisks* for bold (not **double**)
- Use - for bullet points
- Keep sections short (2-4 bullets each)
```

### 4.5 Question Generation

```
Generate 1-2 clarifying questions to gather the missing information.

Questions should be:
- Specific and actionable
- Prioritized by importance
- Natural and conversational

Focus on: {missing_fields}
```

### 4.6 Answer Matching

```
Match the user's response to the numbered questions that were asked.

Questions asked:
{questions_with_numbers}

User's response:
{response}

For each question, determine:
- Did the user answer it? (yes/partial/no)
- What was their answer?
- Confidence (0.0-1.0)

Special signals:
- "you decide" / "propose something" = [GENERATE] delegation
- "not sure" / "don't know" = [SKIP] acknowledgment
```

### 4.7 Discussion Response

```
You are a helpful Slack bot. The user has sent a casual message or greeting.

Message: {message}

Respond briefly (1-2 sentences max). Be friendly and helpful.
If they seem to want something specific, ask what you can help with.
```

### 4.8 Story Generation

```
You are breaking down a Jira Epic into User Stories.

Epic:
{epic_summary}
{epic_description}

Create {count} independent user stories. Each story should:
- Follow "As a [user], I want [goal], so that [benefit]" format
- Be independently deliverable
- Have clear acceptance criteria

Return as JSON array:
[
  {"summary": "...", "description": "...", "acceptance_criteria": ["...", "..."]}
]
```

### 4.9 Duplicate Explanation

```
Explain in 1 sentence (max 80 chars) why this draft matches the existing ticket.

Draft title: {draft_title}
Draft problem: {draft_problem}

Existing ticket:
Key: {existing_key}
Summary: {existing_summary}
Status: {existing_status}

Focus on: What makes them similar? Be specific and concise.
```

---

## 5. State Machine & Workflows

### 5.1 Main Graph Structure (LangGraph)

```
START
  → intent_router (LLM classification)
  → [conditional routing]
    ├─ workitem_flow
    │    → extraction (update draft from message)
    │    → [should_continue?]
    │    │   ├─ extraction (loop for more info)
    │    │   ├─ validation (have enough data)
    │    │   └─ end (max steps or intro action)
    │    → validation (check completeness)
    │    → decision (route to ask/preview/preflight)
    │    → END
    │
    ├─ draft_refine_flow (Phase 26)
    │    → decision (checks DRAFT_REFINE intent)
    │    → returns refinement_prompt with options
    │    → END
    │
    ├─ draft_transform_flow (Phase 28)
    │    → draft_transform (mutate draft structure)
    │    → returns action="transform_applied"
    │    → dispatch shows updated structure
    │    → END
    │
    ├─ review_flow
    │    → review (persona-based analysis)
    │    → END
    │
    ├─ discussion_flow
    │    → discussion (brief response)
    │    → END
    │
    ├─ scope_gate_flow
    │    → scope_gate (show 3-button UI)
    │    → END
    │
    ├─ ticket_action_flow
    │    → ticket_action (create stories/subtasks)
    │    → END
    │
    ├─ jira_command_flow
    │    → jira_command (modify fields)
    │    → END
    │
    ├─ jira_search_flow
    │    → jira_search (search existing)
    │    → END
    │
    ├─ sync_flow
    │    → sync_trigger (bulk sync)
    │    → END
    │
    ├─ decision_flow (Phase 30)
    │    → decision_extraction (extract from message)
    │    → create Decision entity (PROPOSED status)
    │    → show_decision_proposal card
    │    → END (user approves/edits via buttons)
    │
    └─ multi_intent_flow (Phase 35)
         → task_decomposer (convert proposal → TaskPlan)
         → task_executor (recursive)
         │   ├─ AUTO_EXECUTE → run immediately
         │   └─ REQUIRES_CONFIRMATION → block, show buttons
         → END (plan complete or blocked)
```

### 5.2 Decision Flow Detail (Phase 30)

```
User: "We decided to use PostgreSQL"
    ↓
intent_router → DECISION intent detected
    ↓
decision_extraction_node
    ↓
    ├─ Extract decision type (ARCH from keywords)
    ├─ Extract title ("Use PostgreSQL")
    ├─ Create Decision entity (PROPOSED status)
    └─ Return action="show_decision_proposal"
    ↓
dispatch → show compact draft card
    ├─ [Edit] → open modal
    ├─ [Approve] → approve + sync to Jira
    └─ [Discard] → deprecate
```

**Button handlers:**
- `decision_approve`: Mark APPROVED → sync to all linked Jira tickets via preflight
- `decision_edit`: Open modal to modify title/description
- `decision_change`: Create new version (for approved decisions)
- `decision_deprecate`: Mark DEPRECATED with reason

**Canonical message lifecycle:**
```
PROPOSED: Compact card with [Edit][Approve][Discard]
    ↓ (approve)
APPROVED: Authoritative card with [Change][Deprecate][History]
    ↓ (deprecate)
DEPRECATED: Historical marker with pointer to replacement
```

### 5.3 WorkItem Flow Detail

```
extraction
    ↓
should_continue? ──→ Loop back to extraction if:
    │                 - Just intro/nudge (no real content yet)
    │                 - Pending questions answered
    │                 - More context needed
    │
    ↓ (have enough data)
validation
    ↓
decision ──→ Routes to:
    │         - ASK (need more questions)
    │         - PREVIEW (draft ready for approval)
    │         - PREFLIGHT (exact duplicate found)
    │         - READY (approved, create in Jira)
    ↓
END (Slack handler sends response)
```

### 5.3 Workflow Steps (Button Validation)

Each workflow step has allowed actions:

| Step | Allowed Actions |
|------|-----------------|
| DRAFT_PREVIEW | approve, reject, edit, duplicate_use, duplicate_new |
| MULTI_TICKET_PREVIEW | approve, edit_story, cancel, confirm_quantity |
| DECISION_PREVIEW | approve, edit, cancel |
| REVIEW_ACTIVE | show_full, approve_decision, turn_into_ticket |
| REVIEW_FROZEN | *No actions allowed* |
| SCOPE_GATE | select_review, select_ticket, dismiss, remember |
| UPDATE_PREVIEW | update_preview_apply, update_preview_edit, update_preview_cancel |

---

## 6. Decision Logic

### 6.1 Decision Node Flow

```python
def decision_node(state):
    # 0. Check for DRAFT_REFINE intent (Phase 26)
    if intent == "DRAFT_REFINE" and draft.title:
        # User asking meta-questions about draft structure
        return DRAFT_REFINE (with refinement_prompt)

    # 1. Check thread binding first
    if thread_bound_to_ticket:
        skip_duplicate_detection()

    # 2. Check re-ask logic
    if unanswered_questions and reask_count < MAX_REASK_COUNT:
        return ASK (re-ask unanswered questions)

    # 3. If max re-asks reached
    if reask_count >= MAX_REASK_COUNT:
        proceed_with_partial_info()  # → PREVIEW

    # 4. Validate draft
    if conflicts_exist:
        return ASK (resolve conflicts first)

    if missing_required_fields:
        return ASK (batch questions, max 3)

    # 5. Draft is valid - check duplicates
    duplicates, confidence = search_for_duplicates(draft)
    preflight = PreflightResult.from_search_results(duplicates, confidence)

    if preflight.should_block_creation():  # >85% confidence
        return PREFLIGHT_REQUIRED (block until user chooses)

    if preflight.should_warn():  # 60-85% confidence
        return PREVIEW (with duplicate warning)

    return PREVIEW (normal, no duplicates)
```

### 6.2 Extraction Continuation Logic

```python
def should_continue(state):
    action = state.get("extraction_action")
    step_count = state.get("step_count", 0)

    # Stop conditions
    if step_count >= MAX_STEPS:
        return "validation"

    if action in ("intro", "nudge", "hint"):
        return "end"  # Don't loop on contextual hints

    # Continue conditions
    if action == "extract":
        return "validation"  # Have content, validate it

    if action == "generate":
        return "validation"  # Generated content, validate it

    return "extraction"  # Loop for more info
```

### 6.3 Question Batching

Questions are batched and prioritized:

```python
def batch_questions(questions):
    # Priority order:
    # 1. Conflicts (highest priority)
    # 2. Missing required fields (title, problem, acceptance_criteria)
    # 3. Optional improvements (suggestions)

    # Batch size: max 3 questions per ask
    return questions[:3]
```

### 6.4 User Input Classification (Phase 28)

Every user message is classified to determine routing:

| InputClass | Description | Bot Action |
|------------|-------------|------------|
| **CHOICE** | Structural decision | Mutate draft immediately |
| **OPINION** | Preference expression | Continue discussion |
| **QUESTION** | User asking something | Answer the question |
| **ANSWER** | Response to bot's question | Apply to draft, continue |
| **UNCLEAR** | Cannot determine | Default to normal flow |

**Key rule:** If user input represents a decision, bot must act, not discuss.

```python
# User: "Split into multiple epics"
# → InputClass.CHOICE → draft.split_to_plan() → show structure

# User: "I think we could split it"
# → InputClass.OPINION → continue discussion, maybe ask "Would you like me to split it?"

# User: "Should we split this?"
# → InputClass.QUESTION → answer with options, don't mutate yet
```

**Classification signals:**
- CHOICE: Imperative commands ("split", "merge", "only epics", "add a story")
- OPINION: Hedging language ("I think", "maybe", "could", "might")
- QUESTION: Interrogatives ("should we?", "do you think?", "is it?")
- ANSWER: Follows pending_questions context

### 6.5 Form-Dependent Validation (Phase 28)

Validation rules depend on the draft's **form** (issue type and lifecycle):

| Issue Type | Required Fields | Optional Fields |
|------------|-----------------|-----------------|
| **EPIC** | title, problem | acceptance_criteria |
| **STORY** | title, problem, acceptance_criteria | - |
| **TASK** | title, problem | acceptance_criteria |
| **BUG** | title, problem | acceptance_criteria |

**Key insight:** Epics don't require acceptance criteria. Stories do.

```python
def validate_structured_draft(draft):
    for item in draft.items:
        rules = _get_validation_rules_for_type(item.issue_type)

        if item.issue_type == IssueType.EPIC:
            # Validate goal/scope, NOT AC
            check_required(["title", "problem"])
        elif item.issue_type == IssueType.STORY:
            # Validate including AC
            check_required(["title", "problem", "acceptance_criteria"])

    # Plan drafts require 2+ items
    if draft.kind == DraftKind.PLAN and len(draft.items) < 2:
        return Invalid("Plan needs at least 2 items")
```

### 6.6 Lifecycle-Aware Questions (Phase 28)

The bot asks **different questions** based on draft lifecycle:

| Lifecycle | Questions to Ask | Questions to Skip |
|-----------|------------------|-------------------|
| **EMPTY** | "What would you like to create?" | Everything else |
| **SINGLE_ITEM** (Epic) | Goal, scope, decomposition options | Acceptance criteria |
| **PLAN** | Item structure, decomposition | Acceptance criteria |
| **PLAN_REFINED** | Item details, missing fields | - |
| **APPROVED** | None (ready for commit) | All |

**Key rule:** Cannot ask for acceptance criteria while Draft is in PLAN stage.

```python
def _filter_questions_by_lifecycle(questions, lifecycle, issue_type):
    # PLAN stage: Don't ask AC, ask about decomposition
    if lifecycle == DraftLifecycle.PLAN:
        questions = [q for q in questions if "acceptance" not in q.lower()]
        questions.append("How should we break this down?")

    # EPIC type: Never ask AC
    if issue_type == IssueType.EPIC:
        questions = [q for q in questions if "acceptance" not in q.lower()]

    return questions
```

**Example conversation:**
```
User: "Create an auth system"
Bot: "What's the main goal?" (not "What are the acceptance criteria?")

User: "Secure login for users"
Bot: "Should this be one epic or multiple?" (lifecycle-appropriate)

User: "Split into multiple epics"
Bot: [mutates draft, shows structure]
Bot: "What items should this plan include?" (not AC questions)
```

### 6.7 No Question Repetition (Phase 28)

Once a question is answered, it's recorded and never asked again:

```python
class AnsweredQuestionsStore:
    async def record_answer(channel_id, thread_ts, question_key, answer, user_id)
    async def was_answered(channel_id, thread_ts, question_key) -> bool
    async def filter_unanswered(channel_id, thread_ts, questions) -> list[str]
```

**Question keys** normalize questions to fields:
- "What are the acceptance criteria?" → `acceptance_criteria`
- "What problem are we solving?" → `problem`
- "Would you like epics or full plan?" → `scope_decision`

**Confidence threshold:** 0.7 minimum to record as definitive answer.

```python
# Before asking questions:
questions = await store.filter_unanswered(channel_id, thread_ts, missing_fields)
# Only ask questions not yet answered
```

**Hard rule:** Repeating the same question after a direct answer is a system error.

---

## 7. Response Generation

### 7.1 Dispatch Actions

| Action | Handler | Response Type |
|--------|---------|---------------|
| `ask` | `SkillDispatcher.ask_user` | Questions in modal/blocks |
| `preview` | `SkillDispatcher.show_draft` | Draft blocks + approve/reject |
| `preflight` | `build_preflight_blocks` | Duplicate UI + 3 choice buttons |
| `draft_refine` | `_build_refinement_prompt` | Options for draft decomposition |
| `ready` | Simple message | "Ticket approved and ready" |
| `review` | Chunked blocks | Analysis + approve/edit buttons |
| `discussion` | Simple message | Brief conversational response |
| `scope_gate` | Blocks | 3-button choice UI |
| `jira_command` | Command confirmation | Preview + confirm button |

### 7.2 Slack Block Chunking

Long responses are chunked for Slack's 2900 char limit:

```python
def chunk_response(text, max_chars=2900):
    # Priority: paragraph breaks > line breaks > word breaks
    chunks = []
    # Action buttons only on last chunk
    return chunks
```

### 7.3 Preflight UI (EXACT_MATCH)

```
┌─────────────────────────────────────────────────┐
│ ⚠️ *EXACT MATCH FOUND* (92% confident)          │
│ This appears to be an existing task.            │
├─────────────────────────────────────────────────┤
│ *SCRUM-123*: Similar title                      │
│ Status: *In Progress* | Assignee: @user         │
├─────────────────────────────────────────────────┤
│ 💡 *Match reason:* Both address auth flow       │
├─────────────────────────────────────────────────┤
│ *What would you like to do?*                    │
│                                                 │
│ [Link to SCRUM-123 (Recommended)]  [primary]    │
│ [Update SCRUM-123 with new info]               │
│ [Create new anyway ⚠️]             [danger]     │
└─────────────────────────────────────────────────┘
```

---

## 8. Key Behavior Patterns

### 8.1 Context Injection

Context is injected at multiple points:
- **Intent classification** - Last 15 messages + summary
- **Extraction** - Channel context (epics, conventions, rules)
- **Validation** - Channel constraints and naming conventions
- **Review** - Prior discussion and review artifacts

### 8.2 Conversation-Aware Extraction

```python
# Answer matching
if pending_questions:
    matches = await match_answers(user_response, pending_questions)
    # Correlates responses to numbered questions
    # Detects [GENERATE] delegation signals
    # Detects [SKIP] acknowledgments

# Reference detection
if references_prior_content(message, ["the architecture", "this review"]):
    use_extraction_with_reference_prompt()
```

### 8.3 Human-in-the-Loop Interrupts

Graph interrupts at key points for human decision:
- **ASK** - Need more information
- **PREVIEW** - Draft ready for approval
- **PREFLIGHT** - Duplicate found, need choice
- **SCOPE_GATE** - Ambiguous intent, need clarification

State is persisted via checkpointer for resume.

### 8.4 Idempotency & Stale UI

```python
# Event deduplication
if event_id in processed_events:
    reject_duplicate()

# Workflow step validation
if button_action not in allowed_actions[current_step]:
    show_stale_ui_error()

# Version checking
if action_version != state_version:
    show_outdated_error()
```

### 8.5 Persona-Based Responses

Review intents route to personas with different perspectives:

| Persona | Focus Areas |
|---------|-------------|
| **PM** | Requirements, user value, scope |
| **Architect** | System design, scalability, patterns |
| **Security** | Vulnerabilities, auth, data protection |

Persona is detected from message content or explicitly specified.

### 8.6 Smart Duplicate Detection

```python
def compute_confidence(draft, duplicate):
    score = 0.0

    # Title word overlap (up to 0.5)
    overlap = title_words & dup_words
    score += (overlap / max_words) * 0.5

    # Problem description overlap (up to 0.3)
    if problem_overlaps:
        score += 0.3

    # Active ticket boost (up to 0.2)
    if status in ("To Do", "In Progress"):
        score += 0.2
    elif status in ("Done", "Closed"):
        score += 0.05  # Lower for closed tickets

    return min(score, 1.0)
```

---

## Summary

MARO's intelligence is built on:

### Core Principles
1. **WorkItem-centric model** — Channel is truth, Jira is deployment
2. **Decision-centric model** — Decisions are versioned, Jira is a projection (Phase 30)
3. **Git-like semantics** — Threads propose, channels commit, Jira syncs

### Draft Model (Phase 28)
4. **StructuredDraft as design object** — Draft is a typed data structure, not text
5. **Lifecycle state machine** — EMPTY → SINGLE_ITEM → PLAN → APPROVED → COMMITTED
6. **User input classification** — CHOICE/OPINION/QUESTION/ANSWER routing
7. **Form-dependent validation** — Epic validates goal/scope, Story validates AC
8. **Lifecycle-aware questions** — PLAN stage asks decomposition, not AC
9. **DRAFT_TRANSFORM intent** — Structural mutations triggered by semantic commands
10. **Structure visualization** — Show draft structure after every mutation
11. **No question repetition** — Answered questions never re-asked

### Preflight Model (Phase 29)
12. **Preflight as universal guardrail** — Every Jira write goes through conflict check
13. **4-type conflict classification** — IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL
14. **Never auto-fix** — Human choice required for any conflict resolution
15. **Sync tracking** — jira_updated vs last_synced for drift detection

### Decision Model (Phase 30)
16. **Decision as first-class entity** — Versioned with lifecycle (PROPOSED → APPROVED → DEPRECATED)
17. **Canonical message pattern** — One message per decision, updated in place
18. **Managed sections** — MARO writes only to its block, preserves user content
19. **Deterministic mapping** — Decision type → known Jira field, no LLM guessing
20. **Decision approval = commit + sync** — Approval triggers immediate Jira projection

### Architecture Hardening (Phase 31)
21. **Super-modes for simplicity** — Users see 5 modes (BUILD, OPERATE, DECIDE, THINK, CHAT), not 13 intents

### Product Invariants (Phase 32)
22. **5 invariants as physics** — SuperMode, Slack=UI, Commit Log, Managed Section, Draft States
23. **4-layer protection** — Types, Boundaries, CI Gates, Runtime
24. **Escape hatch protocol** — Override with role + reason + TTL + audit
25. **Handler read-only invariant** — Mutations dispatch through graph

### Multi-Intent Task Orchestration (Phase 35)
26. **TaskPlan replaces single intent** — Parse full universe of user intent
27. **Two-stage classification** — Single-intent first, multi-intent if signals detected
28. **Safety-based auto-execution** — THINK/CHAT auto-execute, BUILD/OPERATE/DECIDE require approval
29. **Dependency-aware execution** — Tasks run only when dependencies satisfied
30. **Version-bound buttons** — Stale actions rejected with version mismatch
31. **Cascade cancel** — Rejecting a task cancels all dependents
32. **Status card with throttling** — Single editable message, 1.5s minimum between updates

### Question Engine (Phase 36)
33. **Questions as first-class tasks** — QuestionTask extends Task with status tracking
34. **Active/Passive mode** — State machine determines when bot leads vs listens
35. **Question budget** — Max 2 unanswered before partial preview
36. **Hybrid question generation** — Templates for scope, LLM for field collection
37. **Hybrid answer processing** — Buttons deterministic, text LLM-parsed
38. **Mode transitions** — @mention/command → ACTIVE, complete/timeout → PASSIVE

### Supporting Systems
39. **Context-aware intent classification** — Message + draft state → intent (Phase 26)
27. **Version-bound approvals** — Stale buttons detected and rejected
28. **Draft continuity** — DRAFT_REFINE catches meta-questions before switching to review
29. **Rule-based governance** ensuring consistent behavior
30. **Graph-based workflows** with conditional routing
31. **Smart duplicate detection** — channel-first, then Jira
32. **Human-in-the-loop** interrupts for critical decisions
33. **Persona-based analysis** for different perspectives

**Mantras:**
- "Threads propose. Channels decide. Jira executes."
- "Decisions are versioned, Jira is a projection." (Phase 30)
- "Draft is a data structure representing the shape of work, not a paragraph of text." (Phase 28)
- "If user input represents a decision, bot must act, not discuss." (Phase 28)
- "Every write goes through preflight — no exceptions." (Phase 29)
- "Invariants are physics, not rules." (Phase 32)
- "Safe tasks execute. Dangerous tasks wait." (Phase 35)
- "Questions are tasks. Mode drives behavior. Budget prevents spam." (Phase 36)

The system is designed to be **conversational**, **non-blocking**, and **transparent** — always explaining its reasoning and giving users explicit choices.

---

*Last updated: 2026-01-24 (Phase 36 Question Engine — Conversation Driver)*

# MARO Architecture Documentation

**Multi-Agent Requirements Orchestrator (MARO) v2**

> **Note:** This document describes the original v2 architecture. Some components have changed:
> - **Zep** replaced with PostgreSQL for all persistence
> - **MCP** replaced with direct atlassian-python-api
> - **11-phase workflow** replaced with intent-based routing
>
> See `HOW_THE_BOT_THINKS.md` for the current behavior and sections below for latest architecture:
> - **Phase 28: StructuredDraft Evolution** - Draft as typed design object
> - **Phase 29: Preflight** - Universal guardrail for Jira writes
> - **Phase 30: Decision as Entity** - Decisions are versioned, Jira is projection
> - **Phase 31: Architecture Hardening** - Super-modes, MANAGED_SECTION_ONLY invariant
> - **Phase 32: Product Invariants** - 5 invariants enforced as architecture
> - **Phase 35: Multi-Intent Task Orchestration** - Parse full universe of user intent
> - **Phase 36: Question Engine — Conversation Driver** - Questions as first-class tasks with active/passive mode
> - **Phase 39: Intent Classification v2** - 2-stage architecture with IntentEnvelope, pre-gates, and terminal intents

A sophisticated AI-powered system that transforms natural language conversations into structured, validated Jira issues through an intent-based LangGraph workflow with human-in-the-loop approval.

---

## Phase 28: StructuredDraft Evolution (Latest)

**Core shift:** From "bot collects text for a ticket" to "bot manages a typed design object with lifecycle states and structural mutations."

### StructuredDraft Schema

```python
class StructuredDraft(BaseModel):
    id: str
    kind: DraftKind           # SINGLE_ITEM vs PLAN
    scope: DraftScope         # SINGLE, EPICS_ONLY, FULL_PLAN
    lifecycle: DraftLifecycle # EMPTY → SINGLE_ITEM → PLAN → APPROVED → COMMITTED
    version: int              # Incremented on every mutation
    items: list[DraftItem]    # Multiple items with hierarchy
    change_log: list[DraftChange]  # Audit trail of all changes

class DraftItem(BaseModel):
    id: str
    issue_type: IssueType     # EPIC, STORY, TASK, BUG
    title: str
    goal: str
    status: DraftItemStatus   # PROPOSED → APPROVED → COMMITTED
    parent_id: Optional[str]  # For stories under epics
    acceptance_criteria: list[str]
    jira_key: Optional[str]   # Set after Jira creation
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **DraftKind** | SINGLE_ITEM (one ticket) vs PLAN (multiple items) |
| **DraftScope** | SINGLE, EPICS_ONLY, FULL_PLAN |
| **DraftLifecycle** | State machine: EMPTY → SINGLE_ITEM → PLAN → APPROVED → COMMITTED |
| **DRAFT_TRANSFORM** | Intent for structural mutations (split, merge, elevate, decompose) |
| **InputClass** | CHOICE/OPINION/QUESTION/ANSWER classification for routing |

### Structural Mutations

| Operation | Method | Effect |
|-----------|--------|--------|
| Split to plan | `split_to_plan()` | SINGLE_ITEM → PLAN |
| Add items | `add_items()` | Append new DraftItems |
| Merge items | `merge_items()` | Combine multiple items |
| Elevate to epic | `elevate_to_epic()` | Change item type to EPIC |
| Decompose | `decompose_to_stories()` | Create stories under epic |
| Change scope | `change_scope()` | Modify generation intent |
| Remove items | `remove_items()` | Delete items (cascading) |

### Form-Dependent Validation

| Issue Type | Required | Optional |
|------------|----------|----------|
| EPIC | title, problem | acceptance_criteria |
| STORY | title, problem, acceptance_criteria | - |
| TASK | title, problem | acceptance_criteria |

### Lifecycle-Aware Questions

- **PLAN stage**: Ask about decomposition, NOT acceptance criteria
- **EPIC type**: Never ask about acceptance criteria
- **STORY type**: Ask about acceptance criteria

### Version-Bound Approvals

Button payloads include `{draft_id, version}`. When clicked:
- `button.version == draft.version` → Proceed
- `button.version != draft.version` → "Outdated, please review new structure"

---

## Phase 29: Preflight - Universal Guardrail (Latest)

**Core principle:** Every write operation goes through preflight — no exceptions.

### Conflict Classification

| Type | Meaning | Action |
|------|---------|--------|
| **IDEMPOTENT** | Already done in Jira | Auto-succeed, sync local |
| **SAFE_DRIFT** | Changes don't overlap | Ask but default to proceed |
| **REAL_CONFLICT** | Same fields changed | Block until user chooses |
| **STRUCTURAL** | Invalid operation | Block with explanation |

### Sync Tracking

```python
class JiraRegistryEntry:
    jira_key: str
    jira_updated: datetime  # When Jira was last modified
    last_synced: datetime   # When we last fetched
    status: str
    assignee: str
```

### Key Rules

- **IDEMPOTENT auto-succeeds** — all others require human choice
- **Never auto-fix conflicts** — user must explicitly choose resolution
- **Sync on read** — every preflight updates local registry

---

## Phase 30: Decision as First-Class Entity (Latest)

**Mantra:** "Decisions are versioned, Jira is a projection."

### Decision Entity

```python
class Decision:
    id: str
    channel_id: str
    decision_type: DecisionType  # ARCH, SCOPE, CONSTRAINT, PRIORITY, STRUCTURE, PROCESS
    title: str
    description: str
    status: DecisionStatus       # PROPOSED → APPROVED → DEPRECATED/REPLACED
    version: int
    canonical_message_ts: str    # Slack message that represents this
```

### Decision Types → Jira Projection

| Type | Jira Field |
|------|------------|
| ARCH | Description → Architecture section |
| SCOPE | Description → Scope section |
| CONSTRAINT | Description → Constraints section |
| PRIORITY | Priority field / Labels |
| STRUCTURE | Parent/Link relations |
| PROCESS | Labels / Custom field |

### Canonical Message Pattern

Each Decision has **one message** in channel:
- Always reflects current version (like HEAD in git)
- Never deleted, only updated or marked deprecated
- Thread = working area for discussion

### Managed Sections

MARO writes only to clearly marked sections:

```markdown
## Decisions (managed by MARO)
• DEC-41 v4 – Use ISO 8601 dates
---
```

User content outside this block is never touched.

### DecisionLink

```python
class DecisionLink:
    decision_id: str
    jira_key: str
    field_path: JiraFieldPath
    synced_version: int
    synced_at: datetime
```

Enables:
- Deterministic mapping (no LLM guessing)
- Incremental sync (only if version changed)
- Audit trail (which version is in Jira)

---

## Phase 31: Architecture Hardening (Latest)

**Mantra:** "Feel like a product, not an OS kernel."

Phase 31 hardens the architecture for production without adding features.

### Super-Modes: User-Facing Simplicity

13 intents exist for routing, but users see 5 modes:

| Super-Mode | User Perception | Internal Intents |
|------------|-----------------|------------------|
| **BUILD** | "I'm building something" | WORKITEM_CREATE, DRAFT_REFINE, DRAFT_TRANSFORM |
| **OPERATE** | "I'm managing Jira" | JIRA_COMMAND, CHANGE_REQUEST, SYNC_REQUEST, TICKET_ACTION |
| **DECIDE** | "I'm recording a decision" | DECISION |
| **THINK** | "Help me think" | REVIEW, JIRA_SEARCH |
| **CHAT** | "Just talking" | DISCUSSION, META, AMBIGUOUS |

The `super_mode` field on IntentResult is populated at classification time via `get_super_mode()`.

### MANAGED_SECTION_ONLY Invariant

Decision projection MUST only touch the managed section:

```markdown
## Decisions (managed by MARO)
• DEC-41 v4 – Use ISO 8601 dates
---
```

**Rules:**
- Decision projection touches ONLY this block
- User content outside is NEVER modified
- Projection must fail if boundaries unclear
- Removal of managed section restores original description

### Slack as UI

Message failures don't block state or Jira sync:

```
Decision approved
    ↓
DecisionStore.approve() ← STATE (truth)
    ↓
DecisionSyncService → JIRA (projection)
    ↓
DecisionManager → SLACK (presentation, best effort)
```

Database is truth. Jira is projection. Slack is presentation.

### Canonical Message Idempotency

- Version-checked: Only update if decision.version matches
- Failure-safe: Edit failure doesn't change decision state
- Retry-safe: Same version → same blocks

### Commit Log vs State

| Concept | Nature | Mutability |
|---------|--------|------------|
| Canonical Message | Current state (HEAD) | Mutable |
| Commit Log | Historical record | Append-only |

Canonical messages show "what is true now". Commit logs show "what became true".

### Architecture Flow

```
User Input
    ↓
Intent Router → SuperMode (user) + Intent (routing)
    ↓
Decision Flow
    ↓
DecisionStore.approve() ← STATE (truth)
    ↓
DecisionSyncService → JIRA (projection)
    ↓
DecisionManager → SLACK (presentation, best effort)
```

**Mantra:** "Feel like a product, not an OS kernel."

---

## Phase 32: Product Invariants (Latest)

**Mantra:** "Invariants are physics, not rules."

Phase 32 formalizes 5 product invariants as enforced architecture, not documentation. The system makes wrong paths hard, not just discouraged.

### The 5 Invariants

| ID | Invariant | Meaning |
|----|-----------|---------|
| **I1** | SuperMode = Sole UI Contract | Users see 5 modes, never 13 intents |
| **I2** | Slack = UI | Handlers read-only, mutations via graph dispatch |
| **I3** | Commit Log = Append-Only | Event source, canonical messages rebuildable |
| **I4** | MANAGED_SECTION = Law | CI enforcement, no bypass without override |
| **I5** | Draft Lifecycle = 3 States | Users see Drafting/Ready/Published only |

### 4-Layer Protection Model

```
Layer 0: Types make wrong path hard
         - InvariantViolation exception hierarchy
         - PreflightToken, OverrideToken

Layer 1: Boundaries make right path easy
         - Gateway pattern (single door, single key)
         - JiraGateway, SlackGateway, RegistryService

Layer 2: Tokens prove checks passed
         - Cannot construct token without passing check
         - Write APIs require token to proceed

Layer 3: CI makes wrong path unshippable
         - Forbidden import tests
         - Property-based invariant tests

Layer 4: Runtime makes failures survivable
         - Structured logs with invariant names
         - Metrics for violations
```

### InvariantViolation Hierarchy

```python
class InvariantViolation(Exception):
    """Base class for invariant violations."""
    invariant_name: str = "UNKNOWN"

class ManagedSectionViolation(InvariantViolation):
    invariant_name = "MANAGED_SECTION_ONLY"

class PreflightRequired(InvariantViolation):
    invariant_name = "PREFLIGHT_REQUIRED"

class SlackWriteFromHandler(InvariantViolation):
    invariant_name = "SLACK_IS_UI"

class CommitLogMutation(InvariantViolation):
    invariant_name = "COMMIT_LOG_APPEND_ONLY"
```

### Token Pattern

```python
@dataclass(frozen=True)
class PreflightToken:
    """Proof that preflight check passed."""
    id: str
    jira_key: str
    conflict_type: str
    expires_at: datetime

    def is_valid(self) -> bool:
        return datetime.utcnow() < self.expires_at

# Cannot construct without passing check
# Write APIs require this token to proceed
```

### Escape Hatch Protocol

Override = emergency bypass with audit trail:

```python
@dataclass(frozen=True)
class OverrideToken:
    granted_by: str      # admin/owner only
    reason: str          # mandatory text
    scope: str           # operation_type or "all"
    expires_at: datetime # 10 min TTL

# Bypass goes THROUGH the system, not around it
# Must feel like pulling a fire alarm
```

On override use:
1. Post to channel (not just log)
2. Audit log entry with actor + reason
3. Suggest `/maro sync` to reconcile

### UserDraftState (I5)

Users see 3 states, internal complexity hidden:

| User State | Internal States |
|------------|-----------------|
| **Drafting** | EMPTY, SINGLE_ITEM, PLAN, PLAN_REFINED |
| **Ready** | APPROVED |
| **Published** | COMMITTED |

### Architecture Flow

```
User Input
    |
Intent Router -> SuperMode (user) + Intent (routing)
    |
Graph Dispatch (mutations go through graph, not handlers)
    |
Truth Stores (DecisionStore, WorkItemStore, DraftStore)
    |
Commit Log (append-only event source)
    |
Jira Projection (via preflight token)
    |
Slack Presentation (best effort, non-blocking)
```

**Key insight:** Slack handlers are read-only for truth stores. All mutations dispatch through graph.

---

## Phase 35: Multi-Intent Task Orchestration (Latest)

**Mantra:** "Safe tasks execute. Dangerous tasks wait."

Phase 35 replaces single-intent classification with TaskPlan orchestration. Users can express compound requests, and the bot decomposes them into tasks with dependencies and safety classifications.

### The Problem

Users write compound requests:
```
"Create stories from the decisions, check for duplicates, and review the architecture"
```

Single-winner classification loses context — only one intent wins, others are dropped.

### The Solution: TaskPlan

```python
class TaskPlan(BaseModel):
    plan_id: str
    channel_id: str
    thread_ts: str
    tasks: list[Task]
    status: TaskPlanStatus  # PENDING → RUNNING → BLOCKED → DONE
    version: int            # For idempotent button handling

class Task(BaseModel):
    task_id: str
    mode: SuperMode         # BUILD, OPERATE, DECIDE, THINK, CHAT
    intent: Intent          # Fine-grained routing
    title: str
    status: TaskStatus      # PENDING → RUNNING → BLOCKED → DONE → CANCELED
    safety_level: SafetyLevel
    side_effects: list[SideEffect]
    depends_on: list[str]   # Task IDs this depends on
```

### Safety Classification

| Mode | Safety Level | Auto-Execute? |
|------|--------------|---------------|
| THINK | AUTO_EXECUTE | Yes |
| CHAT | AUTO_EXECUTE | Yes |
| BUILD | REQUIRES_CONFIRMATION | No |
| OPERATE | REQUIRES_CONFIRMATION | No |
| DECIDE | REQUIRES_CONFIRMATION | No |

**Override:** Any task with `SideEffect.JIRA` always requires confirmation.

### Two-Stage Classification

1. **Stage 1:** Quick single-intent classification
2. **Stage 2:** Re-classify with multi-intent if signals detected

**Multi-intent signals:**
- Conjunctions: "and", "also", "plus", "then"
- Low confidence: <0.7 on single-intent
- Multiple action verbs: ≥2 verbs detected

### Execution Flow

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
    └─ If REQUIRES_CONFIRMATION → block, show buttons
    ↓
dispatch handlers
    ├─ task_plan_created → post status card
    ├─ task_confirmation_required → show approval buttons
    ├─ task_plan_complete → post summary
    └─ task_failed → show error
```

### Canonical UX

```
I see 3 actions:
1. Check Jira duplicates
2. Create stories from decisions
3. Review the architecture

Executing 1 now. For 2 and 3 — OK?
```

### Status Card

Single editable message with throttled updates (1.5s minimum):

```
🛠 MARO Plan — BUILD (2/3 tasks)

1) ✅ THINK: Check Jira duplicates
2) ⏳ BUILD: Create stories (waiting approval)
3) ⏸ THINK: Review architecture (blocked)

[Cancel plan]
(2) [Approve] [Reject]
```

### Version-Bound Buttons

```python
# Button value format
value = f"{plan_id}:{task_id}:{plan.version}"

# On click
if plan.version != button_version:
    respond("⚠️ This action is outdated. The plan has been updated.")
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `TaskPlan`, `Task` | Data models (src/schemas/task_plan.py) |
| `TaskPlanStore` | CRUD with optimistic locking (src/db/task_plan_store.py) |
| `classify_task_safety()` | Safety level inference (src/graph/safety.py) |
| `task_decomposer_node` | Proposal → TaskPlan (src/graph/nodes/task_decomposer.py) |
| `task_executor_node` | Dependency-aware execution (src/graph/nodes/task_executor.py) |
| `TaskStatusUpdater` | Throttled Slack updates (src/slack/task_status_updater.py) |
| `build_task_plan_blocks()` | Status card UI (src/slack/blocks/task_plan.py) |

---

## Phase 36: Question Engine — Conversation Driver (Latest)

**Mantra:** "Questions are tasks. Mode drives behavior. Budget prevents spam."

Phase 36 transforms MARO from an event recorder into a conversation leader. Questions become first-class tasks in the TaskPlan with explicit status tracking, and the bot manages Active/Passive modes to know when to lead vs. listen.

### The Three Core Concepts

| Concept | Description |
|---------|-------------|
| **Questions as Tasks** | QuestionTask extends Task model — questions are planned, prioritized, and tracked |
| **Active/Passive Mode** | State machine: ACTIVE (bot leads, posts questions) vs PASSIVE (bot listens, acknowledges) |
| **Question Budget** | Max 2 unanswered questions before partial preview — prevents bot spam |

### QuestionTask Schema

```python
class QuestionTask(BaseModel):
    question_id: str  # UUID
    question_type: QuestionType  # CONFIRM_SCOPE, COLLECT_FIELD, RESOLVE_CONFLICT, ASK_USER
    question_text: str
    target_field: Optional[str]  # For COLLECT_FIELD, which draft field we're filling
    options: Optional[list[QuestionOption]]  # For choice-based questions
    priority: int = 100  # Lower = ask first
    status: QuestionStatus  # PENDING, ANSWERED, SKIPPED
    answer: Optional[str]
    answered_at: Optional[datetime]
```

### Question Types

| Type | Use Case | Answer Format |
|------|----------|---------------|
| **CONFIRM_SCOPE** | "Stories under this epic?" | Button click (deterministic) |
| **COLLECT_FIELD** | "What are the acceptance criteria?" | Free-form text (LLM-parsed) |
| **RESOLVE_CONFLICT** | "Keep Slack or Jira version?" | Button click |
| **ASK_USER** | Freeform fallback | Text reply |

### Active/Passive Mode

```
PASSIVE (default)
    │
    ├─ @mention → ACTIVE
    ├─ /command → ACTIVE
    └─ Task BLOCKED → ACTIVE

ACTIVE
    │
    ├─ Plan COMPLETE → PASSIVE
    ├─ 10min timeout → PASSIVE
    └─ User CANCEL → PASSIVE
```

**Behavior Differences:**

| Mode | Bot Behavior |
|------|--------------|
| **ACTIVE** | Leads conversation, posts questions, follows up |
| **PASSIVE** | Listens, acknowledges, doesn't ask unprompted |

### Question Budget

- **Budget:** Max 2 unanswered questions in a row
- **Reset:** New user message resets budget to 0
- **Exhausted:** Show partial preview with [Proceed][Wait][Cancel] buttons

```
Question asked → budget++
Answer received → budget = 0
Budget == 2 → show partial preview
```

### QuestionCatalog: Hybrid Generation

| Question Type | Generation Method |
|---------------|-------------------|
| CONFIRM_SCOPE | Templates (deterministic) |
| COLLECT_FIELD | LLM-generated (flexible prompts) |
| RESOLVE_CONFLICT | Templates |
| ASK_USER | LLM fallback |

### AnswerMapper: Hybrid Processing

| Input Type | Processing |
|------------|------------|
| Button click | Deterministic mapping → StatePatch (confidence=1.0) |
| Text reply | LLM parsing → StatePatch (confidence varies) |

Low confidence (<0.7) triggers clarification question.

### Key Components

| Component | Purpose |
|-----------|---------|
| `QuestionTask`, `QuestionType` | Question schema (src/schemas/question.py) |
| `ConversationModeStore` | Mode persistence (src/db/conversation_mode_store.py) |
| `ModeManager` | Mode transition logic (src/questions/mode_manager.py) |
| `QuestionCatalog` | Question generation (src/questions/catalog.py) |
| `AnswerMapper` | Answer processing (src/questions/answer_mapper.py) |
| `BudgetTracker` | Budget enforcement (src/questions/budget_tracker.py) |
| `question_executor_node` | Question task execution (src/graph/nodes/question_executor.py) |
| `build_question_blocks()` | Question UI (src/slack/blocks/question.py) |

---

## Phase 39: Intent Classification v2 (Latest)

**Mantra:** "Know intent kind before classification. Terminal intents END immediately."

Phase 39 refactors the intent classification system into a 2-stage architecture that improves accuracy, reduces LLM calls, and simplifies routing for simple intents.

### The Problem

The existing intent classifier has accumulated complexity:
- Single monolithic prompt classifying 13+ intents
- Terminal intents (DISCUSSION, META) go through full graph unnecessarily
- Pre-classification checks scattered across dispatch handlers
- Multi-intent detection bolted on top of single-intent classification

### The Solution: 2-Stage Architecture

```
User Message
    |
Stage 1: Pre-Gates (deterministic, no LLM)
    |   - Empty message? -> NOOP
    |   - Button action? -> Extract intent from payload
    |   - Slash command? -> Map to known intent
    |   - Thread-bound ticket? -> TICKET_ACTION default
    |
Stage 2: LLM Classification (if needed)
    |   - Classify into IntentKind first (terminal vs work)
    |   - Then classify specific Intent within kind
    |
IntentEnvelope
    |
Router
    |-> Terminal? -> terminal_response_node -> END
    |-> Work? -> Existing graph flows
```

### IntentEnvelope Schema

```python
class IntentEnvelope(BaseModel):
    """Envelope wrapping classified intent with routing metadata."""
    kind: IntentKind          # TERMINAL, WORK, PENDING_ACTION
    intent: Optional[Intent]  # Specific intent (DISCUSSION, TICKET, etc.)
    confidence: float         # Classification confidence
    source: IntentSource      # PRE_GATE, LLM, BUTTON, COMMAND
    gate_hit: Optional[str]   # Which pre-gate matched
    legacy_result: Optional[dict]  # Backward compat with IntentResult
```

### IntentKind Classification

First classify the **kind** of intent, then the specific intent:

| Kind | Description | Routing |
|------|-------------|---------|
| **TERMINAL** | Single response then END | terminal_response_node -> END |
| **WORK** | Requires graph workflow | Existing flow nodes |
| **PENDING_ACTION** | Button/command continuation | Resume from state |
| **NOOP** | No action needed | Skip graph entirely |

### Pre-Gates (Stage 1)

Deterministic checks that bypass LLM classification:

| Gate | Check | Result |
|------|-------|--------|
| `empty_message` | Message is empty/whitespace | NOOP |
| `button_action` | Event has button payload | Extract from payload |
| `slash_command` | Event is slash command | Map command to intent |
| `thread_binding` | Thread bound to ticket | TICKET_ACTION default |
| `explicit_trigger` | Message starts with known trigger | Map trigger to intent |

Pre-gates reduce LLM calls and ensure consistent behavior for deterministic cases.

### Terminal Intents

DISCUSSION and META intents are now handled specially:

```
envelope.kind == TERMINAL
    |
    v
terminal_response_node
    |   - Generate single response
    |   - No follow-up questions
    |   - No state mutations
    |
    v
END (graph terminates immediately)
```

This replaces the previous flow where DISCUSSION/META went through discussion_node with full state management.

### Backward Compatibility

Phase 39 maintains backward compatibility during migration:

```python
# New wrapper returns both envelope and legacy result
result = await classify_intent_v2(state)
envelope = result["envelope"]        # New
legacy_result = result["intent_result"]  # Old

# Router checks envelope first
if envelope and is_terminal_intent(envelope):
    return "terminal_response_flow"
# Fall back to legacy routing
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `IntentEnvelope` | Intent wrapper with kind and routing metadata |
| `IntentKind` | TERMINAL, WORK, PENDING_ACTION, NOOP |
| `intent_router_node` | Pre-gates + LLM classification |
| `is_terminal_intent()` | Check if envelope indicates terminal |
| `terminal_response_node` | Generate single response for CHAT/META |
| `classify_intent_v2()` | Backward-compatible wrapper |
| `get_intent_classifier()` | Factory for v1/v2 classifier |

### Migration Path

1. **Phase 39-01 to 39-06**: Build IntentEnvelope, IntentKind, pre-gates
2. **Phase 39-07**: Wire terminal_response_node to graph
3. **Phase 39-08+**: Migrate remaining intents to v2 classification
4. **Phase 39-Final**: Remove legacy IntentResult

---

## Table of Contents

1. [System Overview](#system-overview)
2. [The Brain: LangGraph Orchestration](#the-brain-langgraph-orchestration)
3. [State Management](#state-management)
4. [Workflow Phases](#workflow-phases)
5. [Node Architecture](#node-architecture)
6. [Routing Logic](#routing-logic)
7. [Memory System](#memory-system)
8. [Entity Extraction & Knowledge Graph](#entity-extraction--knowledge-graph)
9. [Persona System](#persona-system)
10. [Slack Integration](#slack-integration)
11. [Jira Integration](#jira-integration)
12. [Admin Dashboard](#admin-dashboard)
13. [Configuration](#configuration)
14. [Data Flow Diagrams](#data-flow-diagrams)

---

## System Overview

MARO is built on the following technology stack:

| Component | Technology |
|-----------|------------|
| **Orchestration** | LangGraph StateGraph with PostgreSQL checkpointer |
| **Memory** | PostgreSQL (conversation history, two-layer context) |
| **Chat Interface** | Slack Bolt (async, Socket Mode) |
| **Issue Tracking** | Jira via atlassian-python-api (direct API) |
| **LLM Providers** | Gemini (default), OpenAI, Anthropic (configurable) |
| **Database** | PostgreSQL (state, WorkItems, approvals, config) |
| **Deployment** | Docker Compose on GCE VM |

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Slack Interface                          │
│  (Messages, @mentions, Commands, Approval Buttons)               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph "Brain"                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │ Memory  │→ │ Intake  │→ │ Phases  │→ │ Approval│            │
│  │  Node   │  │  Node   │  │ (1-10)  │  │  Node   │            │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘            │
│       │                                       │                  │
│       ▼                                       ▼                  │
│  ┌─────────┐                           ┌─────────┐              │
│  │   Zep   │                           │  Jira   │              │
│  │ Memory  │                           │  Write  │              │
│  └─────────┘                           └─────────┘              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL                                  │
│  (Checkpoints, Approvals, Channel Config, Knowledge Files)       │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Brain: LangGraph Orchestration

The "brain" of MARO is a **LangGraph StateGraph** that orchestrates requirement processing through multiple specialized nodes. It implements:

- **Actor Model**: Independent nodes processing messages
- **Reflexion Pattern**: Critique loop for self-improvement
- **Human-in-the-Loop**: Interrupt before critical decisions
- **Multi-turn Conversation**: Checkpointing enables resumption
- **State Machine**: Explicit phases with clear transitions

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/graph/state.py` | 419 | State schema (RequirementState, enums) |
| `src/graph/graph.py` | 455 | StateGraph builder, invoke/resume functions |
| `src/graph/routers.py` | 345 | 16 conditional edge routing functions |
| `src/graph/checkpointer.py` | 498 | PostgreSQL persistence |
| `src/graph/nodes/*.py` | 4,238 | 13 node implementation files |

### Graph Compilation

```python
graph = StateGraph(RequirementState)

# Add 23 nodes
graph.add_node("memory", memory_node)
graph.add_node("intake", intake_node)
# ... 21 more nodes

# Add conditional edges with routers
graph.add_conditional_edges("intake", intake_router, {...})

# Compile with checkpointer and interrupt
compiled = graph.compile(
    checkpointer=postgres_checkpointer,
    interrupt_before=["human_approval"]  # HITL pause point
)
```

---

## State Management

The `RequirementState` TypedDict flows through all nodes, containing:

### Input Context
```python
channel_id: str              # Slack channel
thread_ts: str | None        # Thread timestamp
user_id: str                 # Requesting user
message: str                 # Current message
attachments: list[dict]      # Parsed file attachments
is_mention: bool             # Bot was @mentioned
```

### Memory Integration
```python
zep_facts: list[dict]        # Retrieved context from Zep
zep_session_id: str          # Session identifier
related_jira_issues: list    # Cross-referenced issues
messages: Annotated[list, add_messages]  # Conversation history
```

### Intent & Persona
```python
intent: IntentType           # REQUIREMENT, MODIFICATION, QUESTION, JIRA_*
intent_confidence: float     # 0.0-1.0
persona_matches: list        # Matched personas with confidence
active_persona: str | None   # Currently active persona
```

### Workflow Progress
```python
current_phase: WorkflowPhase # Current phase enum
phase_history: list[str]     # Completed phases
progress_steps: list[dict]   # Phase status for UI
```

### Hierarchical Structure
```python
epics: list[dict]            # Epic definitions
stories: list[dict]          # User stories with epic refs
tasks: list[dict]            # Technical tasks with story refs
```

### Analysis & Estimation
```python
architecture_options: list   # 2-3 architecture proposals
chosen_architecture: str     # Selected architecture
total_story_points: int      # Aggregated points
total_hours: float           # Effort estimate
risk_buffer_percent: float   # Risk buffer
validation_report: dict      # Validation results
```

### Human-in-the-Loop
```python
awaiting_human: bool         # Graph paused for decision
human_decision: HumanDecision  # APPROVE, EDIT, REJECT, PENDING
human_feedback: str | None   # Edit feedback from user
```

### Jira Operations
```python
jira_action: str | None      # create, update, link, search
jira_issue_key: str | None   # Created/updated issue
jira_items: list[dict]       # Tracked items with status
```

### Output
```python
response: str                # Message to send
should_respond: bool         # Bot should generate response
response_target: str         # "thread", "channel", "broadcast"
error: str | None            # Error message if failed
```

---

## Workflow Phases

MARO processes requirements through 11 distinct phases:

| Phase | Node | Description |
|-------|------|-------------|
| 1. INTAKE | `intake` | Intent classification, confidence scoring |
| 2. DISCOVERY | `discovery` | Generate clarifying questions if needed |
| 3. ARCHITECTURE | `architecture` | Propose 2-3 architecture options |
| 4. SCOPE | `scope` | Define epics, in/out of scope |
| 5. STORIES | `stories` | Break down into user stories |
| 6. TASKS | `tasks` | Decompose into technical tasks |
| 7. ESTIMATION | `estimation` | Story points, hours, risk buffer |
| 8. SECURITY | `security` | Security review (OWASP Top 10) |
| 9. VALIDATION | `validation` | Check for gaps, conflicts |
| 10. REVIEW | `final_review` | Summary before approval |
| 11. JIRA_SYNC | `jira_write` | Create issues in Jira |

### Phase Flow Diagram

```
User Message
    │
    ▼
┌─────────┐    ┌───────────┐    ┌──────────────┐
│ MEMORY  │───▶│  INTAKE   │───▶│  DISCOVERY   │
└─────────┘    └───────────┘    └──────────────┘
                                       │
                    ┌──────────────────┘
                    ▼
            ┌──────────────┐    ┌─────────┐    ┌──────────┐
            │ ARCHITECTURE │───▶│  SCOPE  │───▶│ STORIES  │
            └──────────────┘    └─────────┘    └──────────┘
                                                    │
                    ┌───────────────────────────────┘
                    ▼
            ┌─────────┐    ┌────────────┐    ┌──────────┐
            │  TASKS  │───▶│ ESTIMATION │───▶│ SECURITY │
            └─────────┘    └────────────┘    └──────────┘
                                                   │
                    ┌──────────────────────────────┘
                    ▼
            ┌────────────┐    ┌────────────┐
            │ VALIDATION │───▶│   REVIEW   │
            └────────────┘    └────────────┘
                                    │
                                    ▼
                           ┌────────────────┐
                           │ HUMAN APPROVAL │ ◀── INTERRUPT POINT
                           └────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌───────────┐   ┌──────────┐
              │ APPROVE  │   │   EDIT    │   │  REJECT  │
              └──────────┘   └───────────┘   └──────────┘
                    │               │               │
                    ▼               ▼               ▼
              ┌──────────┐   ┌───────────┐   ┌──────────┐
              │JIRA WRITE│   │ DISCOVERY │   │ RESPONSE │
              └──────────┘   └───────────┘   └──────────┘
```

---

## Node Architecture

### Node Categories (23 total nodes)

```
src/graph/nodes/
├── common.py (272 lines)     # Shared helpers, LLM utilities
├── intake.py (637 lines)     # Intent classification, initial processing
├── architecture.py (241)     # Phase 3: Architecture exploration
├── planning.py (540 lines)   # Phase 4-6: Scope, stories, tasks
├── analysis.py (630 lines)   # Phase 7-9: Estimation, security, validation
├── review.py (141 lines)     # Phase 10: Final review
├── drafting.py (346 lines)   # Conflict detection, draft/critique loop
├── approval.py (76 lines)    # Human approval, decision processing
├── jira.py (660 lines)       # Jira CRUD operations
├── memory.py (203 lines)     # Zep memory retrieval/update
├── impact.py (210 lines)     # Impact analysis for modifications
├── response.py (150 lines)   # Response generation
└── __init__.py (132 lines)   # Re-exports all nodes
```

### Key Node Descriptions

| Node | Purpose |
|------|---------|
| `memory` | Retrieve Zep context, extract entities, store messages |
| `intake` | LLM classifies intent, identifies matching personas |
| `discovery` | Generates clarifying questions based on knowledge gaps |
| `architecture` | Proposes 2-3 architecture options with trade-offs |
| `scope` | Creates epic definitions, in/out of scope |
| `stories` | Breaks epics into user stories with acceptance criteria |
| `tasks` | Decomposes stories into technical tasks |
| `estimation` | Calculates story points, hours, risk buffer |
| `security` | Security review against OWASP Top 10 |
| `validation` | Checks for gaps, conflicts, completeness |
| `final_review` | Summarizes artifacts before approval |
| `human_approval` | **INTERRUPT POINT** - Pauses for user decision |
| `process_decision` | Routes based on approve/edit/reject |
| `jira_write` | Creates Epic→Story→Task hierarchy in Jira |
| `impact_analysis` | Analyzes modification impact, determines restart phase |

---

## Routing Logic

### 16 Conditional Edge Routers

Each router examines state and returns the next node:

```python
def intake_router(state: RequirementState) -> str:
    if not state.get("should_respond"):
        return "no_response"

    intent = state.get("intent")
    if intent == "JIRA_READ":
        return "jira_read"
    if intent == "REQUIREMENT" and state.get("clarifying_questions"):
        return "discovery"
    if intent == "REQUIREMENT":
        return "architecture"
    # ... more routing logic
```

### Router Summary

| Router | Examines | Routes To |
|--------|----------|-----------|
| `should_respond_router` | `should_respond` flag | response or no_response |
| `intent_router` | `intent` type | Various based on intent |
| `intake_router` | Intent, questions | discovery/architecture/jira |
| `discovery_router` | Has questions? | response or architecture |
| `architecture_router` | Has response? | response or scope |
| `scope_router` | Phase complete? | response or stories |
| `story_router` | Phase complete? | response or tasks |
| `task_router` | Phase complete? | response or estimation |
| `human_decision_router` | `human_decision` | jira_write/discovery/response |
| `impact_router` | `impact_level` | Restart from appropriate phase |

---

## Memory System

### Zep Integration

MARO uses Zep Community Edition for long-term memory with semantic search.

**Location**: `src/memory/zep_client.py`

```python
class ZepMemoryClient:
    async def ensure_session(channel_id, user_id)  # Create/get session

class MemoryOperations:
    async def add(session_id, messages)    # Store messages
    async def get(session_id, limit=10)    # Retrieve recent
    async def search(session_id, text)     # Semantic search
    async def clear(session_id)            # Delete all

class FactOperations:
    async def get_facts(session_id)        # Get extracted facts
    async def add_fact(session_id, fact)   # Add fact manually
```

### Session Management

- **Session ID Format**: `channel-{channel_id}`
- **Storage**: Messages with metadata (user_id, entities, relationships)
- **Retrieval**: Semantic search + recent history

### Memory Node Workflow

```
1. Ensure Session exists in Zep
        │
        ▼
2. Search for relevant past memories
        │
        ▼
3. Extract knowledge from current message (LLM)
   ├── Entities
   ├── Relationships
   ├── Knowledge gaps
   └── Suggested questions
        │
        ▼
4. Merge into Knowledge Graph
        │
        ▼
5. Store message with metadata to Zep
        │
        ▼
6. Return context to workflow
   └── zep_facts, clarifying_questions
```

---

## Entity Extraction & Knowledge Graph

### Entity Types (14 domain-specific)

| Type | Description |
|------|-------------|
| `requirement` | Functional/non-functional requirement |
| `constraint` | Limitations or restrictions |
| `acceptance_criteria` | Conditions for acceptance |
| `risk` | Potential problems/threats |
| `dependency` | System dependencies |
| `stakeholder` | People/roles involved |
| `component` | System components/modules |
| `integration` | External systems/APIs |
| `data_entity` | Database objects |
| `user_action` | User-performable actions |
| `business_rule` | Business logic policies |
| `priority` | Priority levels |
| `timeline` | Deadlines/time constraints |
| `technology` | Technologies/frameworks |

### Relationship Types (10)

| Type | Meaning |
|------|---------|
| `requires` | Entity A requires B to function |
| `implements` | Entity A implements B |
| `depends_on` | Entity A depends on B |
| `conflicts_with` | Contradiction between entities |
| `refines` | Entity A refines/details B |
| `belongs_to` | Hierarchical ownership |
| `affects` | A impacts B |
| `validates` | A validates B |
| `uses` | A uses B |
| `owned_by` | A managed by stakeholder B |

### Knowledge Graph Class

```python
class KnowledgeGraph:
    session_id: str
    entities: dict[str, dict]      # name → entity data
    relationships: list[dict]       # All relationships
    knowledge_gaps: list[dict]      # Identified gaps
    message_count: int              # Messages processed

    def merge_knowledge(knowledge) -> dict  # Merge extracted data
    def get_suggested_questions() -> list   # Generate questions
    def to_dict() / from_dict()             # Serialization
```

### Extraction Output

```json
{
  "entities": [
    {
      "name": "User Authentication",
      "type": "component",
      "description": "OAuth2-based login system",
      "attributes": {"priority": "high"},
      "is_update": false
    }
  ],
  "relationships": [
    {
      "source": "User Authentication",
      "target": "User Database",
      "type": "depends_on"
    }
  ],
  "knowledge_gaps": [
    {
      "entity": "User Authentication",
      "gap_type": "missing_criteria",
      "description": "No acceptance criteria defined"
    }
  ],
  "suggested_questions": [
    "What authentication methods should be supported?"
  ]
}
```

---

## Persona System

### Available Personas

| Persona | Focus Areas | Personality |
|---------|-------------|-------------|
| **Architect** | System design, components, scalability | Formal, low humor, detailed |
| **Product Manager** | User stories, acceptance criteria, priority | Moderate formality, balanced |
| **Security Analyst** | OWASP, compliance, vulnerabilities | Very formal, no humor, thorough |

### Persona Structure

```
personas/
├── architect/
│   └── knowledge.md       # Architecture patterns, design decisions
├── product_manager/
│   └── knowledge.md       # User story formats, INVEST principles
└── security_analyst/
    └── knowledge.md       # Security checklists, OWASP Top 10
```

### PersonaConfig

```python
@dataclass
class PersonaConfig:
    name: str                    # Internal name
    display_name: str            # "Solution Architect"
    description: str             # Role description
    system_prompt: str           # Full LLM system prompt
    knowledge_base: str          # Loaded markdown content
    model: str                   # Preferred LLM model
    personality: PersonalityConfig
    triggers: list[str]          # Activation keywords

@dataclass
class PersonalityConfig:
    humor: float        # 0.0-1.0
    emoji_usage: float  # 0.0-1.0
    formality: float    # 0.0-1.0
    verbosity: float    # 0.0-1.0
```

### Persona Usage in Workflow

| Phase | Persona Used |
|-------|--------------|
| Architecture | Architect |
| Scope | Product Manager |
| Stories | Product Manager |
| Tasks | Architect |
| Estimation | Architect |
| Security | Security Analyst |
| Response | Active persona (from intent) |

---

## Slack Integration

### Event Handling

**Location**: `src/slack/handlers/`

```python
@app.event("message")
async def handle_message(event, say, client):
    # 1. Skip bot messages, edits, deletes
    # 2. Detect @mentions
    # 3. Process file attachments
    # 4. Load channel configuration
    # 5. Initialize progress reporter
    # 6. Create/restore thread state
    # 7. Invoke LangGraph workflow
    # 8. Handle result (approval request or response)
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/req-status` | Show current workflow state |
| `/req-clean` | Clear memory, state, config |
| `/req-config` | Open channel configuration modal |
| `/req-approve list` | List permanent approvals |
| `/req-approve delete <id>` | Delete approval pattern |

### Approval Workflow

```
Graph reaches human_approval node
           │
           ▼
Approval Request Posted (Block Kit UI)
├── Draft Preview (title, type, criteria)
├── Conflicts (if any)
└── Action Buttons:
    ├── [Approve] - One-time approval
    ├── [Approve Always] - Permanent pattern
    ├── [Edit] - Open edit modal
    └── [Reject] - Cancel requirement
           │
           ▼
User clicks button
           │
           ▼
resume_graph(thread_id, decision, feedback)
           │
           ▼
Graph continues from interrupt point
```

### Channel Configuration

Stored per-channel in PostgreSQL:

```python
@dataclass
class ChannelConfig:
    channel_id: str
    jira_project_key: str | None
    jira_default_issue_type: str   # Story/Task/Bug/Epic
    default_model: str             # LLM model selection
    personality: PersonalityConfig # Bot personality traits
    persona_knowledge: dict        # Custom knowledge per persona
```

### Progress Tracking

Real-time Slack message updates as workflow progresses:

```
☐ Analyzing request
☐ Discovery & clarification
☐ Architecture options
☐ Scope definition
☐ Story breakdown
☐ Task breakdown
☐ Estimation
☐ Security review
☐ Validation
☐ Ready for approval
```

Status indicators: `☐` (pending) → `🔄` (in progress) → `✅` (complete)

---

## Jira Integration

### MCP Client

**Location**: `src/jira/mcp_client.py`

```python
class JiraMCPClient:
    async def create_issue(project_key, issue_type, summary,
                          description, priority, labels, parent_key)
    async def update_issue(issue_key, fields)
    async def get_issue(issue_key)
    async def search_issues(jql, max_results)
    async def add_comment(issue_key, body)
    async def delete_issue(issue_key)
    async def link_issues(inward_key, outward_key, link_type)
```

### Hierarchy Creation

```
Epic (created first)
├── Story 1 (linked via Epic Link field)
│   ├── Task 1.1 (parent = Story 1)
│   └── Task 1.2
├── Story 2
│   ├── Task 2.1
│   └── Task 2.2
└── Story 3
```

### Jira Command Nodes

| Node | Trigger | Action |
|------|---------|--------|
| `jira_write` | Approval | Create hierarchy |
| `jira_read` | "re-read PROJ-123" | Fetch latest data |
| `jira_status` | "show status" | Display tracked items |
| `jira_add` | "add story to EPIC-1" | Create linked item |
| `jira_update` | "update PROJ-123" | Modify fields |
| `jira_delete` | "delete PROJ-123" | Remove issue |

### Priority Mapping

| Workflow Priority | Jira Priority |
|-------------------|---------------|
| Must / Critical | Highest |
| Should / High | High |
| Could / Medium | Medium |
| Won't / Low | Low |

---

## Admin Dashboard

### Routes Overview

**Location**: `src/admin/routes/`

| Route | Description |
|-------|-------------|
| `/admin/dashboard` | System health, stats, config |
| `/admin/zep/sessions` | List memory sessions |
| `/admin/zep/sessions/{id}` | Session details, messages, facts |
| `/admin/zep/knowledge-graph` | D3.js knowledge graph |
| `/admin/graph/threads` | List workflow threads |
| `/admin/graph/threads/{id}` | Thread state inspection |
| `/admin/graph/mermaid` | Workflow diagram (Mermaid) |
| `/admin/graph/visualize` | Interactive workflow graph |

### Knowledge Graph Visualization

Interactive D3.js force-directed graph showing:

- **Entity nodes**: Color-coded by type
- **Relationship edges**: Labeled with type
- **Knowledge gaps**: Dashed orange nodes
- **Session selector**: View one session at a time
- **Filtering**: By entity type
- **Zoom controls**: In, out, reset

### API Endpoints

```
GET  /admin/api/zep/sessions          # List sessions (JSON)
GET  /admin/api/graph/threads         # List threads (JSON)
DELETE /admin/api/zep/sessions/{id}   # Delete session
DELETE /admin/api/graph/threads/{id}  # Delete thread
GET  /admin/api/knowledge-graph       # Knowledge graph data
GET  /admin/api/graph/data            # Workflow structure
```

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/maro

# Zep Memory
ZEP_API_URL=http://localhost:8001

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

# Jira
JIRA_URL=https://company.atlassian.net
JIRA_USER=user@company.com
JIRA_API_TOKEN=...
JIRA_MCP_URL=http://localhost:3000/sse

# LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...

# Observability
LANGCHAIN_PROJECT=maro
LANGCHAIN_API_KEY=...
```

### Settings Class

**Location**: `src/config/settings.py`

```python
class Settings(BaseSettings):
    environment: str = "development"
    default_llm_model: str = "gpt-4o"

    # Database
    database_url: str

    # Zep
    zep_api_url: str = "http://localhost:8001"

    # Slack
    slack_bot_token: str
    slack_app_token: str

    # Jira
    jira_url: str
    jira_user: str
    jira_api_token: str
    jira_mcp_url: str = "http://localhost:3000/sse"

    # LLM
    openai_api_key: str
    anthropic_api_key: str
    google_api_key: str
```

---

## Data Flow Diagrams

### Complete Message Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      User sends message                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Slack Handler (src/slack/handlers/main.py)                       │
│ ├── Skip bot messages, edits, deletes                           │
│ ├── Detect @mentions and remove mention text                    │
│ ├── Process file attachments                                    │
│ ├── Load channel config from PostgreSQL                         │
│ ├── Initialize ProgressReporter                                 │
│ └── Create/restore thread state                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ LangGraph Workflow (src/graph/)                                  │
│                                                                  │
│ memory ─▶ intake ─▶ discovery ─▶ architecture ─▶ scope ─▶       │
│ stories ─▶ tasks ─▶ estimation ─▶ security ─▶ validation ─▶     │
│ final_review ─▶ HUMAN_APPROVAL (interrupt)                       │
│                       │                                          │
│         ┌─────────────┼─────────────┐                           │
│         ▼             ▼             ▼                           │
│     APPROVE         EDIT        REJECT                          │
│         │             │             │                           │
│         ▼             ▼             ▼                           │
│    jira_write    discovery     response                         │
│         │                                                        │
│         ▼                                                        │
│   memory_update ─▶ response                                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ External Systems                                                 │
│ ├── Zep: Store messages, extract entities, semantic search      │
│ ├── Jira: Create Epic→Story→Task hierarchy                      │
│ └── PostgreSQL: Checkpoints, config, approvals                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Response sent to Slack thread                                    │
└─────────────────────────────────────────────────────────────────┘
```

### Checkpointing Flow

```
Graph Execution
      │
      ▼
┌─────────────────────┐
│  Node completes     │
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Checkpoint saved    │──▶ PostgreSQL langgraph_checkpoints
│ to PostgreSQL       │    ├── thread_id
└─────────────────────┘    ├── checkpoint_id
      │                    ├── parent_checkpoint_id
      ▼                    ├── checkpoint (JSONB state)
┌─────────────────────┐    └── metadata
│ Next node or        │
│ INTERRUPT           │
└─────────────────────┘
      │
      ▼ (if interrupt)
┌─────────────────────┐
│ Graph pauses        │
│ State persisted     │
└─────────────────────┘
      │
      ▼ (user decision)
┌─────────────────────┐
│ resume_graph()      │
│ loads checkpoint    │
│ continues execution │
└─────────────────────┘
```

---

## Summary

MARO v2 is a production-ready requirements orchestration system featuring:

- **Sophisticated LangGraph brain** with 23 nodes and 16 routers
- **11-phase workflow** from intake to Jira creation
- **Human-in-the-loop approval** with edit and rejection paths
- **Long-term memory** via Zep with semantic search
- **LLM-based entity extraction** building knowledge graphs
- **Three specialized personas** (Architect, PM, Security)
- **Full Slack integration** with commands and approval UI
- **Jira MCP integration** for issue hierarchy creation
- **Comprehensive admin dashboard** with D3.js visualizations
- **PostgreSQL persistence** for state, config, and approvals

The architecture follows best practices for:
- Async/await throughout for scalability
- State isolation per conversation thread
- Graceful error handling and degradation
- Streaming support for progress updates
- Modular design with clear separation of concerns

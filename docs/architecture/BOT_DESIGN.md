# MARO 2.0 Bot Design: How It Thinks

This document explains the cognitive architecture of MARO — how it processes messages, makes decisions, and maintains state. A person reading this should understand the bot's "mental model."

---

## Table of Contents

1. [Core Philosophy](#core-philosophy)
2. [Mental Model: The Git Analogy](#mental-model-the-git-analogy)
3. [Two-Stage Intent Classification](#two-stage-intent-classification)
4. [Four SuperModes](#four-supermodes)
5. [Entity Lifecycle State Machine](#entity-lifecycle-state-machine)
6. [Decision-Making Rules](#decision-making-rules)
7. [Process Orchestration](#process-orchestration)
8. [Prompts Overview](#prompts-overview)
9. [Safety Guardrails](#safety-guardrails)
10. [Jira Projection](#jira-projection)
11. [Structured Questions (Smart UX)](#structured-questions-smart-ux)
12. [Intent Audit Logging](#intent-audit-logging)
13. [Deterministic Post-Filters](#deterministic-post-filters)
14. [Observability Tools](#observability-tools)

---

## Core Philosophy

**"Threads propose. Channels decide. Jira executes."**

MARO treats communication as the source of truth. The bot doesn't store work items — it stores *events* that describe what happened in conversations. Current state is derived by replaying these events.

### Key Principles

1. **Sum Types Over Optionals** — An entity is in exactly ONE state. There's no "maybe proposed" or "partially approved."

2. **Events Over State** — We never mutate. We append events and derive current state.

3. **Channel as Aggregate Root** — All mutations flow through the channel. The channel "owns" its entities.

4. **Facilitate, Don't Dictate** — The bot helps reach consensus. It doesn't force decisions.

5. **Explicit Over Implicit** — No magic. Every state transition is an event. Every decision is traceable.

---

## Mental Model: The Git Analogy

| Git Concept | MARO Equivalent |
|-------------|-----------------|
| Repository | Channel |
| Branch | Thread |
| Commit | Approval |
| HEAD | Canonical message |
| Push | Sync to Jira |
| Merge conflict | Decision conflict |

**Jira is not the source of truth** — it's a deployment artifact built from the source (conversation).

---

## Two-Stage Intent Classification

When a message arrives, MARO uses two stages to decide what to do:

### Stage 1: PreGates (Deterministic)

Fast, rule-based checks that short-circuit LLM calls:

```
Message arrives
    ↓
Is it a button click? → Handle button action
    ↓
Is it a slash command? → Handle command
    ↓
Is it in a known process thread? → Route to process
    ↓
Is it from the bot? → Ignore
    ↓
Pass to Stage 2
```

### Stage 2: LLM Router

For messages that pass PreGates, the LLM classifies intent:

```
Input: Message text + thread context + channel entities

Output: {
  mode: CREATE | MODIFY | RECORD | CONVERSE,
  confidence: 0.0-1.0,
  entity_type: work_item | decision | null,
  reasoning: "..."
}
```

**Confidence Threshold Rule:**
- If `confidence < 0.7` → Fall back to CONVERSE mode
- Never take action when uncertain

---

## Four SuperModes

Every message results in one of four modes:

### CREATE Mode
**Trigger:** User wants to define a new work item or decision
**Behavior:**
1. Extract structured content from conversation
2. Create Draft entity
3. Post formatted preview
4. Offer "Propose to channel" button

### MODIFY Mode
**Trigger:** User wants to change an existing entity
**Behavior:**
1. Identify target entity
2. Validate lifecycle allows modification (Draft or Proposed only)
3. Apply changes
4. Emit `EntityUpdated` event
5. Update canonical message

### RECORD Mode
**Trigger:** User made a decision that should be captured
**Behavior:**
1. Extract decision from context
2. Infer decision type (ARCHITECTURE, SCOPE, CONSTRAINT, etc.)
3. Create Decision entity
4. Link to affected entities
5. Post for approval

### CONVERSE Mode
**Trigger:** Casual conversation, questions, clarifications
**Behavior:**
1. Respond helpfully
2. DO NOT create entities
3. DO NOT emit events (except maybe `MessageReceived` for audit)
4. Maintain context for future intent detection

---

## Entity Lifecycle State Machine

Every entity (WorkItem or Decision) follows this lifecycle:

```
                    ┌─────────────┐
                    │    DRAFT    │
                    │  (thread)   │
                    └──────┬──────┘
                           │ propose()
                           ▼
                    ┌─────────────┐
                    │  PROPOSED   │◄──────────────┐
                    │  (channel)  │               │
                    └──────┬──────┘               │
                           │                      │
              ┌────────────┼────────────┐         │
              │            │            │         │
         objection()   approval()   withdraw()    │
              │            │            │         │
              ▼            ▼            │         │
        ┌─────────┐  ┌──────────┐      │         │
        │ BLOCKED │  │ APPROVED │      │         │
        │ (needs  │  │ (ready   │      │    modify()
        │ resolve)│  │ for Jira)│      │    (reopen)
        └────┬────┘  └────┬─────┘      │         │
             │            │            │         │
        resolve()    commit()          │         │
             │            │            │         │
             └────────────┼────────────┘         │
                          ▼                      │
                   ┌─────────────┐               │
                   │  COMMITTED  │───────────────┘
                   │  (in Jira)  │
                   └──────┬──────┘
                          │ deprecate() (decisions only)
                          ▼
                   ┌─────────────┐
                   │ DEPRECATED  │
                   │ (superseded)│
                   └─────────────┘
```

### Transition Rules

| Current State | Allowed Actions | Resulting State |
|---------------|-----------------|-----------------|
| DRAFT | propose, delete | PROPOSED, (deleted) |
| PROPOSED | approve, object, withdraw, modify | APPROVED, BLOCKED, DRAFT, PROPOSED |
| BLOCKED | resolve | PROPOSED |
| APPROVED | commit, modify | COMMITTED, PROPOSED |
| COMMITTED | deprecate (decisions) | DEPRECATED |
| DEPRECATED | (none) | (terminal) |

---

## Entity Lifecycle Implementation

### Sum Types Pattern

Entities use sum types (tagged unions) to make illegal states unrepresentable. Each lifecycle state is a distinct class:

| Type | State | Key Properties |
|------|-------|----------------|
| `DraftEntity` | Being formed | thread_ts, no canonical message |
| `ProposedEntity` | Awaiting approval | canonical_message_ts, approvals[], objections[] |
| `ApprovedEntity` | Ready for Jira | attribution.approved_by set |
| `CommittedEntity` | In Jira | jira_link (required, not optional!) |
| `DeprecatedEntity` | Superseded | deprecated_at, superseded_by |

**Key insight:** A `CommittedEntity` always has a `JiraLink`. Not "maybe has" or "optionally has" — the type system guarantees it.

```python
# This is how we express "committed means has Jira link"
class CommittedEntity(BaseModel):
    jira_link: JiraLink  # Required, not Optional[JiraLink]
```

### Transition Functions

All state transitions are pure functions in `src/domain/transitions.py`:

```
propose(draft) -> proposed
add_approval(proposed, user) -> proposed (with approval)
raise_objection(proposed, user, reason) -> proposed (with objection)
resolve_objection(proposed, index, resolution) -> proposed
approve(proposed) -> approved
commit(approved, jira_key) -> committed
deprecate(committed) -> deprecated
```

Each function:
1. Takes an entity in state A
2. Returns an entity in state B
3. Raises `TransitionError` for illegal transitions

### Channel Aggregate Root

The `ChannelAggregate` coordinates all entity mutations:

```
ChannelAggregate
├── entities: dict[EntityId, Entity]
├── pending_events: list[DomainEvent]
├── version: int
│
├── draft_work_item() -> DraftEntity
├── propose_work_item() -> ProposedEntity
├── approve_work_item() -> ProposedEntity | ApprovedEntity
├── commit_work_item() -> CommittedEntity
│
├── record_decision() -> DraftEntity
├── propose_decision() -> ProposedEntity
├── approve_decision() -> ProposedEntity | ApprovedEntity
├── commit_decision() -> CommittedEntity
├── deprecate_decision() -> DeprecatedEntity
│
├── raise_entity_objection() -> ProposedEntity
├── resolve_entity_objection() -> ProposedEntity
└── withdraw_entity_objection() -> ProposedEntity
```

**Pattern:** Every mutation:
1. Validates current state
2. Applies transition function
3. Emits domain event
4. Updates local state
5. Returns new entity

### Approval/Objection Flow

```
┌────────────────────────────────────────────────────────┐
│                    PROPOSED                             │
│  ┌─────────────┐    ┌─────────────┐    ┌───────────┐  │
│  │  approvals  │    │  objections │    │  actions  │  │
│  │  ─────────  │    │  ──────────  │    │  ───────  │  │
│  │  user_id    │    │  user_id    │    │  Approve  │  │
│  │  timestamp  │    │  reason     │    │  Object   │  │
│  │  comment?   │    │  status     │    │  Discuss  │  │
│  └─────────────┘    │  resolution │    └───────────┘  │
│                     └─────────────┘                    │
└────────────────────────────────────────────────────────┘

Objection Status Flow:
  ACTIVE -> RESOLVED (by anyone, with resolution text)
  ACTIVE -> WITHDRAWN (only by original objector)

Approval Rules:
  - Cannot approve if you already approved
  - Cannot approve if there are ACTIVE objections
  - When approvals >= min_required AND no active objections -> APPROVED
```

### Mode Handler Integration

Mode handlers use the entity lifecycle:

| Mode | Entity Operations |
|------|-------------------|
| CREATE | `draft_work_item()` / `record_decision()` |
| MODIFY | Update draft/proposed content |
| RECORD | `record_decision()` |
| CONVERSE | None (no entity operations) |

The `SafetyEvaluator` checks entity state before allowing operations:

```python
# In safety.py
can_mod, reason = can_modify(entity)  # Only Draft/Proposed
can_app, reason = can_approve(entity)  # Only Proposed, no active objections
can_com, reason = can_commit(entity)   # Only Approved
```

### Event Sourcing Integration

Entity events feed into the event store:

```
User Action -> ChannelAggregate -> Domain Event -> Event Store -> Projection
                    │
                    └── Returns updated Entity
```

Events for entity lifecycle:
- `WorkItemDrafted`, `WorkItemProposed`, `WorkItemApproved`, `WorkItemCommitted`, `WorkItemUpdated`
- `DecisionRecorded`, `DecisionProposed`, `DecisionApproved`, `DecisionCommitted`, `DecisionDeprecated`
- `ApprovalAdded`, `ObjectionRaised`, `ObjectionResolved`, `ObjectionWithdrawn`

### Module Structure

```
src/domain/
├── types.py          # EntityId, ChannelId, EntityLifecycle, etc.
├── content.py        # WorkItemContent, DecisionContent, Approval, Objection
├── entities.py       # Sum types: DraftEntity, ProposedEntity, etc.
├── transitions.py    # Pure transition functions
├── channel.py        # ChannelAggregate (aggregate root)
├── events.py         # Domain events
└── __init__.py       # Exports
```

---

## Task-Based Orchestration

### Evolution from ProcessExecutor

The original spec (maro_2_0.md Part 7) defined a linear ProcessExecutor with fixed stages. After analysis, this was found too rigid for real conversations:
- Users revisit topics and decisions emerge organically
- "Create stories for each epic" requires parallelism
- Multi-user collaboration is natural in Slack

The Task-based model replaces linear stages with flexible, entity-centric workflows.

### Core Concepts

```
Conversation Thread
  └─ Workspace (channel/thread state)
       ├─ Task A: "Create login story" → Entity[WorkItem]
       ├─ Task B: "Capture API decisions" → Entity[Decision], Entity[Decision]
       └─ Task C: "Review sprint" → Entity[WorkItem]×N
```

| Concept | Purpose |
|---------|---------|
| **Workspace** | State container for a channel/thread — tracks active tasks and entities |
| **Task** | Unit of work with a goal, can spawn children, can cycle |
| **FlowTemplate** | Template/pattern for common task types (not a rigid stage machine) |
| **Orchestrator** | Routes user input to tasks, manages lifecycle, detects new intents |

### Task Lifecycle

```
         ┌─────────────────────────────────────────┐
         │              TaskStatus                  │
         │  ┌────────┐   ┌─────────┐   ┌─────────┐ │
         │  │ ACTIVE │ → │ WAITING │ → │COMPLETED│ │
         │  └────────┘   └─────────┘   └─────────┘ │
         │       │            │             ↑      │
         │       │            │             │      │
         │       ↓            ↓             │      │
         │  ┌────────┐   ┌─────────┐        │      │
         │  │BLOCKED │   │CANCELLED│        │      │
         │  └────────┘   └─────────┘        │      │
         │       │                          │      │
         │       └──────────────────────────┘      │
         └─────────────────────────────────────────┘

ACTIVE    → Working, gathering context
WAITING   → Asked question, awaiting response
BLOCKED   → Waiting on child tasks to complete
COMPLETED → Goal achieved, entities created
CANCELLED → Abandoned before completion
```

### Flow Templates

Templates guide (don't enforce) what context to gather:

| Flow | Purpose | Required | Fan-Out |
|------|---------|----------|---------|
| `create_work_item` | Single item creation | "what" | No |
| `create_decision` | Capture decision | "decision" | No |
| `architecture_review` | Multi-entity discussion | "goal" | Yes |
| `batch_create` | Parallel item creation | "targets" | Yes |
| `review` | Review existing entities | "entities" | No |

### Orchestrator Routing

```python
async def handle_message(workspace, message, user_id):
    # 1. Check for task-switch intent
    if switch := detect_task_switch(workspace, message):
        workspace.focus_task_id = switch

    # 2. Route to focus task or create new
    if workspace.focus_task_id:
        return process_task_input(task, message)
    else:
        intent = detect_intent(message)
        if intent.should_create_task:
            task = create_task(intent, workspace)
            return start_task(task)
```

### Fan-Out Pattern

For "Create stories for each epic":

```
Parent Task (batch_create, BLOCKED)
  ├─ Child Task: Story for Epic 1 (ACTIVE)
  ├─ Child Task: Story for Epic 2 (ACTIVE)
  └─ Child Task: Story for Epic 3 (ACTIVE)
        ↓ all complete
Parent Task (ACTIVE) → Aggregate → Review → Approve
```

### Integration with Entity Lifecycle

Tasks create entities through the existing ChannelAggregate:

```
Orchestrator                    ChannelAggregate
    │                                  │
    │ Task complete with context       │
    ├──────────────────────────────────→
    │                                  │ draft_work_item(content)
    │                                  │ propose_work_item(entity_id)
    │                                  │
    │ DomainEvents                     │
    ←──────────────────────────────────┤
```

### PreGates Integration

PreGates Gate 4 now checks for active workspaces:

```python
# Gate 4: Known workspace thread - route to Orchestrator
if thread_ts in active_workspace_threads:
    return PreGateOutput(result=PreGateResult.WORKSPACE)
```

### Module Structure

```
src/orchestration/
├── models.py          # Task, Workspace, Question, TaskStatus
├── flows.py           # FlowTemplate definitions
├── orchestrator.py    # Main Orchestrator class
├── actions.py         # OrchestratorAction types
├── events.py          # TaskCreated, TaskCompleted, etc.
├── projection.py      # WorkspaceProjection for read model
└── __init__.py        # Exports
```

---

## Decision-Making Rules

### When to Create an Entity

**DO create** when:
- User explicitly asks ("create a story for...")
- User describes work with enough detail (title + some description)
- User states a decision with rationale

**DON'T create** when:
- User is asking questions
- User is brainstorming (no commitment)
- Confidence < 0.7
- Similar entity already exists in Draft

### When to Auto-Approve

**Never.** All approvals require human action via button click.

### When to Sync to Jira

Only when:
1. Entity is in APPROVED state
2. User clicks "Commit to Jira" button
3. No unresolved conflicts exist

### Conflict Detection

Check before commit:
1. **Overlapping decisions** — Two decisions affecting same entity/field
2. **Jira drift** — Entity changed in Jira since last sync
3. **Superseded decisions** — Decision references deprecated decision

---

## Process Orchestration

For complex workflows (like architecture review), MARO uses multi-stage processes:

### Process Structure

```
Process
  ├── Stage 1: Gather Context
  │     └── Questions, document review
  ├── Stage 2: Analysis
  │     └── LLM analysis, pattern matching
  ├── Stage 3: Recommendations
  │     └── Generate decision drafts
  └── Stage 4: Approval
        └── User reviews, approves/rejects
```

### Process Types

| Process | Trigger | Stages | Output |
|---------|---------|--------|--------|
| `work_item_creation` | CREATE mode for work item | Extract → Refine → Propose | WorkItem entity |
| `decision_creation` | RECORD mode | Capture → Contextualize → Propose | Decision entity |
| `architecture_review` | User requests review | Gather → Analyze → Recommend → Approve | Multiple decisions |

### Plan Execution

Within a process, plans execute specific actions:

```python
Plan:
  - create_entity(type=DECISION, content={...})
  - post_message(channel, formatted_preview)
  - wait_confirmation(timeout=24h)
  - on_approved: sync_to_jira()
```

---

## Slack Integration Layer

### Message Flow

```
Slack -> POST /slack/events -> Bolt AsyncApp -> Handler -> SlackClient -> Slack
```

**Inbound Flow:**
1. Slack sends events to `/slack/events` endpoint
2. Bolt handles signature verification automatically
3. Event routed to appropriate handler:
   - `@app.event("message")` - Message events
   - `@app.event("app_mention")` - @mentions
   - `@app.action(pattern)` - Button clicks
   - `@app.command("/maro")` - Slash commands
4. Handler processes event and responds via SlackClient

**Outbound Flow:**
1. Handler calls `SlackClient.send(message_type, channel_id, content)`
2. SlackClient routes based on `WRITE_TARGETS` mapping:
   - CHANNEL: Permanent, visible to all
   - THREAD: Conversation context
   - EPHEMERAL: Only visible to one user
3. Rate limiter ensures 1 msg/sec limit respected
4. Message posted to Slack

### Handler Types

| Handler | Trigger | Response Type |
|---------|---------|---------------|
| Message | User sends message | Thread (conversation_response) |
| App Mention | @MARO in message | Thread |
| Button Action | Approve/Object/Discuss click | Thread (ack + feedback) |
| Slash Command | /maro command | Ephemeral (command_help) |

### Critical Rules

1. **ack() First**: All action/command handlers MUST call `ack()` as first line. Slack times out after 3 seconds.

2. **Check bot_id**: Message handlers MUST check `event.get("bot_id")` to avoid infinite loops.

3. **Use thread_ts**: Always respond in the correct thread using `thread_ts` from the event.

4. **Rate Limiting**: All outbound messages go through RateLimiter (1/sec).

### Message Type Routing

| Message Type | Target | Example |
|--------------|--------|---------|
| entity_proposed | CHANNEL | "New story proposed: ..." |
| entity_approved | CHANNEL | "Story approved by @user" |
| question_asked | THREAD | "What's the priority?" |
| draft_preview | THREAD | "Here's the draft..." |
| command_help | EPHEMERAL | "/maro help output" |
| error_message | EPHEMERAL | "You don't have permission" |

### Dashboard

Each channel has a pinned status dashboard showing:
- Pending approvals (count + first 5)
- Committed items in Jira (count + first 5)
- Active decisions (count)
- Last updated timestamp

Dashboard is updated when entities change lifecycle state.

---

## Intent Classification Implementation

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| LLM Abstraction | LiteLLM | Multi-provider support (Gemini, OpenAI, Anthropic, etc.) |
| Structured Output | Instructor | Pydantic validation with auto-retries |
| JSON Repair | json-repair | Fallback for malformed LLM responses |

### Classification Pipeline

```
Message arrives
    |
+---------------------------------------------+
| Stage 1: PreGates (Deterministic)           |
|   * /maro command -> COMMAND                |
|   * Button click -> ACTION                  |
|   * "lgtm", "approved" -> APPROVAL          |
|   * Bot message -> IGNORE                   |
|   * Process thread -> PROCESS               |
|   * Otherwise -> PASS_THROUGH               |
+---------------------------------------------+
    | (if PASS_THROUGH)
+---------------------------------------------+
| Stage 2: LLM Router                         |
|   * Input: message + context                |
|   * Output: IntentClassification            |
|   * Uses Instructor for structured output   |
|   * Auto-retries on validation failure      |
+---------------------------------------------+
    |
+---------------------------------------------+
| Stage 3: Confidence Thresholds              |
|   * confidence < 0.7 -> CONVERSE            |
|   * CREATE/MODIFY < 0.85 -> CONVERSE        |
|   * Otherwise -> classified mode            |
+---------------------------------------------+
    |
+---------------------------------------------+
| Stage 4: Safety Evaluator                   |
|   * Check lifecycle state                   |
|   * Check permissions                       |
|   * Determine if confirmation required      |
+---------------------------------------------+
    |
+---------------------------------------------+
| Stage 5: Mode Handler                       |
|   * CREATE -> CreateModeHandler             |
|   * MODIFY -> ModifyModeHandler             |
|   * RECORD -> RecordModeHandler             |
|   * CONVERSE -> ConverseModeHandler         |
+---------------------------------------------+
```

### Configuration

LLM settings in environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | gemini | Provider prefix for LiteLLM |
| `LLM_MODEL` | gemini-2.0-flash | Model name |
| `LLM_API_KEY` | (none) | Provider API key |
| `LLM_TEMPERATURE` | 0.1 | Lower = more deterministic |
| `LLM_MAX_RETRIES` | 2 | Retry count for validation failures |

### Confidence Thresholds

| Threshold | Value | Effect |
|-----------|-------|--------|
| Base | 0.7 | Below this, always CONVERSE |
| Side-effect | 0.85 | CREATE/MODIFY require this |

**Rationale:** Side-effect modes (CREATE, MODIFY) can cause irreversible actions. Requiring higher confidence prevents accidental entity creation or modification on ambiguous input.

### Module Structure

```
src/
+-- llm/
|   +-- client.py         # LiteLLM + Instructor wrapper
|   +-- __init__.py
+-- intent/
|   +-- schemas.py        # SuperMode, IntentClassification, etc.
|   +-- pregates.py       # Deterministic pre-routing
|   +-- router.py         # LLM-based classification
|   +-- prompts.py        # Classification prompts
|   +-- safety.py         # Safety evaluator
|   +-- __init__.py
+-- modes/
    +-- base.py           # ModeHandler base class
    +-- create.py         # CREATE mode handler
    +-- modify.py         # MODIFY mode handler
    +-- record.py         # RECORD mode handler
    +-- converse.py       # CONVERSE mode handler
    +-- dispatcher.py     # Routes intents to handlers
    +-- __init__.py
```

### Error Handling

| Error Type | Handling |
|------------|----------|
| LLM timeout | Fall back to CONVERSE |
| Validation failure | Instructor retries with error feedback |
| JSON malformed | json-repair attempts fix |
| All retries exhausted | Fall back to CONVERSE |

**Key principle:** Always fail safe to CONVERSE mode. Never take action when uncertain.

---

## Deterministic Post-Filters

The classification pipeline is now **three stages**, adding a deterministic validation layer after the LLM:

```
Message arrives
    │
┌───────────────────────────────────────────┐
│ Stage 1: PreGates (Deterministic)         │
│   Rule-based pre-routing                  │
│   (button clicks, commands, bot msgs)     │
└───────────────────┬───────────────────────┘
                    │ PASS_THROUGH
┌───────────────────┴───────────────────────┐
│ Stage 2: LLM Router                       │
│   Structured classification               │
│   (mode, confidence, entity references)   │
└───────────────────┬───────────────────────┘
                    │
┌───────────────────┴───────────────────────┐
│ Stage 3: Post-Filters (Deterministic)     │  ← NEW
│   Validate LLM output against real data   │
│   (entity existence, reference cleanup)   │
└───────────────────┬───────────────────────┘
                    │
            Final classification
```

### Why Post-Filters Exist

The LLM may hallucinate entity references. When it classifies a message as MODIFY with a `target_entity_id`, that entity must actually exist in the channel. Post-filters catch this before the mode handler acts on invalid data.

### Filter: Entity Existence Check

**Applies to:** MODIFY classifications with `target_entity_id`

```
LLM says: MODIFY entity abc-123
    │
Post-filter checks: Does abc-123 exist in this channel?
    ├── Yes → Pass through (MODIFY confirmed)
    └── No  → Downgrade to CONVERSE
              (respond helpfully, don't attempt modification)
```

**Behavior:**
1. Load the channel aggregate to get current entities
2. Check if `target_entity_id` exists
3. If entity not found: downgrade `mode` to CONVERSE, clear `target_entity_id`
4. Log the downgrade in the audit trail for debugging

### Filter: Invalid Entity Mention Cleanup

If the LLM includes entity references in `entities_mentioned` that don't exist, the post-filter removes them silently. This prevents downstream handlers from attempting lookups on nonexistent entities.

### Graceful Degradation

If the channel aggregate fails to load (database error, timeout), post-filters **pass through** without filtering. The principle is: filtering is a safety enhancement, not a hard gate. A temporary inability to validate should not block the user from getting a response.

### Source Files

- `src/intent/post_filters.py` — Post-filter pipeline and entity existence check
- `src/intent/router.py` — Integration point (post-filters applied after LLM classification)

---

## Intent Audit Logging

Every intent classification is persisted for debugging and threshold tuning. The audit trail captures the full journey: message → pregate → raw LLM output → threshold-adjusted mode → final classification.

### What Gets Logged

Each message that passes through the classification pipeline produces one audit entry:

| Field | Description |
|-------|-------------|
| `channel_id`, `thread_ts`, `message_ts` | Message location |
| `user_id`, `message_text` | Who said what |
| `pregate_result` | PreGate outcome (PASS_THROUGH, BOT_MESSAGE, COMMAND, etc.) |
| `raw_mode`, `raw_confidence` | LLM's original classification before thresholds |
| `classified_mode`, `classified_confidence` | Final mode after threshold adjustment and post-filters |
| `entity_type`, `target_entity_id` | Entity references from classification |
| `reasoning` | LLM's reasoning text |
| `classification_ms` | End-to-end classification latency |

The distinction between `raw_mode`/`raw_confidence` and `classified_mode`/`classified_confidence` is critical: it enables tuning confidence thresholds without losing the original LLM output.

### Storage

```sql
CREATE TABLE intent_audit_log (
    id              BIGSERIAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel_id      TEXT NOT NULL,
    thread_ts       TEXT,
    message_ts      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    message_text    TEXT NOT NULL,
    pregate_result  TEXT,
    pregate_data    JSONB,
    raw_mode        TEXT,
    raw_confidence  FLOAT,
    classified_mode TEXT NOT NULL,
    classified_confidence FLOAT NOT NULL,
    entity_type     TEXT,
    target_entity_id TEXT,
    entities_mentioned JSONB,
    reasoning       TEXT,
    classification_ms INTEGER,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
```

**Monthly partitions** with 90-day retention. Old partitions are dropped (not deleted row-by-row), keeping cleanup fast and efficient.

### Write Pattern

Audit writes use **fire-and-forget** with strong reference tracking:

```python
_background_tasks: set[asyncio.Task] = set()  # Prevents garbage collection

async def log_intent_audit(entry: IntentAuditEntry) -> None:
    task = asyncio.create_task(_write_audit_entry(entry))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
```

This ensures:
- Classification latency is not affected by database writes
- Tasks are not garbage collected before completion
- Failed writes log a warning but never block the user's response

### Query Patterns

```sql
-- Why did the bot do X for this message?
SELECT * FROM intent_audit_log WHERE message_ts = $1;

-- Classification distribution (last 7 days)
SELECT classified_mode, COUNT(*), AVG(classified_confidence)
FROM intent_audit_log
WHERE created_at > now() - interval '7 days'
GROUP BY classified_mode;

-- Threshold downgrades (tuning signal)
SELECT raw_mode, classified_mode, raw_confidence, reasoning
FROM intent_audit_log
WHERE raw_mode != classified_mode
ORDER BY created_at DESC LIMIT 50;
```

### Source Files

- `src/intent/audit.py` — IntentAuditEntry model and async write logic
- `src/intent/router.py` — Audit logging integration point
- `migrations/` — Table and partition creation

---

## Prompts Overview

### Intent Classification Prompt

```
You are classifying the user's intent in a Slack conversation about software development.

Context:
- Channel: {channel_name}
- Thread: {thread_summary}
- Recent messages: {messages}
- Existing entities: {entity_summaries}

Message to classify: "{message_text}"

Classify into one of:
- CREATE: User wants to define a new work item or decision
- MODIFY: User wants to change an existing entity
- RECORD: User made a decision that should be captured
- CONVERSE: Casual conversation, questions, clarifications

Output JSON:
{
  "mode": "CREATE|MODIFY|RECORD|CONVERSE",
  "confidence": 0.0-1.0,
  "entity_type": "work_item|decision|null",
  "target_entity_id": "uuid|null",
  "reasoning": "Brief explanation"
}

Rules:
- If uncertain, choose CONVERSE
- Never hallucinate entity IDs
- Consider thread context for intent
```

### Content Extraction Prompt (CREATE mode)

```
Extract structured work item content from this conversation.

Conversation:
{thread_messages}

Extract:
{
  "issue_type": "epic|story|task|bug|spike",
  "title": "Concise title (max 80 chars)",
  "description": "Detailed description",
  "acceptance_criteria": ["AC1", "AC2", ...],
  "constraints": ["Constraint1", ...]
}

Rules:
- Title should be actionable ("Add...", "Fix...", "Implement...")
- Stories require acceptance criteria
- Don't invent details not in conversation
- Mark uncertainty with [NEEDS CLARIFICATION]
```

### Decision Detection Prompt (RECORD mode)

```
Analyze if this message contains an architectural decision.

Context:
{thread_context}

Message: "{message_text}"

A decision is a CHOICE or COMMITMENT, not just information or opinion.

Output:
{
  "is_decision": true|false,
  "decision_type": "ARCHITECTURE|SCOPE|CONSTRAINT|PRIORITY|PROCESS|STRUCTURE",
  "title": "Decision title",
  "description": "What was decided",
  "rationale": "Why (from context)",
  "confidence": 0.0-1.0
}

Examples:
- "Let's use PostgreSQL" → Decision (ARCHITECTURE)
- "I think PostgreSQL might work" → NOT a decision (opinion)
- "We won't support IE11" → Decision (SCOPE/CONSTRAINT)
- "Should we support IE11?" → NOT a decision (question)
```

---

## Safety Guardrails

### What the Bot Will Never Do

1. **Create without confidence** — If confidence < 0.7, falls back to conversation
2. **Auto-approve** — All approvals require explicit human action
3. **Sync without approval** — Only APPROVED entities can go to Jira
4. **Delete without confirmation** — Destructive actions need explicit confirmation
5. **Override objections** — Objections block until resolved

### Safe Defaults

| Situation | Behavior |
|-----------|----------|
| LLM returns invalid JSON | Retry once with repair prompt, then CONVERSE |
| Unknown intent | CONVERSE mode |
| Entity not found | Report error, don't hallucinate |
| Jira sync fails | Mark CONFLICT, notify user |
| Rate limited | Back off, queue for retry |

### Audit Trail

Every action produces an event that captures:
- What happened
- Who did it
- When
- Why (correlation to triggering message)
- What changed

Events are immutable. The audit trail is complete.

---

## Structured Questions (Smart UX)

MARO's CONVERSE mode generates intelligent follow-up questions with structured options, rendered as interactive Slack buttons. This replaces free-form text questions with a guided experience that feels natural.

### How It Works

The `ConverseLLMResponse` model includes an optional `follow_up_questions` field. The LLM generates structured questions alongside its conversational response, using field descriptions as prompt guidance:

```python
# In src/modes/converse.py (extended response model)
class ConverseLLMResponse(BaseModel):
    response_text: str
    follow_up_questions: list[FollowUpQuestion] = Field(
        default_factory=list,
        description="Questions to ask the user. Use 'choice' when there are 2-4 clear options. "
                    "Use 'confirmation' for yes/no. Use 'open_ended' only when no reasonable options exist."
    )
```

### Question Types

| Type | Rendering | When to Use |
|------|-----------|-------------|
| `choice` | 2-4 buttons + "Something else" | User picks from clear options |
| `confirmation` | Yes/No buttons | Simple yes/no or confirm/deny |
| `open_ended` | No buttons (free text) | No reasonable options to predict |

### Schema

```python
class FollowUpOption(BaseModel):
    label: str = Field(description="Short button label, max 75 chars")
    description: str = Field(description="What this option means")

class FollowUpQuestion(BaseModel):
    question_text: str = Field(description="The question to ask the user")
    question_type: Literal["choice", "confirmation", "open_ended"]
    options: list[FollowUpOption] = Field(default_factory=list)
    priority: int = Field(default=0, description="Higher = ask first")
```

### Slack Rendering

Questions are rendered as Slack Block Kit actions blocks:

- **`choice`** — Each option becomes a button. A "Something else" escape hatch button is always appended.
- **`confirmation`** — Rendered as Yes / No buttons.
- **`open_ended`** — No buttons; the question text is posted as a regular message.

**Post-selection behavior:**
1. User clicks a button
2. Original message is updated via `chat.update` to show the selected option (buttons removed)
3. The user's answer is posted as a thread reply

This prevents double-clicks and provides a clear record of what was chosen.

### Slack Block Kit Constraints

| Constraint | Limit |
|------------|-------|
| Button label text | 75 characters max |
| Elements per `actions` block | 25 max |
| `value` payload per button | 255 characters max |
| Blocks per message | 50 max |

### LLM Prompt Guidance

The system prompt instructs the LLM:
- Use `question_type="choice"` when 2-4 clear options exist
- Use `question_type="confirmation"` for yes/no scenarios
- Use `question_type="open_ended"` only when no reasonable options can be predicted
- Keep option labels under 75 characters
- Place the most likely option first

**Graceful degradation:** If `follow_up_questions` is empty, the response falls back to plain text — zero change from pre-Phase 8 behavior.

### Source Files

- `src/modes/converse.py` — ConverseLLMResponse model with follow-up questions
- `src/slack/blocks/questions.py` — Slack Block Kit rendering for questions
- `src/slack/handlers/questions.py` — Button click handler for question answers

---

## Jira Projection

### Philosophy: Jira as Deployment Artifact

**"Jira is not the source of truth — it's a deployment artifact built from the source (conversation)."**

This mental model is key:
- Slack conversations are the source of truth for **content** (descriptions, acceptance criteria)
- Jira is the source of truth for **workflow** (status, assignee, sprint)
- MARO projects approved content to Jira, not the reverse

The relationship mirrors Git → CI/CD:
| Git Concept | MARO Equivalent |
|-------------|-----------------|
| Source code | Slack conversation |
| CI build | Jira issue creation |
| Deployment | Issue in board |
| Hotfix | Manual Jira edit (needs sync) |

### Field Ownership Model

Not all fields are equal. The ownership model determines who can modify what:

| Field | Owner | Meaning |
|-------|-------|---------|
| summary | SLACK_OWNED | Slack is source of truth |
| description | SLACK_OWNED | Slack is source of truth |
| acceptance_criteria | SLACK_OWNED | Slack is source of truth |
| status | JIRA_OWNED | Jira is source of truth |
| assignee | JIRA_OWNED | Jira is source of truth |
| reporter | JIRA_OWNED | Jira is source of truth |
| priority | SHARED | Both can modify, needs conflict resolution |
| labels | SHARED | Both can modify, needs conflict resolution |
| components | SHARED | Both can modify, needs conflict resolution |

**Conflict resolution rules:**
- SLACK_OWNED: If Jira differs, ask user (Jira edit may be intentional)
- JIRA_OWNED: Always defer to Jira value
- SHARED: Always ask user to choose

### Duplicate Detection (Mandatory)

**Before creating any Jira issue, MARO MUST check for duplicates.**

This is not optional. The PreflightService searches for issues with similar summaries:

```
User approves work item
    ↓
PreflightService.check_create()
    ↓ searches JQL: project = X AND summary ~ "..."
    ↓
Duplicates found?
    ├── Yes → Show user the duplicates
    │         ├── "Link to PROJ-123" (use existing)
    │         └── "Create anyway" (explicit choice)
    │
    └── No → Create new issue
```

This prevents the common problem of duplicate Jira issues from similar conversations.

### Commit Flow

When an approved entity is committed to Jira:

```
ApprovedEntity
    ↓
CommitHandler.commit_work_item()
    ├── Check for duplicates (PreflightService)
    ├── If duplicates: return for user choice
    ├── If clean: create issue (JiraSyncService)
    └── Return jira_key
    ↓
ChannelAggregate.commit_work_item(entity_id, jira_key)
    ├── Transition: Approved → Committed
    ├── Emit: WorkItemCommitted event
    └── Entity now has JiraLink (required, not optional)
    ↓
CommittedEntity (with JiraLink)
```

**Decisions are different:**
- Decisions don't create their own Jira issues
- They append to a linked work item's issue as comments
- `commit_decision(entity, target_jira_key)` adds comment to existing issue

### Sync/Reconciliation Flow

Two triggers for sync:

1. **`/maro sync`** — Bulk check all committed entities
2. **"Refresh from Jira" button** — Single entity check

```
/maro sync
    ↓
Load all CommittedEntities in channel
    ↓
ReconciliationService.check_sync_status()
    ↓
For each entity:
    ├── Fetch current Jira state
    ├── Compare fields by ownership
    └── Record discrepancies
    ↓
Build sync report
    ├── In sync: ✅ confirmation
    └── Discrepancies: Show diff + resolution buttons
        ├── "Use Jira" — Update entity to match Jira
        ├── "Keep Slack" — Push Slack values to Jira
        └── "Skip" — Leave as-is for now
```

### Rate Limiting

Jira Cloud uses points-based rate limiting (65,000 points/hour standard, enforced March 2026).

MARO handles this with:
- **Tenacity** for exponential backoff with jitter
- **Retry on 429** responses
- **Warning logs** when rate limited

```python
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    retry=retry_if_exception_type(RateLimitError),
)
async def _retry_impl(self, func, *args, **kwargs):
    # Wrap sync atlassian-python-api with asyncio.to_thread()
```

### Module Structure

```
src/jira/
├── client.py           # JiraClient - async wrapper for atlassian-python-api
├── models.py           # FieldOwnership, PreflightCheck, SyncDiscrepancy
├── preflight.py        # PreflightService - duplicate detection
├── sync_service.py     # JiraSyncService - create/update/reconcile
├── commit_handler.py   # CommitHandler - orchestrates commit flow
├── reconciliation.py   # ReconciliationService - sync status checks
└── __init__.py         # Exports

src/slack/
├── handlers/jira.py    # Jira button handlers (commit, duplicate selection)
├── commands/sync.py    # /maro sync command handler
└── blocks/sync.py      # Slack blocks for sync UI
```

### Key Types

| Type | Purpose |
|------|---------|
| `JiraKey` | Jira issue key (e.g., "PROJ-123") |
| `JiraLink` | Link to Jira with key and field_path |
| `FieldOwnership` | JIRA_OWNED, SLACK_OWNED, SHARED |
| `PreflightCheck` | Result of pre-commit check |
| `SyncDiscrepancy` | Difference between Slack and Jira |
| `CommitResult` | Result of commit operation |
| `ReconciliationReport` | Summary of sync status |

### Integration Points

| Component | Jira Integration |
|-----------|------------------|
| ChannelAggregate | `commit_work_item()`, `commit_decision()` accept JiraKey |
| CommittedEntity | Has required `jira_link: JiraLink` |
| WorkItemApproved event | Triggers commit flow |
| DecisionApproved event | Triggers decision projection |
| Slack buttons | "Commit to Jira", "Refresh from Jira" |
| /maro sync | Bulk reconciliation check |

---

## Observability Tools

The `/maro inspect` slash command provides a debug toolkit for understanding bot behavior. All output is **ephemeral** (visible only to the invoking user) to avoid cluttering channels.

### Commands

| Command | Description | Data Source |
|---------|-------------|-------------|
| `/maro inspect` | Recent classifications (last 10) | `intent_audit_log` |
| `/maro inspect thread <ts>` | Full audit trail for a specific thread | `intent_audit_log` filtered by `thread_ts` |
| `/maro inspect stats` | Classification distribution (last 7 days) | Aggregated `intent_audit_log` |
| `/maro inspect downgrades` | Recent threshold downgrades | `intent_audit_log` where `raw_mode != classified_mode` |

### Example Output

**`/maro inspect`** — Shows the 10 most recent classifications:

```
Recent Classifications:
─────────────────────
12:34 PM  "Can we add login?" → CREATE (0.91)
12:33 PM  "sounds good"       → CONVERSE (0.95)
12:31 PM  "update the title"  → MODIFY (0.87) → entity abc-123
12:30 PM  "what's the status" → CONVERSE (0.82)
```

**`/maro inspect downgrades`** — Shows where thresholds changed the LLM's classification:

```
Threshold Downgrades (last 50):
───────────────────────────────
12:31 PM  CREATE (0.72) → CONVERSE  "maybe we should add..."
12:15 PM  MODIFY (0.68) → CONVERSE  "could we change the..."
11:45 AM  CREATE (0.81) → CONVERSE  "thinking about a new..."
```

This is the primary tool for tuning confidence thresholds — if too many legitimate intents are being downgraded, thresholds may be too aggressive.

### Design Principles

1. **Ephemeral output** — Debug info never clutters the channel
2. **Read-only** — Inspect never modifies state
3. **Fast** — Queries hit indexed audit log partitions
4. **Self-service** — Any user can debug "why did the bot do that?" without admin access

### Source Files

- `src/slack/commands/inspect.py` — Command handler and subcommand routing
- `src/intent/audit.py` — Query functions for audit log data

---

## Summary

MARO thinks in terms of:

1. **Events** — What happened (immutable, append-only)
2. **Entities** — Current state (derived from events)
3. **Modes** — What to do with a message (CREATE/MODIFY/RECORD/CONVERSE)
4. **Lifecycle** — Where an entity is in its journey (Draft → Approved → Committed)
5. **Processes** — Multi-step workflows for complex actions
6. **Smart UX** — Structured questions, audit logging, and observability for a polished experience

The bot's job is to:
- Listen to conversations
- Detect when decisions are being made
- Capture them as structured entities
- Guide them through approval
- Project them to Jira

It does this while staying out of the way — facilitating consensus, not forcing it.

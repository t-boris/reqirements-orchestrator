# Phase 35: Multi-Intent Task Orchestration - Research

**Researched:** 2026-01-24
**Status:** Ready for planning

---

## Current Architecture Analysis

### 1. Intent Classification (`src/graph/intent.py`)

**Current Implementation:**
- **Single-intent detection**: LLM classifies into ONE of 14 intents
- **Pattern-first for DECISION**: Uses regex (confidence 0.9), LLM fallback for others
- **Context-aware**: Thread context enables implicit commands (Rule A4)
- **Conversation history**: Last 15 messages provided for context

**IntentResult structure:**
```python
IntentResult {
  intent: Intent (enum)
  confidence: 0.0-1.0
  persona_hint: pm|architect|security
  ticket_key, action_type, command_field, command_value
  transform_operation, decision_type_hint
  super_mode: SuperMode (5 user-facing modes)
  reasons: list[str]
}
```

**Confidence Calculation:**
- Pattern match: 0.9
- Implicit command in anchored thread: 0.85
- LLM classification: 0.5-0.8
- Default fallback: 0.5

**Gap: No multi-intent support** — always returns top-1 only.

---

### 2. Graph Execution & State (`src/graph/graph.py`, `src/graph/runner.py`)

**Graph Structure:**
```
START → intent_router → [
  ticket_flow → extraction → validation → decision → END
  review_flow → review → END
  discussion_flow → discussion → END
  jira_command_flow → jira_command → END
  ...
]
```

**AgentState contains:**
- `messages`: LangChain reducer
- `draft`: TicketDraft with evidence
- `validation_report`: Field-level issues
- `decision_result`: Action dict (ask|preview|ready_to_create|preflight_required)
- `phase`: COLLECTING → VALIDATING → AWAITING_USER → READY_TO_CREATE → CREATED
- `pending_action`: WAITING_APPROVAL, WAITING_SCOPE_CHOICE, etc.
- `channel_state`, `thread_state`: Separated persistence (Phase 25)
- `thread_context`: ThreadContext with anchor binding (Phase 33)

**Checkpointing:**
- AsyncPostgresSaver (one run per thread/session)
- Interrupt points: ASK, PREVIEW, READY_TO_CREATE
- State versioning via `state_version`

**Runner Pattern:**
- `GraphRunner.run_with_message()`: Run until interrupt, return action
- `_run_until_interrupt()`: Stream through graph, check for interrupts
- `handle_approval()`: Handle preview approve/reject
- Session locking for concurrency

---

### 3. UI/Message Update Patterns

**ProgressTracker (`src/slack/progress.py`):**
- <4s: No status message
- ≥4s: Post status with elapsed time
- On complete: Edit to "Done", delete after 1s

**Update Methods:**
- `chat.update()` used in: jira_linker, pinned_board, decision_manager, channel_work_board
- No throttling mechanism (critical gap)

**Response Posting (`src/slack/handlers/response.py`):**
- `post_response()` with transparency footer
- Builds attachment blocks dynamically

---

### 4. Thread Bindings (`src/slack/binding.py`, `src/schemas/anchor.py`)

**Binding Flow:**
- `start_binding_flow()`: Suggests epics via Zep semantic search
- `bind_epic()`: Links thread to Epic via WorkItem
- `get_workitem_for_thread()`: Finds existing binding

**ThreadContext (Phase 33):**
- Resolved anchor info (Epic, Decision, etc.)
- Enables implicit commands without explicit SCRUM-123

**WorkItem:**
- `id, channel_id, jira_key, source_thread_ts, status`
- Status: ACTIVE, COMPLETED, CANCELED

---

### 5. Decision & Approval Workflow

**Decision as First-Class Entity (Phase 30):**
- Versioned, Jira is projection
- Types: ARCH, SCOPE, CONSTRAINT, PRIORITY, STRUCTURE, PROCESS
- Status: PROPOSED → APPROVED → DEPRECATED → REPLACED

**Decision Approval Flow:**
1. User approves review → decision_approval_node
2. Freezes review_context → review_artifact
3. Returns action="decision_approval"
4. Handler posts to channel

**Deterministic Mapping:**
```
ARCH → Description.Architecture section
SCOPE → Description.Scope section
CONSTRAINT → Description.Constraints section
PRIORITY → Priority field
STRUCTURE → Parent/Epic link
PROCESS → Labels
```

---

### 6. Multi-Ticket Batch Processing (`src/graph/nodes/multi_ticket.py`)

**Flow:** Dry-run validate → Create Epic → Create linked Stories

**Safety Latches:**
- QUANTITY_THRESHOLD = 3 (>3 items need confirmation)
- SIZE_THRESHOLD = 10000 chars (large batches need confirmation)

---

## Key Gaps for Multi-Intent Support

| Gap | Current State | Needed |
|-----|---------------|--------|
| **Single-Intent** | Returns top-1 only | Return `intents: [...]` list |
| **Task Decomposition** | No model | TaskPlan with dependencies |
| **Execution Orchestration** | Linear nodes | Parallel where safe |
| **State Model** | `decision_result: dict` | `task_results: list[dict]` |
| **Throttling** | None | Max 1-2s between updates |
| **Task Targeting** | Post-classification | Per-task anchor binding |
| **History Contamination** | 15 messages context | Tasks from trigger only |

---

## Integration Points for TaskPlan

### 1. Intent Router Enhancement

**From:**
```python
IntentResult {intent, confidence, ...}
```

**To:**
```python
TaskPlanProposal {
  tasks: [Task...],
  total_confidence: float,
  low_confidence_signal: bool,
  dependencies: [[task_id, task_id], ...],
  safety_levels: {task_id: auto|confirm|blocked}
}
```

### 2. New Graph Layer

```
START → intent_router → task_decomposer → [
  For each task:
    - Resolve target (Context Binding task if needed)
    - Extract params (Stage 2)
    - Execute
] → task_coordinator → END
```

### 3. State Extension

```python
# Add to AgentState
task_plan: Optional[TaskPlan] = {
  plan_id: str,
  anchor: {channel|thread|decision_id|jira_key},
  tasks: [Task...],
  status: PENDING|RUNNING|BLOCKED|DONE|CANCELED,
  ui_message_ts: str,  # For chat.update
  version: int,
}
```

### 4. Safety Classification

Map SuperMode → Task Safety:
- BUILD, OPERATE, DECIDE → Requires confirmation
- THINK, CHAT → Auto-execute

### 5. UI Throttling

```python
class TaskStatusUpdater:
  async def update(self, plan: TaskPlan):
    # Max once per 1-2 seconds
    # OR on significant events
    await client.chat_update(
      channel=channel_id,
      ts=plan.ui_message_ts,
      blocks=blocks,
    )
```

### 6. Button Version Binding

```python
{
  "action_id": "task_approve",
  "value": f"{plan_id}:{task_id}:{task_version}"
}
```

---

## Recommended Implementation Phases

### 35.1: Intent → TaskPlan Conversion
- Enhance LLM prompt for multi-intent markers ("and", "also", "plus")
- Return `intents: [...]` list with confidence per intent
- New node: `task_proposal_router`

### 35.2: Context Binding Task
- If target not determinable → Context Binding task first
- Use ThreadContext, channel_context to resolve
- Each task gets explicit anchor

### 35.3: Two-Stage Param Extraction
- Stage 1 (cheap): Classify intents, rough task list
- Stage 2 (lazy): Extract params when task runs
- Missing params → status = BLOCKED

### 35.4: Safety Classification
- Map SuperMode → safety level
- Executor respects before running

### 35.5: Task Execution Orchestration
- Coordinated by task_executor
- Parallel where safe
- Sequential where needed

### 35.6: UI/Message Updates
- TaskStatusUpdater with throttling
- Single editable message
- Version binding for buttons

---

## Critical Insights

1. **SuperMode = UI Contract**: Users see 5 modes, TaskPlan must use SuperMode for display

2. **Atomicity via Status**: Each task has atomic status, persisted via checkpointer

3. **History as Context Only**: Tasks come from trigger message only, not conversation

4. **Throttling Critical**: Slack rate limits require batching (max 1-2s)

5. **Deterministic Mapping**: DecisionType → Jira field is hardcoded, not LLM-guessed

6. **Two-Stage Extraction**: Prevents LLM fantasy by lazy param extraction

7. **Button Versioning**: `plan_version:task_version` prevents stale clicks

---

## Key Files Reference

| Area | File | Purpose |
|------|------|---------|
| Intent | `src/graph/intent.py` | Classification logic |
| Intent | `src/schemas/intent.py` | IntentResult, SuperMode |
| Graph | `src/graph/graph.py` | Graph structure |
| Graph | `src/graph/runner.py` | Execution pattern |
| State | `src/schemas/state.py` | AgentState definition |
| UI | `src/slack/progress.py` | Progress tracking |
| Bindings | `src/slack/binding.py` | Thread binding |
| Anchor | `src/schemas/anchor.py` | ThreadContext |
| Decisions | `src/graph/nodes/decision_extraction.py` | Decision creation |
| Batch | `src/graph/nodes/multi_ticket.py` | Multi-ticket pattern |

---

*Phase: 35-multi-intent-task-orchestration*
*Researched: 2026-01-24*

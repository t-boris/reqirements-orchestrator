# Phase 5: Process Orchestration - Research

**Researched:** 2026-02-02 (Updated)
**Domain:** Task-based workflow orchestration for conversational Slack-to-Jira bot
**Confidence:** HIGH

<research_summary>
## Summary

Researched workflow orchestration approaches for a Slack bot that converts conversations into Jira artifacts. The original spec defined a **linear stage machine** (ProcessExecutor with fixed stages). After discussion, we identified this is too rigid for real conversation patterns.

**Key findings:**

1. **Real conversations are non-linear** — Users revisit topics, decisions emerge organically, "create stories for each epic" requires parallelism
2. **Entity-centric, not stage-centric** — The bot manages entities (work items, decisions) through their lifecycle, not stages through a sequence
3. **Libraries don't fit** — LangGraph/Temporal are close but would need heavy wrapping for our Slack+Entity+EventSourcing stack
4. **Custom Task model** — Purpose-built orchestration leveraging existing infrastructure (Phase 1-4)

**Primary recommendation:** Implement custom Task-based orchestration model as defined in 05-MODEL-PROPOSAL.md. Borrow patterns from LangGraph (graph with cycles) and Actor model (parallel tasks) without the dependency.

</research_summary>

<standard_stack>
## Standard Stack

### Recommended: Custom Implementation

| Component | Purpose | Why Custom |
|-----------|---------|------------|
| Task | Unit of work with goal and context | Fits our entity-centric model |
| Workspace | Channel/thread state container | Slack-specific, integrates with existing |
| Orchestrator | Routes input, manages lifecycle | LLM-based intent detection, our domain |
| FlowTemplate | Guides (not enforces) task behavior | Flexible, not rigid stages |

### What We Reuse from Prior Phases

| From Phase | Component | How Used in Phase 5 |
|------------|-----------|---------------------|
| Phase 1 | EventStore | Task events for persistence/replay |
| Phase 1 | Projection | WorkspaceProjection for read model |
| Phase 3 | LLM Client | Intent detection, question generation |
| Phase 4 | Entity lifecycle | Tasks create/modify entities |
| Phase 4 | ChannelAggregate | Entity mutations flow through aggregate |

### Libraries Considered

| Library | Stars | What It Does | Why NOT |
|---------|-------|--------------|---------|
| [LangGraph](https://github.com/langchain-ai/langgraph) | 8k+ | LLM workflow graphs | Heavy wrapper needed for Slack/Entity integration |
| [Temporal](https://temporal.io) | 12k+ | Durable workflow execution | Overkill, requires separate server |
| [Prefect](https://prefect.io) | 17k+ | Data pipeline orchestration | Wrong domain (ETL, not conversation) |
| [transitions](https://github.com/pytransitions/transitions) | 5.5k | State machine | Too rigid, no cycles, no parallelism |
| [python-statemachine](https://github.com/fgmacedo/python-statemachine) | 1.2k | State machine | Same — FSM pattern doesn't fit |
| [Pykka](https://pykka.readthedocs.io) | 1k+ | Actor framework | Could use for parallelism, but asyncio enough |

**Why custom wins:**

Our requirements are specific:
- Slack threads as conversation medium (not generic chat)
- Entity lifecycle already implemented (Phase 4)
- Event sourcing already implemented (Phase 1)
- Multi-user with attribution
- Jira as output target

A library would need heavy adaptation. Our custom model is ~300 lines of domain-specific code vs. learning + wrapping a generic framework.

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### New Model: Task-Based Orchestration

**Core insight:** Don't model "process stages" — model **tasks operating on entities**.

```
Conversation Thread
  └─ Workspace (channel/thread state)
       ├─ Task A: "Create login story" → Entity[WorkItem]
       ├─ Task B: "Capture API decisions" → Entity[Decision], Entity[Decision]
       └─ Task C: "Review sprint" → Entity[WorkItem]×N
```

### Recommended Project Structure

```
src/
├── orchestration/
│   ├── models.py          # Task, Workspace, Question, TaskStatus
│   ├── flows.py           # FlowTemplate definitions
│   ├── orchestrator.py    # Main Orchestrator class
│   ├── routing.py         # Intent detection, task switching
│   ├── execution.py       # Task execution logic
│   ├── events.py          # TaskCreated, TaskCompleted, etc.
│   ├── projection.py      # WorkspaceProjection
│   └── __init__.py
```

### Pattern 1: Task with Flexible Context

**What:** Tasks gather context toward a goal, not through fixed stages
**When to use:** All conversation flows

```python
@dataclass
class Task:
    id: str
    goal: str                           # "Create login story"
    flow_type: str                      # "create_work_item", "batch_create"
    status: TaskStatus

    # Flexible context (not stage-indexed)
    context: dict[str, Any]             # {"what": "...", "why": "...", ...}
    target_entities: list[EntityId]

    # Hierarchy for fan-out
    parent_task_id: str | None
    child_task_ids: list[str]
    blocked_by: list[str]               # Dependency tracking

    # Multi-user
    created_by: UserId
    contributors: set[UserId]
```

### Pattern 2: FlowTemplate as Guide (Not Enforcer)

**What:** Templates suggest what to gather, but don't enforce order
**When to use:** Define reusable patterns without rigidity

```python
@dataclass
class FlowTemplate:
    flow_type: str
    description: str
    suggested_context: list[str]        # What we'd like to know
    required_context: list[str]         # Minimum to complete
    allows_cycles: bool = True          # Can revisit earlier context
    allows_fan_out: bool = False        # Can spawn child tasks

FLOW_TEMPLATES = {
    "create_work_item": FlowTemplate(
        flow_type="create_work_item",
        description="Create a single work item",
        suggested_context=["what", "why", "acceptance_criteria", "priority"],
        required_context=["what"],
    ),

    "architecture_review": FlowTemplate(
        flow_type="architecture_review",
        description="Multi-entity architecture discussion",
        suggested_context=["goal", "scope", "constraints", "components"],
        required_context=["goal"],
        allows_fan_out=True,            # Can spawn decision/work_item tasks
    ),

    "batch_create": FlowTemplate(
        flow_type="batch_create",
        description="Create multiple items in parallel",
        suggested_context=["targets", "template"],
        required_context=["targets"],
        allows_fan_out=True,
        child_flow="create_work_item",
    ),
}
```

### Pattern 3: Orchestrator Routes Input

**What:** Single entry point that routes messages to appropriate tasks
**When to use:** All message handling

```python
class Orchestrator:
    async def handle_message(
        self,
        workspace: Workspace,
        message: SlackMessage
    ) -> list[OrchestratorAction]:

        # 1. Check for task-switch intent
        if switch := await self._detect_task_switch(workspace, message):
            workspace.focus_task_id = switch.task_id
            return [SwitchFocus(task_id=switch.task_id)]

        # 2. Route to focus task or create new
        if workspace.focus_task_id:
            task = workspace.tasks[workspace.focus_task_id]
            return await self._process_task_input(task, message, workspace)
        else:
            intent = await self._detect_intent(message, workspace)
            if intent.should_create_task:
                task = self._create_task(intent, workspace, message.user_id)
                return await self._start_task(task, workspace)
            else:
                return [UpdateSummary(message=message)]
```

### Pattern 4: Fan-Out for Parallel Tasks

**What:** Parent task spawns children for parallel work
**When to use:** "Create X for each Y" patterns

```python
async def _handle_batch_create(
    self,
    task: Task,
    workspace: Workspace
) -> list[OrchestratorAction]:
    actions = []

    targets = task.context.get("targets", [])
    child_flow = FLOW_TEMPLATES[task.flow_type].child_flow

    for target in targets:
        child = Task(
            id=str(uuid4()),
            goal=f"Create item for: {target}",
            flow_type=child_flow,
            status=TaskStatus.ACTIVE,
            context={"target": target},
            parent_task_id=task.id,
            created_by=task.created_by,
        )
        task.child_task_ids.append(child.id)
        workspace.tasks[child.id] = child
        actions.append(TaskSpawned(parent=task, child=child))

    # Parent waits for children
    task.status = TaskStatus.BLOCKED
    task.blocked_by = task.child_task_ids

    return actions
```

### Pattern 5: Entity Emergence Detection

**What:** Detect when user mentions something that should become an entity
**When to use:** Architecture discussions, free-form conversations

```python
async def _detect_entities(
    self,
    message: SlackMessage,
    task: Task,
    workspace: Workspace
) -> list[EntityInfo]:
    """Use LLM to detect if message contains entity-worthy content."""

    prompt = f"""Analyze this message for architectural decisions or work items.

    Message: {message.text}
    Current discussion: {task.goal}
    Context so far: {task.context}

    Output JSON list of detected entities:
    [{{
        "type": "decision" | "work_item",
        "content": "what was decided/requested",
        "confidence": 0.0-1.0
    }}]
    """

    response = await self.llm.complete(prompt)
    return [e for e in parse_entities(response) if e.confidence > 0.7]
```

### Anti-Patterns to Avoid

- **Fixed stage sequence** — Real conversations don't follow scripts
- **Blocking on single user** — Allow any contributor to advance
- **Entity creation only at end** — Capture entities as they emerge
- **No task switching** — Users should be able to say "wait, back to X"
- **Ignoring context** — Every message adds to conversation understanding

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Use Instead | Why |
|---------|-------------|-----|
| Event persistence | Phase 1 EventStore | Already built, tested, handles replay |
| Entity lifecycle | Phase 4 transitions.py | Already built, enforces valid transitions |
| LLM calls | Phase 3 LLMClient | Already built, handles retries/parsing |
| Slack messaging | Phase 2 SlackClient | Already built, handles rate limiting |
| Intent classification | Phase 3 Router | Reuse patterns, maybe extend |

**Key insight:** Phases 1-4 built significant infrastructure. Phase 5 orchestration should leverage all of it, not rebuild.

**What IS new in Phase 5:**
- Task/Workspace data models
- Orchestrator routing logic
- FlowTemplate definitions
- Fan-out/fan-in coordination
- Task-specific events and projection

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Over-Engineering the Graph
**What goes wrong:** Building a full DAG execution engine
**Why it happens:** "Tasks with dependencies" sounds like Airflow
**How to avoid:** Keep it simple — `blocked_by` list + async gather is enough
**Warning signs:** Talking about "schedulers", "executors", "DAG resolution"

### Pitfall 2: Losing Conversation Context
**What goes wrong:** Each task is isolated, loses thread context
**Why it happens:** Focusing on task state, forgetting workspace state
**How to avoid:** Workspace maintains summary + key_points across tasks
**Warning signs:** Bot asks questions already answered earlier in thread

### Pitfall 3: Rigid Flow Enforcement
**What goes wrong:** FlowTemplate becomes rigid stage machine
**Why it happens:** Old ProcessDefinition mindset
**How to avoid:** `required_context` is completion check, not stage gate
**Warning signs:** "User must answer X before Y" logic

### Pitfall 4: Ignoring Multi-User
**What goes wrong:** Task assumes single user flow
**Why it happens:** Testing with one person
**How to avoid:** Track contributors, allow anyone to advance task
**Warning signs:** `task.created_by` used for permission checks

### Pitfall 5: Entity Detection False Positives
**What goes wrong:** Bot captures every statement as decision/work item
**Why it happens:** Aggressive LLM prompting
**How to avoid:** High confidence threshold (0.7+), offer confirmation
**Warning signs:** User annoyed by constant "I captured this as a decision"

### Pitfall 6: Task Proliferation
**What goes wrong:** Workspace has 50 tasks, user is confused
**Why it happens:** Every detected entity spawns a task
**How to avoid:** Tasks for user intent, entities can be grouped under one task
**Warning signs:** "Which task should I focus on?" messages

</common_pitfalls>

<code_examples>
## Code Examples

### Task and Workspace Models

```python
# Source: 05-MODEL-PROPOSAL.md
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Any

class TaskStatus(Enum):
    ACTIVE = "active"
    WAITING = "waiting"      # Asked question
    BLOCKED = "blocked"      # Waiting on children/dependencies
    COMPLETED = "completed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    id: str
    goal: str
    flow_type: str
    status: TaskStatus
    context: dict[str, Any] = field(default_factory=dict)
    target_entities: list[str] = field(default_factory=list)
    pending_question: "Question | None" = None
    parent_task_id: str | None = None
    child_task_ids: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    created_by: str = ""
    contributors: set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Workspace:
    channel_id: str
    thread_ts: str | None
    tasks: dict[str, Task] = field(default_factory=dict)
    focus_task_id: str | None = None
    draft_entities: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
```

### Orchestrator Main Loop

```python
# Source: 05-MODEL-PROPOSAL.md pattern
class Orchestrator:
    def __init__(self, llm: LLMClient, slack: SlackClient):
        self.llm = llm
        self.slack = slack

    async def handle_message(
        self,
        workspace: Workspace,
        message: SlackMessage
    ) -> list[OrchestratorAction]:
        actions = []

        # Check for explicit commands first
        if cmd := self._parse_command(message):
            return await self._handle_command(workspace, cmd, message)

        # Check for task switch ("let's go back to...", "what about...")
        if switch := await self._detect_task_switch(workspace, message):
            workspace.focus_task_id = switch.task_id
            actions.append(SwitchFocus(task_id=switch.task_id))

        # Route to current task or create new
        if workspace.focus_task_id:
            task = workspace.tasks[workspace.focus_task_id]
            task_actions = await self._process_task_input(task, message, workspace)
            actions.extend(task_actions)
        else:
            intent = await self._detect_intent(message, workspace)
            if intent.should_create_task:
                task = self._create_task_from_intent(intent, workspace, message)
                actions.extend(await self._start_task(task, workspace))

        # Always update workspace summary
        workspace.summary = await self._update_summary(workspace, message)

        return actions
```

### Completion Check (Flexible, Not Stage-Based)

```python
# Source: Adapted from spec's _stage_complete
def can_complete(task: Task, flow: FlowTemplate) -> bool:
    """Check if task has minimum required context."""
    return all(
        key in task.context and task.context[key]
        for key in flow.required_context
    )

def missing_context(task: Task, flow: FlowTemplate) -> list[str]:
    """What's still needed to complete."""
    return [
        key for key in flow.required_context
        if key not in task.context or not task.context[key]
    ]

def suggested_next(task: Task, flow: FlowTemplate) -> list[str]:
    """What we'd like to gather next (not required)."""
    return [
        key for key in flow.suggested_context
        if key not in task.context
    ]
```

### Fan-Out Completion Handler

```python
async def _check_children_complete(
    self,
    parent_task: Task,
    workspace: Workspace
) -> list[OrchestratorAction]:
    """Check if all children complete, unblock parent."""
    actions = []

    all_complete = all(
        workspace.tasks[child_id].status == TaskStatus.COMPLETED
        for child_id in parent_task.child_task_ids
    )

    if all_complete:
        # Aggregate results from children
        for child_id in parent_task.child_task_ids:
            child = workspace.tasks[child_id]
            parent_task.target_entities.extend(child.target_entities)

        # Unblock parent
        parent_task.status = TaskStatus.ACTIVE
        parent_task.blocked_by = []

        # Offer completion
        actions.append(OfferCompletion(
            task=parent_task,
            message=f"Created {len(parent_task.target_entities)} items. Review?"
        ))

    return actions
```

</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Linear stage machines | Flexible task graphs | Matches real conversation patterns |
| Single-user flows | Multi-contributor tasks | Team collaboration native |
| Entity at completion | Entity emergence | Captures decisions as they happen |
| Rigid FSM libraries | Purpose-built orchestration | Domain-specific, simpler |

**Relevant patterns from LLM frameworks:**
- **LangGraph** — Graph with cycles, state persistence → we implement similar with Task + blocked_by
- **CrewAI** — Agent delegation → we implement with parent/child tasks
- **AutoGen** — Multi-agent conversation → we implement with multi-user contributors

**What we borrow without the library:**
- Graph execution with cycles (not forced linear)
- State checkpointing (via event sourcing)
- Parallel task execution (via asyncio + child tasks)

**Deprecated patterns:**
- **Fixed stage sequences** — Too rigid for conversation
- **Blocking single-user flows** — Collaboration is normal
- **FSM for conversation** — Wrong abstraction level

</sota_updates>

<open_questions>
## Open Questions

1. **Sub-threads vs. Sequential Questions for Parallel Tasks**
   - What we know: Slack supports threaded replies, could use for parallel task conversations
   - What's unclear: UX implications, whether users find sub-threads confusing
   - Recommendation: Start with sequential questions in main thread, add sub-threads if needed

2. **Task Persistence Granularity**
   - What we know: Could event-source every task state change
   - What's unclear: Is that overkill? Could just persist workspace snapshots
   - Recommendation: Event-source task creation/completion, snapshot context periodically

3. **Entity Emergence Confirmation UX**
   - What we know: Don't want false positives annoying users
   - What's unclear: Best way to confirm without interrupting flow
   - Recommendation: Batch confirmations, show at natural pauses ("I noticed these decisions...")

4. **Focus Task Auto-Selection**
   - What we know: Need to route messages to "current" task
   - What's unclear: What if multiple tasks are active?
   - Recommendation: Explicit focus_task_id, LLM-based detection for implicit switches

</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- 05-MODEL-PROPOSAL.md — New task-based model design
- 05-CONTEXT.md — User requirements (follow spec direction, update docs)
- docs/maro_2_0.md Part 7 — Original spec (used as starting point, then evolved)
- Phase 1-4 implementations — Existing infrastructure to leverage

### Secondary (MEDIUM confidence)
- LangGraph conceptual model — Graph with cycles pattern
- Actor model principles — Parallel task execution pattern
- Dialog management research — Conversation state tracking

### Tertiary (LOW confidence - for reference)
- Temporal workflow patterns — Durable execution concepts
- CrewAI delegation patterns — Task hierarchy concepts

</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Python async orchestration for Slack bot
- Ecosystem: Leveraging Phase 1-4 (EventStore, LLM, Slack, Entities)
- Patterns: Task graphs, fan-out, entity emergence, conversation routing
- Pitfalls: Over-engineering, lost context, rigid flows, multi-user issues

**Confidence breakdown:**
- Architecture model: HIGH — Designed through discussion, fits domain
- Library decision: HIGH — Clear reasoning for custom approach
- Patterns: HIGH — Derived from established concepts
- Pitfalls: MEDIUM — Anticipated, not yet validated in practice

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days — patterns are stable)
</metadata>

---

*Phase: 05-process-orchestration*
*Research completed: 2026-02-02*
*Model: Task-based orchestration (supersedes spec's linear ProcessExecutor)*
*Ready for planning: yes*

# Process Orchestration: Flexible Model Proposal

**Date:** 2026-02-02
**Status:** Draft for discussion

## Problem with Current Spec

The spec's ProcessDefinition is a **linear questionnaire**:
```
Stage 1 → Stage 2 → Stage 3 → Stage 4 → Plan
```

Real conversations are **non-linear and entity-centric**:
- Multiple entities emerge organically
- Users revisit and refine earlier decisions
- "Create stories for each epic" = parallel tracks
- Team members contribute asynchronously

## Proposed Model: Task-Based Orchestration

### Core Insight

Don't model "processes with stages" — model **tasks operating on entities**.

```
Conversation
  └─ Workspace (channel/thread state)
       ├─ Task A: "Create login story" → Entity[WorkItem]
       ├─ Task B: "Capture API decisions" → Entity[Decision], Entity[Decision]
       └─ Task C: "Review sprint backlog" → Entity[WorkItem]×N
```

### Key Concepts

| Concept | Purpose |
|---------|---------|
| **Workspace** | State container for a channel/thread — tracks active tasks and entities |
| **Task** | A unit of work with a goal, can spawn children, can cycle |
| **Flow** | A template/pattern for common task types (not a rigid stage machine) |
| **Orchestrator** | Routes user input to tasks, manages lifecycle, detects new intents |

### Data Model

```python
class TaskStatus(Enum):
    ACTIVE = "active"        # Currently being worked on
    WAITING = "waiting"      # Asked question, awaiting response
    BLOCKED = "blocked"      # Waiting on dependency
    COMPLETED = "completed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    id: str
    goal: str                           # "Create login story", "Architecture review for payments"
    flow_type: str                      # Template: "create_item", "review", "batch", "discuss"
    status: TaskStatus

    # What's being worked on
    target_entities: list[EntityId]     # Entities this task creates/modifies

    # Conversation state
    context: dict[str, Any]             # Accumulated info (like stage_state.gathered_info)
    pending_question: Question | None   # Current question awaiting answer

    # Hierarchy & dependencies
    parent_task_id: str | None          # For sub-tasks (batch children)
    child_task_ids: list[str]           # For fan-out
    blocked_by: list[str]               # Tasks that must complete first

    # Tracking
    created_by: UserId
    contributors: set[UserId]           # All users who contributed
    created_at: datetime
    updated_at: datetime

@dataclass
class Workspace:
    """State for a channel or thread."""
    channel_id: ChannelId
    thread_ts: ThreadTs | None

    # Active work
    tasks: dict[str, Task]
    focus_task_id: str | None           # Currently active task (for routing)

    # Entities being formed
    draft_entities: dict[EntityId, Entity]

    # Conversation context (LLM can use this)
    summary: str                         # Running summary of discussion
    key_points: list[str]               # Important facts mentioned

@dataclass
class Question:
    """A question posed to the user."""
    id: str
    text: str
    question_type: QuestionType         # OPEN, CHOICE, CONFIRM, MULTI_SELECT
    options: list[str] | None           # For CHOICE/MULTI_SELECT
    context_key: str                    # Where to store the answer in task.context
    task_id: str                        # Which task this belongs to
```

### Flow Templates

Flows are **guides, not rigid machines**. They suggest what info to gather but adapt to conversation.

```python
@dataclass
class FlowTemplate:
    flow_type: str
    description: str
    suggested_context: list[str]        # Keys we'd like to gather (not required stages)
    required_context: list[str]         # Must have before completing
    allows_cycles: bool = True          # Can revisit earlier context
    allows_fan_out: bool = False        # Can spawn child tasks
    child_flow: str | None = None       # Flow type for children

FLOW_TEMPLATES = {
    "create_work_item": FlowTemplate(
        flow_type="create_work_item",
        description="Create a single work item",
        suggested_context=["what", "why", "acceptance_criteria", "priority"],
        required_context=["what"],      # Minimum: know what to build
    ),

    "create_decision": FlowTemplate(
        flow_type="create_decision",
        description="Capture an architectural decision",
        suggested_context=["decision", "rationale", "alternatives", "consequences"],
        required_context=["decision"],
    ),

    "architecture_review": FlowTemplate(
        flow_type="architecture_review",
        description="Multi-entity architecture discussion",
        suggested_context=["goal", "scope", "constraints", "components"],
        required_context=["goal"],
        allows_cycles=True,
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

    "review": FlowTemplate(
        flow_type="review",
        description="Review and refine existing entities",
        suggested_context=["entities", "feedback"],
        required_context=["entities"],
        allows_cycles=True,
    ),
}
```

### Orchestrator Logic

```python
class Orchestrator:
    """Routes messages and manages task lifecycle."""

    async def handle_message(
        self,
        workspace: Workspace,
        message: SlackMessage
    ) -> list[OrchestratorAction]:
        """
        Main entry point for all messages in a workspace.

        Returns actions: ASK_QUESTION, CREATE_ENTITY, UPDATE_ENTITY,
                        SPAWN_TASK, COMPLETE_TASK, POST_MESSAGE
        """
        actions = []

        # 1. Check for explicit commands (shortcuts)
        if cmd := self._detect_command(message):
            return await self._handle_command(workspace, cmd)

        # 2. Check for task-switch intent ("let's go back to...", "what about...")
        if switch := await self._detect_task_switch(workspace, message):
            workspace.focus_task_id = switch.task_id
            actions.append(SwitchFocus(task_id=switch.task_id))

        # 3. Route to focus task (or detect new task)
        if workspace.focus_task_id:
            task = workspace.tasks[workspace.focus_task_id]
            task_actions = await self._process_task_input(task, message, workspace)
            actions.extend(task_actions)
        else:
            # No active task — detect intent and maybe create one
            intent = await self._detect_intent(message, workspace)
            if intent.should_create_task:
                task = self._create_task(intent, workspace, message.user_id)
                workspace.tasks[task.id] = task
                workspace.focus_task_id = task.id
                actions.append(TaskCreated(task=task))

                # Start the task
                task_actions = await self._start_task(task, workspace)
                actions.extend(task_actions)
            else:
                # Just conversation, update summary
                actions.append(UpdateSummary(message=message))

        return actions

    async def _process_task_input(
        self,
        task: Task,
        message: SlackMessage,
        workspace: Workspace
    ) -> list[OrchestratorAction]:
        """Process input for an active task."""
        actions = []
        flow = FLOW_TEMPLATES[task.flow_type]

        # Extract info from message using LLM
        extracted = await self._extract_context(message, task, flow)
        task.context.update(extracted)
        task.contributors.add(message.user_id)
        task.updated_at = datetime.utcnow()

        # Check for entity emergence (user mentioned something that should be captured)
        if entities := await self._detect_entities(message, task, workspace):
            for entity_info in entities:
                if flow.allows_fan_out:
                    # Spawn child task for this entity
                    child = self._spawn_child_task(task, entity_info, workspace)
                    actions.append(TaskSpawned(parent=task, child=child))
                else:
                    # Add to current task's targets
                    entity = self._create_draft_entity(entity_info, workspace)
                    task.target_entities.append(entity.id)
                    actions.append(EntityDrafted(entity=entity))

        # Check if task can complete
        if self._can_complete(task, flow):
            actions.append(OfferCompletion(task=task))
        else:
            # Generate follow-up question
            question = await self._generate_question(task, flow, workspace)
            if question:
                task.pending_question = question
                task.status = TaskStatus.WAITING
                actions.append(AskQuestion(question=question))

        return actions

    def _can_complete(self, task: Task, flow: FlowTemplate) -> bool:
        """Check if task has enough context to complete."""
        return all(key in task.context for key in flow.required_context)

    async def _detect_task_switch(
        self,
        workspace: Workspace,
        message: SlackMessage
    ) -> TaskSwitch | None:
        """Detect if user wants to switch to a different task/entity."""
        # LLM-based: "let's go back to the API decision"
        # "what about the login story?"
        # "actually, for the first epic..."
        ...
```

### Example Flows

#### 1. Simple: "Create a login story"

```
User: Create a story for user login
  ↓
Orchestrator: Detects CREATE intent, spawns Task(flow="create_work_item")
  ↓
Task: context={}, needs ["what"]
  ↓
Question: "What should the login feature do?"
  ↓
User: Users should be able to log in with email/password
  ↓
Task: context={what: "login with email/password"}, required met
  ↓
Offer: "Ready to create? [Preview] [Add details] [Create]"
  ↓
User: [Create]
  ↓
Entity: DraftEntity → ProposedEntity (existing lifecycle)
```

#### 2. Parallel: "Create stories for each epic"

```
User: Create user stories for each of these epics: Auth, Payments, Reports
  ↓
Orchestrator: Detects BATCH intent, spawns Task(flow="batch_create")
  ↓
Task: context={targets: ["Auth", "Payments", "Reports"]}
  ↓
Fan-out: Spawn 3 child tasks (flow="create_work_item" each)
  ↓
Parallel questioning (could be sequential in thread or use sub-threads):
  - "For Auth epic: what stories do you need?"
  - "For Payments epic: what stories do you need?"
  - "For Reports epic: what stories do you need?"
  ↓
Children complete → Parent aggregates
  ↓
Offer: "Created 3 stories. [Review all] [Approve all] [Edit]"
```

#### 3. Emergent: Architecture Discussion

```
User: Let's discuss the new payment system architecture
  ↓
Orchestrator: Spawns Task(flow="architecture_review")
  ↓
Question: "What's the main goal for this payment system?"
  ↓
User: We need to support multiple payment providers and handle retries
  ↓
Task: context={goal: "multi-provider payments with retry"}
  ↓
Question: "What providers are you considering?"
  ↓
User: Stripe primarily, but we might add PayPal.
      DECISION: We'll use a provider abstraction layer.
  ↓
Orchestrator: Detects decision entity!
  → Spawns child Task(flow="create_decision") for abstraction layer decision
  → Child captures: decision="Provider abstraction layer", rationale="support multiple providers"
  ↓
Question: "How should retry logic work?"
  ↓
User: Exponential backoff. Oh wait, let's revisit the provider decision -
      should we also support crypto?
  ↓
Orchestrator: Detects task-switch to decision task
  → Switches focus, allows refinement
  ↓
... (conversation continues, cycling between topics)
  ↓
User: I think we're done, let's wrap up
  ↓
Orchestrator: Shows summary of all captured entities (2 decisions, 5 work items)
  ↓
Offer: [Propose all] [Edit] [Add more]
```

#### 4. Multi-user

```
Alice: We need a caching layer for the API
  ↓
Task created, Alice is creator
  ↓
Question: "What should be cached?"
  ↓
Bob: User profiles and product listings should definitely be cached
  ↓
Task: contributors={Alice, Bob}, context updated
  ↓
Carol: I think we should use Redis
  ↓
Task: contributors={Alice, Bob, Carol}
Orchestrator: Detects decision! Spawns decision task
  ↓
...
  ↓
Propose: Shows Alice as requester, Bob/Carol as contributors
Approval: May require multiple approvers based on policy
```

## Comparison with Spec

| Aspect | Spec's Process | Proposed Task Model |
|--------|----------------|---------------------|
| Structure | Fixed stage sequence | Flexible goal + context gathering |
| Progression | Linear (stage_index++) | Graph with cycles allowed |
| Parallelism | None | Native (child tasks) |
| Entity creation | After process completes | During conversation (emergent) |
| Multi-entity | One process = one output type | One task can spawn many entities |
| User control | Answer questions until done | Can switch focus, revisit, wrap up anytime |
| Multi-user | Single actor | Contributors tracked |

## What We Keep from Spec

1. **Entity lifecycle** (Phase 4) — Draft → Proposed → Approved → Committed
2. **Plan/PlanItem** — Still useful for executing approved batches
3. **LLM question generation** — Core capability
4. **Event sourcing** — Tasks emit events too

## What Changes

1. **ProcessDefinition** → **FlowTemplate** (guides, not rigid)
2. **Process** → **Task** (more flexible state)
3. **ProcessExecutor** → **Orchestrator** (routes + manages multiple tasks)
4. **StageState** → **task.context** (flat dict, not stage-indexed)

## Open Questions

1. **Sub-threads vs sequential?** For parallel tasks, use Slack sub-threads or interleave questions?
2. **Task persistence?** Event-source tasks or just workspace state?
3. **How much LLM?** Every message through LLM, or rule-based shortcuts?
4. **Approval granularity?** Per-entity or batch?

## Next Steps

If this direction is approved:
1. Update 05-RESEARCH.md with new patterns
2. Plan phase with this model
3. Implement incrementally (simple flows first, then parallel)

---

*Proposal for discussion — not final design*

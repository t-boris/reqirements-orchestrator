"""Orchestrator - main entry point for message routing and task management.

The Orchestrator is the single entry point for all message handling
in a workspace. It:
- Routes messages to the current focus task
- Detects when to create new tasks
- Detects task-switch intent ("let's go back to...")
- Manages fan-out (parent/child tasks)
- Tracks workspace state

It returns actions (not mutating external state directly) - the caller
executes those actions (posting messages, updating Slack, etc.).

Ref: .planning/phases/05-process-orchestration/05-MODEL-PROPOSAL.md
"""

import logging
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from src.orchestration.models import Task, TaskStatus, Workspace, Question, QuestionType
from src.orchestration.flows import (
    FlowTemplate,
    FLOW_TEMPLATES,
    get_flow_template,
    can_complete,
    missing_context,
    suggested_next,
)
from src.orchestration.actions import (
    OrchestratorAction,
    AskQuestion,
    PostMessage,
    TaskCreated,
    TaskSpawned,
    TaskCompleted as TaskCompletedAction,
    SwitchFocus,
    OfferCompletion,
    EntityDetected,
    UpdateSummary,
)

logger = logging.getLogger(__name__)


class LLMClientProtocol(Protocol):
    """Protocol for LLM client dependency.

    This allows the Orchestrator to accept any LLM client that provides
    structured completion. Currently methods use simplified pattern matching,
    but can be enhanced to use actual LLM calls.
    """

    async def structured_completion(
        self,
        response_model: type,
        messages: list[dict],
        **kwargs: Any,
    ) -> Any: ...


class Orchestrator:
    """Routes messages to Tasks, manages Task lifecycle.

    The Orchestrator is the single entry point for all message handling
    in a workspace. It:
    - Routes messages to the current focus task
    - Detects when to create new tasks
    - Detects task-switch intent ("let's go back to...")
    - Manages fan-out (parent/child tasks)
    - Tracks workspace state
    """

    def __init__(self, llm: LLMClientProtocol | None = None):
        self.llm = llm

    async def handle_message(
        self,
        workspace: Workspace,
        message_text: str,
        user_id: str,
    ) -> list[OrchestratorAction]:
        """Main entry point - route message and return actions.

        Args:
            workspace: Current workspace state
            message_text: User's message
            user_id: ID of the user sending message

        Returns:
            List of actions to execute (post message, ask question, etc.)
        """
        actions: list[OrchestratorAction] = []

        # 1. Check for task-switch intent ("let's go back to...", "what about...")
        switch = await self._detect_task_switch(workspace, message_text)
        if switch:
            old_focus = workspace.focus_task_id
            workspace.focus_task_id = switch
            actions.append(SwitchFocus(from_task_id=old_focus, to_task_id=switch))
            # Continue to process message with new focus

        # 2. Route to focus task or detect new task
        if workspace.focus_task_id:
            task = workspace.tasks.get(workspace.focus_task_id)
            if task:
                task_actions = await self._process_task_input(
                    task, message_text, user_id, workspace
                )
                actions.extend(task_actions)
        else:
            # No active task - detect intent and maybe create one
            intent = await self._detect_intent(message_text, workspace)
            if intent.get("should_create_task"):
                task = self._create_task(
                    goal=intent.get("goal", message_text),
                    flow_type=intent.get("flow_type", "converse"),
                    user_id=user_id,
                    workspace=workspace,
                )
                actions.append(TaskCreated(task=task))
                # Start the task
                start_actions = await self._start_task(task, workspace)
                actions.extend(start_actions)
            else:
                # Just conversation - update summary
                actions.append(UpdateSummary(
                    summary=message_text[:200],  # Simplified
                    key_points=[]
                ))

        return actions

    def _create_task(
        self,
        goal: str,
        flow_type: str,
        user_id: str,
        workspace: Workspace,
        parent_task_id: str | None = None,
    ) -> Task:
        """Create a new task and add to workspace."""
        task = Task(
            id=str(uuid4()),
            goal=goal,
            flow_type=flow_type,
            status=TaskStatus.ACTIVE,
            created_by=user_id,
            contributors={user_id},
            parent_task_id=parent_task_id,
        )
        workspace.tasks[task.id] = task
        workspace.focus_task_id = task.id
        return task

    async def _start_task(
        self,
        task: Task,
        workspace: Workspace,
    ) -> list[OrchestratorAction]:
        """Start a task - generate initial question."""
        actions: list[OrchestratorAction] = []
        flow = get_flow_template(task.flow_type)

        # Generate first question
        question = await self._generate_question(task, flow, workspace)
        if question:
            task.pending_question = question
            task.status = TaskStatus.WAITING
            actions.append(AskQuestion(question=question))
        else:
            # No question needed - maybe already complete
            if can_complete(task.context, flow):
                actions.append(OfferCompletion(
                    task=task,
                    message="Ready to create. Proceed?"
                ))

        return actions

    async def _process_task_input(
        self,
        task: Task,
        message_text: str,
        user_id: str,
        workspace: Workspace,
    ) -> list[OrchestratorAction]:
        """Process input for an active task."""
        actions: list[OrchestratorAction] = []
        flow = get_flow_template(task.flow_type)

        # Track contributor
        task.contributors.add(user_id)
        task.updated_at = datetime.utcnow()

        # Extract context from message
        if task.pending_question:
            # Answer to specific question
            task.context[task.pending_question.context_key] = message_text
            task.pending_question = None
        else:
            # Free-form input - extract what we can
            extracted = await self._extract_context(message_text, task, flow)
            task.context.update(extracted)

        # Check for entity emergence (decisions/work items mentioned)
        if flow.allows_fan_out:
            entities = await self._detect_entities(message_text, task, workspace)
            for entity in entities:
                actions.append(EntityDetected(
                    entity_type=entity["type"],
                    content=entity["content"],
                    confidence=entity["confidence"],
                ))

        # Check if task can complete
        if can_complete(task.context, flow):
            actions.append(OfferCompletion(
                task=task,
                message=f"I have enough info. Ready to create {flow.entity_type or 'item'}?"
            ))
        else:
            # Generate follow-up question
            question = await self._generate_question(task, flow, workspace)
            if question:
                task.pending_question = question
                task.status = TaskStatus.WAITING
                actions.append(AskQuestion(question=question))

        return actions

    async def _detect_intent(
        self,
        message_text: str,
        workspace: Workspace,
    ) -> dict[str, Any]:
        """Detect user intent from message."""
        # Simplified - in production, use LLM
        message_lower = message_text.lower()

        # Pattern matching for common intents
        if any(kw in message_lower for kw in ["create", "add", "new"]):
            if any(kw in message_lower for kw in ["story", "task", "epic", "bug"]):
                return {
                    "should_create_task": True,
                    "flow_type": "create_work_item",
                    "goal": message_text,
                }
            if "decision" in message_lower:
                return {
                    "should_create_task": True,
                    "flow_type": "create_decision",
                    "goal": message_text,
                }

        if "for each" in message_lower or "batch" in message_lower:
            return {
                "should_create_task": True,
                "flow_type": "batch_create",
                "goal": message_text,
            }

        if any(kw in message_lower for kw in ["review", "discuss", "architecture"]):
            return {
                "should_create_task": True,
                "flow_type": "architecture_review",
                "goal": message_text,
            }

        # Default: just conversation
        return {"should_create_task": False}

    async def _detect_task_switch(
        self,
        workspace: Workspace,
        message_text: str,
    ) -> str | None:
        """Detect if user wants to switch to a different task."""
        message_lower = message_text.lower()

        # Simple patterns for task switching
        switch_patterns = ["go back to", "what about", "actually,", "let's focus on"]

        if any(pattern in message_lower for pattern in switch_patterns):
            # Look for task mention in message
            for task_id, task in workspace.tasks.items():
                if task_id != workspace.focus_task_id:
                    # Check if task goal words appear in message
                    goal_words = task.goal.lower().split()
                    if any(word in message_lower for word in goal_words if len(word) > 3):
                        return task_id

        return None

    async def _generate_question(
        self,
        task: Task,
        flow: FlowTemplate,
        workspace: Workspace,
    ) -> Question | None:
        """Generate next question for task."""
        missing = missing_context(task.context, flow)

        if not missing:
            # Check suggested context
            suggested = suggested_next(task.context, flow)
            if not suggested:
                return None
            context_key = suggested[0]
        else:
            context_key = missing[0]

        # Generate question text based on context key
        question_texts = {
            "what": "What would you like to create?",
            "why": "Why is this needed? What problem does it solve?",
            "acceptance_criteria": "What are the acceptance criteria?",
            "priority": "What's the priority? (high, medium, low)",
            "estimate": "Any size estimate? (small, medium, large)",
            "decision": "What is the decision?",
            "rationale": "What's the rationale for this decision?",
            "alternatives": "What alternatives were considered?",
            "consequences": "What are the consequences of this decision?",
            "goal": "What's the goal of this review?",
            "scope": "What's in scope and what's out of scope?",
            "constraints": "Are there any constraints to consider?",
            "targets": "What items should I create? List them.",
        }

        text = question_texts.get(context_key, f"Tell me about {context_key}?")

        return Question(
            id=str(uuid4()),
            text=text,
            question_type=QuestionType.OPEN,
            context_key=context_key,
            task_id=task.id,
        )

    async def _extract_context(
        self,
        message_text: str,
        task: Task,
        flow: FlowTemplate,
    ) -> dict[str, Any]:
        """Extract context from free-form message."""
        # Simplified - in production, use LLM
        extracted = {}

        # For create_work_item, the message itself might be the "what"
        if flow.flow_type == "create_work_item" and "what" not in task.context:
            extracted["what"] = message_text

        # For create_decision, the message might be the decision
        if flow.flow_type == "create_decision" and "decision" not in task.context:
            extracted["decision"] = message_text

        return extracted

    async def _detect_entities(
        self,
        message_text: str,
        task: Task,
        workspace: Workspace,
    ) -> list[dict[str, Any]]:
        """Detect entities (decisions, work items) mentioned in message."""
        # Simplified - in production, use LLM
        entities = []

        message_lower = message_text.lower()

        # Look for decision markers
        decision_markers = ["decision:", "we decided", "let's go with", "we'll use"]
        for marker in decision_markers:
            if marker in message_lower:
                idx = message_lower.find(marker)
                content = message_text[idx:idx + 100]
                entities.append({
                    "type": "decision",
                    "content": content,
                    "confidence": 0.7,
                })
                break

        return entities

    def complete_task(
        self,
        task: Task,
        workspace: Workspace,
    ) -> list[OrchestratorAction]:
        """Mark task as completed."""
        task.status = TaskStatus.COMPLETED
        task.updated_at = datetime.utcnow()

        # If has parent, check if parent can unblock
        actions: list[OrchestratorAction] = []
        if task.parent_task_id:
            parent = workspace.tasks.get(task.parent_task_id)
            if parent and parent.status == TaskStatus.BLOCKED:
                # Check if all children complete
                all_complete = all(
                    workspace.tasks[child_id].status == TaskStatus.COMPLETED
                    for child_id in parent.child_task_ids
                    if child_id in workspace.tasks
                )
                if all_complete:
                    parent.status = TaskStatus.ACTIVE
                    parent.blocked_by = []
                    # Aggregate child entities
                    for child_id in parent.child_task_ids:
                        child = workspace.tasks.get(child_id)
                        if child:
                            parent.target_entities.extend(child.target_entities)
                    actions.append(OfferCompletion(
                        task=parent,
                        message=f"All {len(parent.child_task_ids)} items created. Review?"
                    ))

        return actions

    def spawn_child_tasks(
        self,
        parent_task: Task,
        targets: list[str],
        user_id: str,
        workspace: Workspace,
    ) -> list[OrchestratorAction]:
        """Spawn child tasks for batch operations."""
        actions: list[OrchestratorAction] = []
        flow = get_flow_template(parent_task.flow_type)
        child_flow_type = flow.child_flow or "create_work_item"

        for target in targets:
            child = self._create_task(
                goal=f"Create for: {target}",
                flow_type=child_flow_type,
                user_id=user_id,
                workspace=workspace,
                parent_task_id=parent_task.id,
            )
            child.context["target"] = target
            parent_task.child_task_ids.append(child.id)
            actions.append(TaskSpawned(parent_task_id=parent_task.id, child_task=child))

        # Block parent until children complete
        parent_task.status = TaskStatus.BLOCKED
        parent_task.blocked_by = parent_task.child_task_ids.copy()

        return actions

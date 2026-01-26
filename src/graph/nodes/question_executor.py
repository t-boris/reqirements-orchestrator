"""Question executor node for TaskPlan orchestration.

Handles execution of question tasks:
1. Check budget - if exhausted, trigger partial preview
2. Generate question using QuestionCatalog
3. Post question to Slack
4. Set task to BLOCKED awaiting answer
"""

import logging
from datetime import datetime, timezone
from typing import Any

from src.db.connection import get_connection
from src.db.conversation_mode_store import ConversationModeStore
from src.questions.budget_tracker import BudgetTracker
from src.schemas.conversation_mode import ConversationMode, ModeTransitionReason
from src.schemas.question import QuestionStatus
from src.schemas.state import AgentState
from src.schemas.task_plan import Task, TaskPlan, TaskPlanStatus, TaskStatus

logger = logging.getLogger(__name__)


async def question_executor_node(
    state: AgentState,
    task: Task,
    task_plan: TaskPlan,
) -> dict[str, Any]:
    """Execute a question task.

    Flow:
    1. Check question budget
    2. If budget exhausted -> return budget_exhausted action
    3. Generate/prepare question
    4. Record question asked (increment budget)
    5. Set task BLOCKED
    6. Return decision_result for Slack posting

    Args:
        state: Current AgentState
        task: The question task to execute
        task_plan: Parent TaskPlan

    Returns:
        State update with question_to_post and task status
    """
    channel_id = state.get("channel_id")
    thread_ts = state.get("thread_ts")

    if not task.question_task:
        logger.error(f"Task {task.task_id} is not a question task")
        return {}

    question_task = task.question_task

    async with get_connection() as conn:
        mode_store = ConversationModeStore(conn)
        budget = BudgetTracker(mode_store)

        # Check budget
        if await budget.is_exhausted(channel_id, thread_ts):
            logger.info(f"Question budget exhausted for {channel_id}/{thread_ts}")
            return {
                "decision_result": {
                    "action": "budget_exhausted",
                    "task_id": task.task_id,
                    "plan_id": task_plan.plan_id,
                    "pending_fields": _get_pending_fields(task_plan),
                },
            }

        # Record question asked
        new_count = await budget.record_question_asked(channel_id, thread_ts)
        logger.info(f"Question budget: {new_count}/2")

        # Ensure we're in ACTIVE mode
        await mode_store.transition(
            channel_id,
            thread_ts,
            ConversationMode.ACTIVE,
            ModeTransitionReason.TASK_BLOCKED,
        )

    # Set task status
    task.status = TaskStatus.BLOCKED
    task.requires_user_input = True
    question_task.status = QuestionStatus.PENDING

    return {
        "decision_result": {
            "action": "question_posted",
            "task_id": task.task_id,
            "plan_id": task_plan.plan_id,
            "plan_version": task_plan.version,
            "question": {
                "question_id": question_task.question_id,
                "question_type": question_task.question_type.value,
                "question_text": question_task.question_text,
                "target_field": question_task.target_field,
                "options": [
                    {
                        "option_id": opt.option_id,
                        "label": opt.label,
                        "description": opt.description,
                        "is_recommended": opt.is_recommended,
                    }
                    for opt in (question_task.options or [])
                ],
            },
        },
    }


def _get_pending_fields(task_plan: TaskPlan) -> list[str]:
    """Get list of fields with pending questions."""
    pending = []
    for task in task_plan.tasks:
        if task.is_question and task.status == TaskStatus.PENDING:
            if task.question_task and task.question_task.target_field:
                pending.append(task.question_task.target_field)
    return pending


async def handle_question_answer(
    state: AgentState,
    plan_id: str,
    task_id: str,
    patch: "StatePatch",
) -> dict[str, Any]:
    """Handle user's answer to a question task.

    Called when user clicks button or sends text reply.

    Args:
        state: Current AgentState
        plan_id: TaskPlan ID
        task_id: Task ID of the question
        patch: StatePatch from AnswerMapper

    Returns:
        State update - applies patch and continues execution
    """
    from src.db.task_plan_store import TaskPlanStore
    from src.schemas.state_patch import CONFIDENCE_THRESHOLD, StatePatch

    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

        if not task_plan:
            logger.warning(f"TaskPlan {plan_id} not found")
            return {"decision_result": {"action": "plan_not_found"}}

        # Find the task
        task = next((t for t in task_plan.tasks if t.task_id == task_id), None)
        if not task or not task.is_question:
            logger.warning(f"Question task {task_id} not found")
            return {"decision_result": {"action": "task_not_found"}}

        # Apply answer
        question_task = task.question_task
        question_task.answer = str(patch.value)
        question_task.status = QuestionStatus.ANSWERED
        question_task.answered_at = datetime.now(timezone.utc)

        # Check confidence - if too low, might need clarification
        if patch.confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                f"Low confidence answer ({patch.confidence}), may need clarification"
            )
            # Keep task BLOCKED for clarification
            return {
                "decision_result": {
                    "action": "low_confidence_answer",
                    "confidence": patch.confidence,
                    "task_id": task_id,
                },
            }

        # Mark task done and continue
        task.status = TaskStatus.DONE
        task.requires_user_input = False
        task_plan.status = TaskPlanStatus.PENDING

        await store.update(task_plan)

        # Reset budget counter
        mode_store = ConversationModeStore(conn)
        budget = BudgetTracker(mode_store)
        await budget.record_answer_received(
            state.get("channel_id"),
            state.get("thread_ts"),
        )

    # Continue execution
    from src.graph.nodes.task_executor import task_executor_node

    updated_state = {
        **state,
        "task_plan": task_plan.model_dump(),
    }
    # Apply patch to state
    updated_state[patch.field] = patch.value

    return await task_executor_node(updated_state)


# Import for type hint
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.schemas.state_patch import StatePatch

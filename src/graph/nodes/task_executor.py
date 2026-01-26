"""Task executor node for multi-intent orchestration.

Phase 35: Multi-Intent Task Orchestration

Processes tasks from TaskPlan in dependency order:
1. Find next executable task (PENDING, all deps DONE)
2. If safe -> run immediately
3. If dangerous -> set BLOCKED, return for UI
4. Update TaskPlan state and persist
"""

import logging
from datetime import datetime, timezone
from typing import Any

from src.db.connection import get_connection
from src.db.task_plan_store import TaskPlanStore
from src.schemas.state import AgentState
from src.schemas.task_plan import TaskPlan, TaskPlanStatus, TaskStatus, Task

logger = logging.getLogger(__name__)


async def task_executor_node(state: AgentState) -> dict[str, Any]:
    """Execute next task in TaskPlan.

    Flow:
    1. Load TaskPlan from state
    2. Find next executable task (PENDING with deps DONE)
    3. If auto-executable -> run task, update status
    4. If needs confirmation -> set BLOCKED, return decision_result
    5. If all done -> mark plan DONE
    6. Persist updated TaskPlan

    Returns:
        State update with task_plan and decision_result.
    """
    task_plan_data = state.get("task_plan")
    if not task_plan_data:
        logger.warning("task_executor called without task_plan")
        return {}

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Check if plan is already complete
    if task_plan.status in (TaskPlanStatus.DONE, TaskPlanStatus.CANCELED):
        logger.debug(f"TaskPlan {task_plan.plan_id} already {task_plan.status}")
        return {}

    # Find next executable task
    next_task = task_plan.get_next_pending_task()

    if not next_task:
        # No more tasks to run - check if blocked or done
        if task_plan.all_done():
            task_plan.status = TaskPlanStatus.DONE
            await _persist_plan(task_plan)
            return {
                "task_plan": task_plan.model_dump(),
                "decision_result": {"action": "task_plan_complete"},
            }
        else:
            # Still have BLOCKED tasks waiting
            task_plan.status = TaskPlanStatus.BLOCKED
            await _persist_plan(task_plan)
            return {
                "task_plan": task_plan.model_dump(),
                "decision_result": {"action": "task_plan_blocked"},
            }

    # Process the task
    if next_task.can_auto_execute():
        # Run immediately
        result = await _execute_task(state, task_plan, next_task)
        return result
    else:
        # Needs confirmation - block and show UI
        next_task.status = TaskStatus.BLOCKED
        next_task.requires_user_input = True
        task_plan.status = TaskPlanStatus.BLOCKED
        await _persist_plan(task_plan)

        return {
            "task_plan": task_plan.model_dump(),
            "decision_result": {
                "action": "task_confirmation_required",
                "task_id": next_task.task_id,
                "task_title": next_task.title,
                "task_mode": next_task.mode.value,
                "plan_id": task_plan.plan_id,
                "plan_version": task_plan.version,
            },
        }


async def _execute_task(
    state: AgentState,
    task_plan: TaskPlan,
    task: Task,
) -> dict[str, Any]:
    """Execute a single task and update state.

    Dispatches to appropriate handler based on intent.
    """
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(timezone.utc)
    task.set_active_step("Starting...")
    task_plan.status = TaskPlanStatus.RUNNING
    await _persist_plan(task_plan)

    try:
        # Execute based on intent type
        result = await _dispatch_task(state, task, task_plan)

        # Check for question-specific results that block execution
        decision_action = result.get("decision_result", {}).get("action")

        if decision_action == "question_posted":
            # Don't continue - wait for answer
            task_plan.status = TaskPlanStatus.BLOCKED
            await _persist_plan(task_plan)
            return {
                "task_plan": task_plan.model_dump(),
                **result,
            }

        if decision_action == "budget_exhausted":
            # Budget hit - show partial preview
            task_plan.status = TaskPlanStatus.BLOCKED
            await _persist_plan(task_plan)
            return {
                "task_plan": task_plan.model_dump(),
                **result,
            }

        # Mark complete
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(timezone.utc)
        task.last_error = None
        task.clear_active_step()

        # Check if more tasks to run
        await _persist_plan(task_plan)

        # Continue to next task (recursive until blocked or done)
        return await task_executor_node({
            **state,
            "task_plan": task_plan.model_dump(),
        })

    except Exception as e:
        logger.error(f"Task {task.task_id} failed: {e}")
        task.status = TaskStatus.BLOCKED
        task.last_error = str(e)
        task.clear_active_step()
        task_plan.status = TaskPlanStatus.BLOCKED
        await _persist_plan(task_plan)

        return {
            "task_plan": task_plan.model_dump(),
            "decision_result": {
                "action": "task_failed",
                "task_id": task.task_id,
                "error": str(e),
            },
        }


async def _dispatch_task(
    state: AgentState,
    task: Task,
    task_plan: TaskPlan,
) -> dict[str, Any]:
    """Dispatch task to appropriate handler based on intent.

    Maps task.intent to existing graph node logic or handlers.
    For question tasks, routes to question_executor_node.

    Sets active_step to indicate what MARO is currently doing.
    """
    from src.schemas.intent import Intent

    # Check if this is a question task first
    if task.is_question:
        from src.graph.nodes.question_executor import question_executor_node

        task.set_active_step("Preparing question")
        return await question_executor_node(state, task, task_plan)

    intent = task.intent

    # Map intents to handlers (simplified - expand as needed)
    if intent == Intent.JIRA_SEARCH:
        from src.graph.nodes.jira_search import jira_search_node

        task.set_active_step("Searching Jira")
        await _persist_plan(task_plan)
        return await jira_search_node({**state, "intent_result": task.params})

    elif intent == Intent.REVIEW:
        from src.graph.nodes.review import review_node

        task.set_active_step("Analyzing request")
        await _persist_plan(task_plan)
        return await review_node({**state, "intent_result": task.params})

    elif intent == Intent.DISCUSSION:
        from src.graph.nodes.discussion import discussion_node

        task.set_active_step("Processing discussion")
        await _persist_plan(task_plan)
        return await discussion_node({**state, "intent_result": task.params})

    # For intents that don't have direct node mapping,
    # return empty (they'll be handled by normal graph flow after approval)
    else:
        task.set_active_step("Processing request")
        await _persist_plan(task_plan)
        logger.debug(f"Task {task.task_id} intent {intent} delegated to graph flow")
        return {}


async def _persist_plan(task_plan: TaskPlan) -> TaskPlan:
    """Persist TaskPlan to database and update version.

    IMPORTANT: Updates task_plan.version in-place with the new version from DB.
    This is critical for optimistic locking to work correctly on subsequent updates.

    Returns:
        Updated TaskPlan with new version.
    """
    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        updated = await store.update(task_plan)
        # Update the passed-in object's version to match DB
        task_plan.version = updated.version
        return updated


async def handle_task_approval(
    state: AgentState,
    plan_id: str,
    task_id: str,
    approved: bool,
    plan_version: int,
) -> dict[str, Any]:
    """Handle user approval/rejection of a task.

    Called when user clicks [Approve] or [Reject] on a blocked task.

    Args:
        state: Current AgentState
        plan_id: TaskPlan ID
        task_id: Task ID being approved
        approved: True if approved, False if rejected
        plan_version: Version for idempotency check

    Returns:
        State update - either continues execution or marks rejected.
    """
    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

    if not task_plan:
        logger.warning(f"TaskPlan {plan_id} not found")
        return {"decision_result": {"action": "plan_not_found"}}

    # Version check for idempotency
    if task_plan.version != plan_version:
        logger.info(f"Stale approval: plan version {plan_version} != {task_plan.version}")
        return {
            "decision_result": {
                "action": "stale_approval",
                "message": "This action is outdated. The plan has changed.",
            }
        }

    # Find the task
    task = next((t for t in task_plan.tasks if t.task_id == task_id), None)
    if not task:
        logger.warning(f"Task {task_id} not found in plan {plan_id}")
        return {"decision_result": {"action": "task_not_found"}}

    if task.status != TaskStatus.BLOCKED:
        logger.info(f"Task {task_id} not blocked (status: {task.status})")
        return {
            "decision_result": {
                "action": "task_not_blocked",
                "current_status": task.status.value,
            }
        }

    if approved:
        # Mark as pending and continue execution
        task.status = TaskStatus.PENDING
        task.requires_user_input = False
        task_plan.status = TaskPlanStatus.PENDING
        await _persist_plan(task_plan)

        # Continue execution
        return await task_executor_node({
            **state,
            "task_plan": task_plan.model_dump(),
        })
    else:
        # User rejected - cancel this task
        task.status = TaskStatus.CANCELED
        # Cancel dependent tasks too
        _cascade_cancel(task_plan, task_id)
        await _persist_plan(task_plan)

        return {
            "task_plan": task_plan.model_dump(),
            "decision_result": {
                "action": "task_rejected",
                "task_id": task_id,
            },
        }


def _cascade_cancel(task_plan: TaskPlan, canceled_task_id: str) -> None:
    """Cancel all tasks that depend on a canceled task."""
    for task in task_plan.tasks:
        if canceled_task_id in task.depends_on and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELED
            task.last_error = f"Dependency {canceled_task_id} was canceled"
            # Recursively cancel dependents
            _cascade_cancel(task_plan, task.task_id)

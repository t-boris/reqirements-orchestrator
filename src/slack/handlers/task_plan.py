"""Button handlers for TaskPlan interactions.

Phase 35: Multi-Intent Task Orchestration

Handles:
- task_approve: User approves a blocked task
- task_reject: User rejects a blocked task
- task_plan_cancel: User cancels entire plan

All handlers use version binding for idempotency:
- Button value format: "{plan_id}:{task_id}:{version}" or "{plan_id}:{version}"
- Version mismatch -> "stale action" message
"""

import logging
from typing import Callable, Optional

from slack_sdk.web.async_client import AsyncWebClient

from src.db.connection import get_connection
from src.db.task_plan_store import TaskPlanStore
from src.graph.nodes.task_executor import handle_task_approval
from src.schemas.state import AgentState
from src.schemas.task_plan import TaskPlan, TaskPlanStatus, TaskStatus, Task
from src.slack.blocks.task_plan import build_plan_canceled_message
from src.slack.task_status_updater import TaskStatusUpdater
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


# =============================================================================
# Idempotency Helpers
# =============================================================================


def parse_task_button_value(value: str) -> tuple[str, str, int] | None:
    """Parse task button value: {plan_id}:{task_id}:{version}

    Args:
        value: The button value string

    Returns:
        Tuple of (plan_id, task_id, version) or None if invalid
    """
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        return parts[0], parts[1], int(parts[2])
    except ValueError:
        return None


def parse_plan_button_value(value: str) -> tuple[str, int] | None:
    """Parse plan button value: {plan_id}:{version}

    Args:
        value: The button value string

    Returns:
        Tuple of (plan_id, version) or None if invalid
    """
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


async def validate_task_action(
    plan_id: str,
    task_id: str,
    version: int,
    expected_status: TaskStatus = TaskStatus.BLOCKED,
) -> tuple[TaskPlan | None, Task | None, str | None]:
    """Validate a task action request.

    Checks plan existence, version match, and task status.

    Args:
        plan_id: The plan ID to validate
        task_id: The task ID within the plan
        version: Expected version for idempotency
        expected_status: Expected task status (default: BLOCKED)

    Returns:
        Tuple of (plan, task, error_message)
        If error_message is not None, action should be rejected.
    """
    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

    if not task_plan:
        return None, None, "Plan not found"

    if task_plan.version != version:
        return task_plan, None, "This action is outdated. The plan has been updated."

    task = next((t for t in task_plan.tasks if t.task_id == task_id), None)
    if not task:
        return task_plan, None, "Task not found"

    if task.status != expected_status:
        return task_plan, task, f"Task is already {task.status.value}"

    return task_plan, task, None


async def validate_plan_action(
    plan_id: str,
    version: int,
) -> tuple[TaskPlan | None, str | None]:
    """Validate a plan-level action request.

    Checks plan existence, version match, and plan status.

    Args:
        plan_id: The plan ID to validate
        version: Expected version for idempotency

    Returns:
        Tuple of (plan, error_message)
        If error_message is not None, action should be rejected.
    """
    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

    if not task_plan:
        return None, "Plan not found"

    if task_plan.version != version:
        return task_plan, "This action is outdated. The plan has been updated."

    if task_plan.status in (TaskPlanStatus.DONE, TaskPlanStatus.CANCELED):
        return task_plan, f"Plan is already {task_plan.status.value}"

    return task_plan, None


# =============================================================================
# Button Handlers
# =============================================================================


async def handle_task_approve(
    client: AsyncWebClient,
    body: dict,
    respond: Callable,
) -> None:
    """Handle task approval button click.

    Button value format: "{plan_id}:{task_id}:{version}"

    Validates version, processes approval, updates status card.
    """
    user_id = body.get("user", {}).get("id")
    action = body.get("actions", [{}])[0]
    value = action.get("value", "")
    channel_id = body.get("channel", {}).get("id")

    # Parse button value
    parsed = parse_task_button_value(value)
    if not parsed:
        await respond(text="Invalid action data")
        return

    plan_id, task_id, version = parsed

    # Validate action
    task_plan, task, error = await validate_task_action(plan_id, task_id, version)

    if error:
        await respond(
            text=f"Action failed: {error}",
            response_type="ephemeral",
        )
        # If stale, refresh the card to show current state
        if task_plan and "outdated" in error:
            updater = TaskStatusUpdater(client)
            await updater.update_card(
                task_plan,
                channel_id,
                event="stale_refresh",
            )
        return

    # Process approval
    state = AgentState(
        channel_id=channel_id,
        thread_ts=task_plan.thread_ts,
        user_id=user_id,
        task_plan=task_plan.model_dump(),
    )

    result = await handle_task_approval(
        state=state,
        plan_id=plan_id,
        task_id=task_id,
        approved=True,
        plan_version=version,
    )

    # Update status card
    updated_plan_data = result.get("task_plan")
    if updated_plan_data:
        updated_plan = TaskPlan.model_validate(updated_plan_data)
        updater = TaskStatusUpdater(client)
        await updater.update_card(
            updated_plan,
            channel_id,
            event="task_completed",
        )

    logger.info(f"Task {task_id} approved by {user_id}")


async def handle_task_reject(
    client: AsyncWebClient,
    body: dict,
    respond: Callable,
) -> None:
    """Handle task rejection button click.

    Button value format: "{plan_id}:{task_id}:{version}"

    Validates version, processes rejection, updates status card.
    """
    user_id = body.get("user", {}).get("id")
    action = body.get("actions", [{}])[0]
    value = action.get("value", "")
    channel_id = body.get("channel", {}).get("id")

    # Parse button value
    parsed = parse_task_button_value(value)
    if not parsed:
        await respond(text="Invalid action data")
        return

    plan_id, task_id, version = parsed

    # Validate action
    task_plan, task, error = await validate_task_action(plan_id, task_id, version)

    if error:
        await respond(
            text=f"Action failed: {error}",
            response_type="ephemeral",
        )
        return

    # Process rejection
    state = AgentState(
        channel_id=channel_id,
        thread_ts=task_plan.thread_ts,
        user_id=user_id,
        task_plan=task_plan.model_dump(),
    )

    result = await handle_task_approval(
        state=state,
        plan_id=plan_id,
        task_id=task_id,
        approved=False,
        plan_version=version,
    )

    # Update status card
    updated_plan_data = result.get("task_plan")
    if updated_plan_data:
        updated_plan = TaskPlan.model_validate(updated_plan_data)
        updater = TaskStatusUpdater(client)
        await updater.update_card(
            updated_plan,
            channel_id,
            event="task_blocked",
        )

    await respond(
        text="Task rejected. Dependent tasks have been canceled.",
        response_type="ephemeral",
    )
    logger.info(f"Task {task_id} rejected by {user_id}")


async def handle_plan_cancel(
    client: AsyncWebClient,
    body: dict,
    respond: Callable,
) -> None:
    """Handle plan cancellation button click.

    Button value format: "{plan_id}:{version}"

    Validates version, cancels plan, updates status card, posts message.
    """
    user_id = body.get("user", {}).get("id")
    action = body.get("actions", [{}])[0]
    value = action.get("value", "")
    channel_id = body.get("channel", {}).get("id")

    # Parse button value
    parsed = parse_plan_button_value(value)
    if not parsed:
        await respond(text="Invalid action data")
        return

    plan_id, version = parsed

    # Validate action
    task_plan, error = await validate_plan_action(plan_id, version)

    if error:
        await respond(
            text=f"Action failed: {error}",
            response_type="ephemeral",
        )
        return

    # Cancel the plan
    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.cancel_plan(plan_id, user_id)

    # Update status card to show canceled state
    updater = TaskStatusUpdater(client)
    await updater.update_card(
        task_plan,
        channel_id,
        event="plan_canceled",
    )

    # Post cancellation message
    message = build_plan_canceled_message(task_plan, user_id)
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=task_plan.thread_ts,
        text=message,
    )

    logger.info(f"Plan {plan_id} canceled by {user_id}")


# =============================================================================
# Handler Registration
# =============================================================================


def register_task_plan_handlers(app) -> None:
    """Register TaskPlan button handlers with Slack app.

    Call from router.py during app setup.

    Registers:
    - task_approve: Approve a blocked task
    - task_reject: Reject a blocked task
    - task_plan_cancel: Cancel entire plan
    """
    @app.action("task_approve")
    def on_task_approve(ack, body, client, respond):
        ack()
        _run_async(handle_task_approve(client, body, respond))

    @app.action("task_reject")
    def on_task_reject(ack, body, client, respond):
        ack()
        _run_async(handle_task_reject(client, body, respond))

    @app.action("task_plan_cancel")
    def on_plan_cancel(ack, body, client, respond):
        ack()
        _run_async(handle_plan_cancel(client, body, respond))

    logger.info("Registered TaskPlan button handlers")

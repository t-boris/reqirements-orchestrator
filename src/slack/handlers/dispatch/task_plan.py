"""TaskPlan-related dispatch handlers (Phase 35).

Handles TaskPlan creation, confirmation, completion, blocking, failure, and rejection.
"""

import logging
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

# Phase 35: TaskPlan imports
from src.schemas.task_plan import TaskPlan, TaskPlanStatus, TaskStatus
from src.slack.blocks.task_plan import (
    build_multi_intent_announcement,
    build_plan_complete_message,
)
from src.slack.task_status_updater import TaskStatusUpdater

# Phase 36: ConversationMode imports
from src.questions.mode_manager import ModeManager
from src.db.conversation_mode_store import ConversationModeStore
from src.schemas.conversation_mode import ModeTransitionReason

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def _handle_task_plan_created(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle newly created TaskPlan - post status card and announcement.

    Called when task_decomposer creates a new TaskPlan from multi-intent.
    Posts the canonical announcement and status card.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan data
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        logger.warning("task_plan_created action without task_plan data")
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Post announcement message
    announcement = build_multi_intent_announcement(task_plan)
    await client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=announcement,
    )

    # Post status card
    updater = TaskStatusUpdater(client)
    await updater.post_initial_card(
        task_plan,
        identity.channel_id,
        identity.thread_ts,
    )

    # Phase 43: Start elapsed timer if any tasks are running
    if task_plan.has_running():
        await updater.start_elapsed_timer(task_plan.plan_id, identity.channel_id)

    logger.info(
        f"Posted TaskPlan {task_plan.plan_id} with {len(task_plan.tasks)} tasks",
        extra={
            "plan_id": task_plan.plan_id,
            "task_count": len(task_plan.tasks),
            "auto_count": result.get("auto_count", 0),
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
        },
    )


async def _handle_task_confirmation(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle task needing confirmation - update status card.

    Called when a task with REQUIRES_CONFIRMATION safety level is reached.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan and task info
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Update status card to show blocked task
    updater = TaskStatusUpdater(client)
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="task_blocked",
    )

    # Post reminder about which task needs approval
    task_title = result.get("task_title", "Unknown task")
    await client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f":double_vertical_bar: Waiting for approval: *{task_title}*\nUse the buttons above to approve or reject.",
    )

    logger.info(
        f"Task confirmation required for {task_title}",
        extra={
            "plan_id": task_plan.plan_id,
            "task_title": task_title,
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_plan_complete(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle completed TaskPlan - post summary to channel.

    Called when all tasks in the plan are DONE.
    Phase 36: Also deactivates conversation mode.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan data
        identity: Session identity
    """
    from src.db.connection import get_connection

    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Phase 36: Deactivate conversation mode on plan completion
    if identity.thread_ts:
        try:
            async with get_connection() as conn:
                mode_store = ConversationModeStore(conn)
                mode_manager = ModeManager(mode_store)
                await mode_manager.check_and_deactivate(
                    identity.channel_id,
                    identity.thread_ts,
                    ModeTransitionReason.PLAN_COMPLETE,
                )
        except Exception as e:
            logger.warning(f"Failed to deactivate mode on plan complete: {e}")

    # Phase 43: Stop elapsed timer on plan completion
    updater = TaskStatusUpdater(client)
    await updater.stop_elapsed_timer(task_plan.plan_id)

    # Final status card update
    await updater.flush_pending(task_plan.plan_id, identity.channel_id)
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="plan_completed",
    )

    # Post completion summary to channel (not just thread)
    summary = build_plan_complete_message(task_plan)
    await client.chat_postMessage(
        channel=identity.channel_id,
        text=summary,
    )

    logger.info(
        f"TaskPlan {task_plan.plan_id} completed",
        extra={
            "plan_id": task_plan.plan_id,
            "completed_tasks": len([t for t in task_plan.tasks if t.status == TaskStatus.DONE]),
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_plan_blocked(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle TaskPlan that's blocked waiting for user input.

    Called when plan cannot progress because tasks are blocked.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan data
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Phase 43: Stop elapsed timer when plan is blocked
    updater = TaskStatusUpdater(client)
    await updater.stop_elapsed_timer(task_plan.plan_id)

    # Update status card
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="task_blocked",
    )

    # Find blocked tasks
    blocked = [t for t in task_plan.tasks if t.status == TaskStatus.BLOCKED]
    if blocked:
        task_names = ", ".join(t.title for t in blocked[:3])
        if len(blocked) > 3:
            task_names += f", and {len(blocked) - 3} more"
        await client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":double_vertical_bar: Waiting for: {task_names}",
        )

    logger.info(
        f"TaskPlan {task_plan.plan_id} blocked",
        extra={
            "plan_id": task_plan.plan_id,
            "blocked_count": len(blocked),
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_failed(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle failed task - show error.

    Called when a task execution fails.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan, task_id, and error
        identity: Session identity
    """
    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Phase 43: Stop elapsed timer on task failure
    updater = TaskStatusUpdater(client)
    await updater.stop_elapsed_timer(task_plan.plan_id)

    # Update status card
    await updater.update_card(
        task_plan,
        identity.channel_id,
        event="task_failed",
    )

    # Post error message
    task_id = result.get("task_id", "unknown")
    error = result.get("error", "Unknown error")
    await client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f":x: Task failed: {error}\nYou can retry or cancel the plan.",
    )

    logger.error(
        f"Task {task_id} failed in plan {task_plan.plan_id}",
        extra={
            "plan_id": task_plan.plan_id,
            "task_id": task_id,
            "error": error,
            "channel_id": identity.channel_id,
        },
    )


async def _handle_task_rejected(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle task rejection - check if plan is canceled.

    Called when a user rejects a task. If the plan status becomes
    'canceled', deactivates conversation mode.

    Args:
        client: Slack WebClient
        result: Decision result with task_plan and task_id
        identity: Session identity
    """
    from src.db.connection import get_connection

    task_plan_data = result.get("task_plan")
    if not task_plan_data:
        return

    task_plan = TaskPlan.model_validate(task_plan_data)

    # Check if plan is canceled
    if task_plan.status == TaskPlanStatus.CANCELED:
        # Deactivate conversation mode
        if identity.thread_ts:
            try:
                async with get_connection() as conn:
                    mode_store = ConversationModeStore(conn)
                    mode_manager = ModeManager(mode_store)
                    await mode_manager.check_and_deactivate(
                        identity.channel_id,
                        identity.thread_ts,
                        ModeTransitionReason.USER_CANCEL,
                    )
            except Exception as e:
                logger.warning(f"Failed to deactivate mode on task rejection: {e}")

        # Phase 43: Stop elapsed timer on plan cancellation
        updater = TaskStatusUpdater(client)
        await updater.stop_elapsed_timer(task_plan.plan_id)

        # Update status card
        await updater.update_card(
            task_plan,
            identity.channel_id,
            event="plan_canceled",
        )

        await client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=":no_entry: Plan canceled.",
        )

        logger.info(
            f"TaskPlan {task_plan.plan_id} canceled via task rejection",
            extra={
                "plan_id": task_plan.plan_id,
                "channel_id": identity.channel_id,
            },
        )
    else:
        # Task rejected but plan continues
        task_id = result.get("task_id", "unknown")
        await client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":x: Task rejected. The plan will continue with remaining tasks.",
        )

        logger.info(
            f"Task {task_id} rejected in plan {task_plan.plan_id}",
            extra={
                "plan_id": task_plan.plan_id,
                "task_id": task_id,
                "channel_id": identity.channel_id,
            },
        )

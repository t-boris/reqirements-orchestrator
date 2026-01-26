"""TaskStatusUpdater with throttling for Slack rate limits.

Phase 35: Multi-Intent Task Orchestration

Updates TaskPlan status card via chat.update with:
- Max 1 update per 1.5 seconds (throttling)
- Immediate updates on significant events
- Batched progress updates

Slack rate limits: ~1 req/sec per channel for updates.
We use 1.5s to be safe.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

from src.db.connection import get_connection
from src.db.task_plan_store import TaskPlanStore
from src.schemas.task_plan import TaskPlan, TaskPlanStatus
from src.slack.blocks.task_plan import build_task_plan_blocks

logger = logging.getLogger(__name__)

# Throttling: minimum seconds between updates
MIN_UPDATE_INTERVAL = 1.5

# Significant events that bypass throttling
SIGNIFICANT_EVENTS = {
    "task_started",
    "task_completed",
    "task_blocked",
    "task_failed",
    "task_state_changed",  # Phase 43: Visual state transition feedback
    "plan_completed",
    "plan_canceled",
}


# Elapsed timer configuration
ELAPSED_TIMER_INTERVAL = 5.0  # Update every 5 seconds

# Module-level timer tracking for cross-instance timer management
# Keyed by plan_id -> asyncio.Task
_active_timers: dict[str, asyncio.Task] = {}


class TaskStatusUpdater:
    """Manages TaskPlan status card updates with throttling."""

    def __init__(self, client: AsyncWebClient):
        self.client = client
        self._last_update: dict[str, float] = {}  # plan_id -> timestamp
        self._pending_updates: dict[str, TaskPlan] = {}  # plan_id -> latest plan
        self._update_lock = asyncio.Lock()

    async def post_initial_card(
        self,
        task_plan: TaskPlan,
        channel_id: str,
        thread_ts: Optional[str] = None,
    ) -> str:
        """Post initial status card and return message_ts.

        Args:
            task_plan: The TaskPlan to display
            channel_id: Slack channel ID
            thread_ts: Thread timestamp (post in thread, not channel)

        Returns:
            Message timestamp for future updates
        """
        blocks = build_task_plan_blocks(task_plan)

        response = await self.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"MARO Plan: {len(task_plan.tasks)} tasks",
            blocks=blocks,
        )

        message_ts = response["ts"]

        # Store message_ts in TaskPlan
        async with get_connection() as conn:
            store = TaskPlanStore(conn)
            await store.update_ui_message(task_plan.plan_id, message_ts)

        task_plan.ui_message_ts = message_ts
        self._last_update[task_plan.plan_id] = datetime.now(timezone.utc).timestamp()

        logger.info(f"Posted TaskPlan status card: {message_ts}")
        return message_ts

    async def update_card(
        self,
        task_plan: TaskPlan,
        channel_id: str,
        event: str = "progress",
    ) -> None:
        """Update status card with throttling.

        Args:
            task_plan: Updated TaskPlan
            channel_id: Slack channel ID
            event: Event type (for throttling decision)
        """
        if not task_plan.ui_message_ts:
            logger.warning(f"No ui_message_ts for plan {task_plan.plan_id}")
            return

        async with self._update_lock:
            now = datetime.now(timezone.utc).timestamp()
            last = self._last_update.get(task_plan.plan_id, 0)

            # Check if we should update
            should_update = False

            if event in SIGNIFICANT_EVENTS:
                # Significant events bypass throttle
                should_update = True
            elif now - last >= MIN_UPDATE_INTERVAL:
                # Enough time has passed
                should_update = True
            else:
                # Queue for later
                self._pending_updates[task_plan.plan_id] = task_plan
                logger.debug(f"Throttled update for plan {task_plan.plan_id}")
                return

            if should_update:
                await self._do_update(task_plan, channel_id)
                self._last_update[task_plan.plan_id] = now
                self._pending_updates.pop(task_plan.plan_id, None)

    async def _do_update(self, task_plan: TaskPlan, channel_id: str) -> None:
        """Perform the actual chat.update call."""
        blocks = build_task_plan_blocks(task_plan)

        try:
            await self.client.chat_update(
                channel=channel_id,
                ts=task_plan.ui_message_ts,
                text=f"MARO Plan: {len(task_plan.tasks)} tasks",
                blocks=blocks,
            )
            logger.debug(f"Updated TaskPlan status card: {task_plan.ui_message_ts}")
        except Exception as e:
            logger.error(f"Failed to update status card: {e}")

    async def update_step(
        self,
        plan_id: str,
        task_id: str,
        step: str,
        channel_id: str,
    ) -> None:
        """Update task's active step and refresh status card.

        This is a convenience method that:
        1. Loads the TaskPlan from DB
        2. Updates the task's active_step
        3. Persists the change
        4. Triggers a card update (respecting throttle)

        Use this for granular step updates during long operations.

        Args:
            plan_id: TaskPlan ID
            task_id: Task ID to update
            step: New active step description (should be <40 chars)
            channel_id: Slack channel ID for card update
        """
        async with get_connection() as conn:
            store = TaskPlanStore(conn)
            task_plan = await store.get(plan_id)

        if not task_plan:
            logger.warning(f"update_step: plan {plan_id} not found")
            return

        # Find and update the task
        task = task_plan.get_task(task_id)
        if not task:
            logger.warning(f"update_step: task {task_id} not found in plan {plan_id}")
            return

        task.set_active_step(step)

        # Persist and update card
        async with get_connection() as conn:
            store = TaskPlanStore(conn)
            await store.update(task_plan)

        await self.update_card(task_plan, channel_id, event="step_change")

    async def flush_pending(self, plan_id: str, channel_id: str) -> None:
        """Flush any pending updates for a plan.

        Call this when plan completes to ensure final state is shown.
        """
        async with self._update_lock:
            if plan_id in self._pending_updates:
                task_plan = self._pending_updates.pop(plan_id)
                await self._do_update(task_plan, channel_id)

    async def delete_card(self, task_plan: TaskPlan, channel_id: str) -> None:
        """Delete status card (optional, for cleanup)."""
        if not task_plan.ui_message_ts:
            return

        try:
            await self.client.chat_delete(
                channel=channel_id,
                ts=task_plan.ui_message_ts,
            )
            logger.info(f"Deleted TaskPlan status card: {task_plan.ui_message_ts}")
        except Exception as e:
            logger.debug(f"Could not delete status card: {e}")

    async def start_elapsed_timer(
        self,
        plan_id: str,
        channel_id: str,
    ) -> None:
        """Start a background task that updates elapsed time every 5s.

        Phase 43: Task Progress UX - shows elapsed time updating live.

        Timer should:
        - Update every 5 seconds while task is RUNNING
        - Respect throttling (combine with other updates)
        - Auto-stop when task completes
        - Not block main execution

        Args:
            plan_id: TaskPlan ID to track
            channel_id: Slack channel ID for card updates
        """
        global _active_timers

        # Don't start if already running
        if plan_id in _active_timers:
            logger.debug(f"Elapsed timer already running for plan {plan_id}")
            return

        # Need to capture self.client for use in the closure
        client = self.client

        async def _timer_loop():
            """Background timer that updates status card periodically."""
            try:
                while True:
                    await asyncio.sleep(ELAPSED_TIMER_INTERVAL)

                    # Load fresh plan state from DB
                    async with get_connection() as conn:
                        store = TaskPlanStore(conn)
                        task_plan = await store.get(plan_id)

                    if not task_plan:
                        logger.debug(f"Elapsed timer: plan {plan_id} not found, stopping")
                        break

                    # Check if any tasks are still running
                    if not task_plan.has_running():
                        logger.debug(f"Elapsed timer: no running tasks in plan {plan_id}, stopping")
                        break

                    # Check if plan is done or canceled
                    if task_plan.status in (TaskPlanStatus.DONE, TaskPlanStatus.CANCELED):
                        logger.debug(f"Elapsed timer: plan {plan_id} is {task_plan.status}, stopping")
                        break

                    # Update the status card (respects throttling)
                    # Create a fresh updater instance with captured client
                    updater = TaskStatusUpdater(client)
                    await updater.update_card(task_plan, channel_id, event="elapsed_tick")

            except asyncio.CancelledError:
                logger.debug(f"Elapsed timer for plan {plan_id} was cancelled")
            except Exception as e:
                logger.warning(f"Elapsed timer error for plan {plan_id}: {e}")
            finally:
                # Clean up timer reference
                _active_timers.pop(plan_id, None)

        # Start the background task
        timer_task = asyncio.create_task(_timer_loop())
        _active_timers[plan_id] = timer_task
        logger.info(f"Started elapsed timer for plan {plan_id}")

    async def stop_elapsed_timer(self, plan_id: str) -> None:
        """Stop the elapsed timer for a plan.

        Called when task completes/fails/blocks to stop the timer.

        Args:
            plan_id: TaskPlan ID to stop tracking
        """
        global _active_timers

        timer_task = _active_timers.pop(plan_id, None)
        if timer_task:
            timer_task.cancel()
            try:
                await timer_task
            except asyncio.CancelledError:
                pass
            logger.info(f"Stopped elapsed timer for plan {plan_id}")

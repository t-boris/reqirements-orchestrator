"""Progress tracking with timing-based status messages.

Provides visual feedback during bot processing with timing thresholds:
- < 4s: No status message (fast operations)
- >= 4s: Post status message with elapsed time
- On complete: Edit to Done, then delete after 1s
"""

import asyncio
import logging
import time
from typing import Optional, Union

from slack_sdk.web import WebClient
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Timing thresholds (seconds)
STATUS_THRESHOLD = 4  # Post status message after this
UPDATE_INTERVAL = 5  # Update status every N seconds
LONG_OPERATION_THRESHOLD = 15  # Show bottleneck info after this
VERY_LONG_OPERATION_THRESHOLD = 30  # Additional update at this threshold

# Predefined status messages for operations
STATUS_MESSAGES = {
    "processing": "Processing...",
    "context": "Loading context...",
    "extracting": "Extracting requirements...",
    "validating": "Validating draft...",
    "searching_jira": "Searching Jira...",
    "preparing_preview": "Preparing preview...",
    "creating_ticket": "Creating ticket...",
}


class ProgressTracker:
    """Manage progress status messages with timing thresholds.

    Usage:
        tracker = ProgressTracker(client, channel, thread_ts)
        try:
            await tracker.start("Processing...")
            # ... do work ...
            await tracker.update("Searching Jira...")
            # ... more work ...
        finally:
            await tracker.complete()
    """

    def __init__(
        self,
        client: Union[WebClient, AsyncWebClient],
        channel: str,
        thread_ts: str,
    ):
        """Initialize progress tracker.

        Args:
            client: Slack WebClient (sync or async) for posting messages
            channel: Channel ID to post in
            thread_ts: Thread timestamp to reply in
        """
        self.client = client
        self.channel = channel
        self.thread_ts = thread_ts

        self._status_ts: Optional[str] = None  # Status message timestamp
        self._start_time: Optional[float] = None
        self._current_status: str = ""
        self._delayed_post_task: Optional[asyncio.Task] = None
        self._long_operation_task: Optional[asyncio.Task] = None
        self._completed: bool = False

    async def start(self, initial_status: str = "Processing...") -> None:
        """Start tracking. Posts status if >4s threshold exceeded.

        Does not post immediately - schedules delayed posting.
        Call update() to change status text during operation.

        Args:
            initial_status: Initial status text (default "Processing...")
        """
        self._start_time = time.monotonic()
        self._current_status = initial_status
        self._completed = False

        # Schedule delayed status posting
        self._delayed_post_task = asyncio.create_task(
            self._delayed_post(STATUS_THRESHOLD)
        )

        # Schedule long operation updates (15s and 30s)
        self._long_operation_task = asyncio.create_task(
            self._schedule_long_operation_updates()
        )

    async def set_operation(self, operation: str) -> None:
        """Set current operation from predefined list.

        Maps operation key to user-friendly status message.
        Falls back to operation name if not in STATUS_MESSAGES.

        Args:
            operation: Operation key (e.g., "searching_jira", "preparing_preview")
        """
        status = STATUS_MESSAGES.get(operation, operation)
        await self.update(status)

    async def set_error(
        self,
        error_type: str,
        service: str,
        attempt: int = 1,
        max_attempts: int = 3,
    ) -> None:
        """Set error state with retry info.

        Shows transient error message during retry attempts.
        Formats message based on error type for clear user feedback.

        Args:
            error_type: Type of error (api_error, timeout, rate_limit)
            service: Service name (Jira, Slack, LLM)
            attempt: Current attempt number
            max_attempts: Maximum retry attempts
        """
        if error_type == "timeout":
            msg = f":warning: {service} API timeout. Retrying... ({attempt}/{max_attempts})"
        elif error_type == "rate_limit":
            msg = f":warning: {service} API rate-limited. Backing off..."
        else:
            msg = f":warning: {service} API error. Retrying... ({attempt}/{max_attempts})"

        await self.update(msg)

    async def set_failure(self, service: str, error_msg: str = "") -> None:
        """Set permanent failure state after retries exhausted.

        Shows failure message. Does not auto-delete - keeps message visible
        so user can see what failed and take action.

        Args:
            service: Service name that failed (Jira, Slack, LLM)
            error_msg: Optional error details to include
        """
        if error_msg:
            self._current_status = f":x: {service} unreachable: {error_msg}"
        else:
            self._current_status = f":x: {service} unreachable after retries."

        # Post or update the failure status
        if self._status_ts:
            await self._update_failure_status()
        else:
            await self._post_failure_status()

    async def _post_failure_status(self) -> None:
        """Post failure status message (does not auto-delete)."""
        if self._completed or self._status_ts:
            return

        try:
            if isinstance(self.client, AsyncWebClient):
                response = await self.client.chat_postMessage(
                    channel=self.channel,
                    thread_ts=self.thread_ts,
                    text=self._current_status,
                )
            else:
                response = await asyncio.to_thread(
                    self.client.chat_postMessage,
                    channel=self.channel,
                    thread_ts=self.thread_ts,
                    text=self._current_status,
                )
            self._status_ts = response.get("ts")
            logger.debug(
                "Posted failure status message",
                extra={
                    "channel": self.channel,
                    "thread_ts": self.thread_ts,
                    "status_ts": self._status_ts,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to post failure status message: {e}")

    async def _update_failure_status(self) -> None:
        """Update existing status message to failure state."""
        if not self._status_ts:
            return

        try:
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_update(
                    channel=self.channel,
                    ts=self._status_ts,
                    text=self._current_status,
                )
            else:
                await asyncio.to_thread(
                    self.client.chat_update,
                    channel=self.channel,
                    ts=self._status_ts,
                    text=self._current_status,
                )
            logger.debug(
                "Updated status to failure",
                extra={
                    "status_ts": self._status_ts,
                    "status": self._current_status,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to update failure status: {e}")

    async def update(self, status: str) -> None:
        """Update status text. Only posts if message already visible.

        If status message not yet visible, updates the pending status.
        If status message visible, edits it immediately.

        Args:
            status: New status text
        """
        if self._completed:
            return

        self._current_status = status

        # If message already posted, update it
        if self._status_ts:
            await self._update_status()

    async def complete(self, show_done: bool = True) -> None:
        """Mark complete. Edits to Done, then deletes after 1s.

        Args:
            show_done: Whether to show "Done" before deleting (default True)
        """
        self._completed = True

        # Cancel delayed posting if not yet fired
        if self._delayed_post_task:
            self._delayed_post_task.cancel()
            try:
                await self._delayed_post_task
            except asyncio.CancelledError:
                pass
            self._delayed_post_task = None

        # Cancel long operation updates if not yet fired
        if self._long_operation_task:
            self._long_operation_task.cancel()
            try:
                await self._long_operation_task
            except asyncio.CancelledError:
                pass
            self._long_operation_task = None

        # If status message was posted, clean it up
        if self._status_ts:
            if show_done:
                await self._show_done_and_delete()
            else:
                await self._delete_status()

    async def _delayed_post(self, delay: float) -> None:
        """Post status message after delay (threshold exceeded)."""
        try:
            await asyncio.sleep(delay)

            # Don't post if already completed
            if self._completed:
                return

            await self._post_status()

        except asyncio.CancelledError:
            # Expected when operation completes before threshold
            pass

    async def _post_status(self) -> None:
        """Post initial status message."""
        if self._completed or self._status_ts:
            return  # Already posted or completed

        elapsed = self._get_elapsed()
        message = f":hourglass_flowing_sand: {self._current_status}"
        if elapsed >= STATUS_THRESHOLD:
            message += f" ({elapsed}s)"

        try:
            # Handle both sync and async clients
            if isinstance(self.client, AsyncWebClient):
                response = await self.client.chat_postMessage(
                    channel=self.channel,
                    thread_ts=self.thread_ts,
                    text=message,
                )
            else:
                # Sync client - run in thread to avoid blocking
                response = await asyncio.to_thread(
                    self.client.chat_postMessage,
                    channel=self.channel,
                    thread_ts=self.thread_ts,
                    text=message,
                )
            self._status_ts = response.get("ts")
            logger.debug(
                "Posted status message",
                extra={
                    "channel": self.channel,
                    "thread_ts": self.thread_ts,
                    "status_ts": self._status_ts,
                    "elapsed": elapsed,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to post status message: {e}")

    async def _update_status(self) -> None:
        """Update existing status message with elapsed time.

        Shows elapsed time in 5-second increments after 10s.
        Format: "Searching Jira... (5s)" or "Searching Jira... (15s)"
        """
        if not self._status_ts or self._completed:
            return

        elapsed = self._get_elapsed()
        # Show elapsed in 5-second increments after 10s
        if elapsed >= 10:
            # Round to nearest 5 seconds
            rounded_elapsed = (elapsed // 5) * 5
            message = f":hourglass_flowing_sand: {self._current_status} ({rounded_elapsed}s)"
        else:
            message = f":hourglass_flowing_sand: {self._current_status}"

        try:
            # Handle both sync and async clients
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_update(
                    channel=self.channel,
                    ts=self._status_ts,
                    text=message,
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_update,
                    channel=self.channel,
                    ts=self._status_ts,
                    text=message,
                )
            logger.debug(
                "Updated status message",
                extra={
                    "status_ts": self._status_ts,
                    "status": self._current_status,
                    "elapsed": elapsed,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to update status message: {e}")

    async def _show_done_and_delete(self) -> None:
        """Show "Done" message then delete after 1s."""
        if not self._status_ts:
            return

        # Update to "Done"
        try:
            # Handle both sync and async clients
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_update(
                    channel=self.channel,
                    ts=self._status_ts,
                    text=":white_check_mark: Done.",
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_update,
                    channel=self.channel,
                    ts=self._status_ts,
                    text=":white_check_mark: Done.",
                )
        except Exception as e:
            logger.warning(f"Failed to update status to done: {e}")

        # Wait briefly then delete
        await asyncio.sleep(1)
        await self._delete_status()

    async def _delete_status(self) -> None:
        """Delete status message."""
        if not self._status_ts:
            return

        try:
            # Handle both sync and async clients
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_delete(
                    channel=self.channel,
                    ts=self._status_ts,
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_delete,
                    channel=self.channel,
                    ts=self._status_ts,
                )
            logger.debug(
                "Deleted status message",
                extra={"status_ts": self._status_ts}
            )
        except Exception as e:
            # May not have permission to delete
            logger.warning(f"Failed to delete status message: {e}")

        self._status_ts = None

    async def _schedule_long_operation_updates(self) -> None:
        """Schedule updates for long-running operations.

        Posts bottleneck info at 15s and 30s thresholds.
        Only posts if status message is visible (already passed 4s threshold).
        """
        try:
            # Wait for 15s threshold
            await asyncio.sleep(LONG_OPERATION_THRESHOLD)

            # Don't update if completed
            if self._completed:
                return

            # Only update if status message was posted
            if self._status_ts and self._current_status:
                elapsed = self._get_elapsed()
                bottleneck = self._identify_bottleneck()
                await self._update_with_bottleneck(bottleneck, elapsed)

            # Wait for additional 15s (30s total)
            await asyncio.sleep(VERY_LONG_OPERATION_THRESHOLD - LONG_OPERATION_THRESHOLD)

            # Don't update if completed
            if self._completed:
                return

            # Update again at 30s
            if self._status_ts and self._current_status:
                elapsed = self._get_elapsed()
                bottleneck = self._identify_bottleneck()
                await self._update_with_bottleneck(bottleneck, elapsed, show_waiting=True)

        except asyncio.CancelledError:
            # Expected when operation completes before thresholds
            pass

    def _identify_bottleneck(self) -> str:
        """Identify what's slow based on current operation.

        Returns human-readable bottleneck name for status display.
        """
        status_lower = self._current_status.lower()

        if "jira" in status_lower:
            return "Jira API"
        elif "context" in status_lower:
            return "Context loading"
        elif "extracting" in status_lower:
            return "LLM processing"
        elif "validating" in status_lower:
            return "Validation"
        elif "preview" in status_lower:
            return "Preview generation"
        else:
            return "Processing"

    async def _update_with_bottleneck(
        self,
        bottleneck: str,
        elapsed: int,
        show_waiting: bool = False,
    ) -> None:
        """Update status message with bottleneck identification.

        Args:
            bottleneck: Name of the slow component (e.g., "Jira API")
            elapsed: Elapsed time in seconds
            show_waiting: Whether to show "Still waiting..." suffix
        """
        if not self._status_ts or self._completed:
            return

        if show_waiting:
            message = f":hourglass_flowing_sand: {bottleneck} is responding slowly ({elapsed}s). Still waiting..."
        else:
            message = f":hourglass_flowing_sand: {bottleneck} is responding slowly ({elapsed}s)"

        try:
            # Handle both sync and async clients
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_update(
                    channel=self.channel,
                    ts=self._status_ts,
                    text=message,
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_update,
                    channel=self.channel,
                    ts=self._status_ts,
                    text=message,
                )
            logger.debug(
                "Updated status with bottleneck info",
                extra={
                    "status_ts": self._status_ts,
                    "bottleneck": bottleneck,
                    "elapsed": elapsed,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to update status with bottleneck: {e}")

    def _get_elapsed(self) -> int:
        """Get elapsed time in seconds."""
        if self._start_time is None:
            return 0
        return int(time.monotonic() - self._start_time)


__all__ = ["ProgressTracker", "STATUS_MESSAGES"]

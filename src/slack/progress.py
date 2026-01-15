"""Progress tracking with timing-based status messages.

Provides visual feedback during bot processing with timing thresholds:
- < 4s: No status message (fast operations)
- >= 4s: Post status message with elapsed time
- On complete: Edit to Done, then delete after 1s
"""

import asyncio
import logging
import time
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Timing thresholds (seconds)
STATUS_THRESHOLD = 4  # Post status message after this
UPDATE_INTERVAL = 5  # Update status every N seconds


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
        client: AsyncWebClient,
        channel: str,
        thread_ts: str,
    ):
        """Initialize progress tracker.

        Args:
            client: Async Slack WebClient for posting messages
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
            response = await self.client.chat_postMessage(
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
        """Update existing status message with elapsed time."""
        if not self._status_ts or self._completed:
            return

        elapsed = self._get_elapsed()
        message = f":hourglass_flowing_sand: {self._current_status} ({elapsed}s)"

        try:
            await self.client.chat_update(
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
            await self.client.chat_update(
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
            await self.client.chat_delete(
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

    def _get_elapsed(self) -> int:
        """Get elapsed time in seconds."""
        if self._start_time is None:
            return 0
        return int(time.monotonic() - self._start_time)


__all__ = ["ProgressTracker"]

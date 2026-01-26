"""SingleTaskStatus helper for single-intent request feedback.

Phase 43: Task Progress UX

Manages the lifecycle of a single-task status card:
- Post a "Working on: X" card when processing starts
- Update to "Done: X" when complete
- Delete the card if processing was fast (<2s) to avoid stale cards

Unlike TaskStatusUpdater (for multi-task TaskPlans), this handles
simple single-intent requests that don't create a full TaskPlan.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Union

from slack_sdk.web import WebClient
from slack_sdk.web.async_client import AsyncWebClient

from src.slack.blocks.task_plan import build_single_task_blocks

logger = logging.getLogger(__name__)

# Delete status card if processing completes within this time (seconds)
# Fast responses don't need lingering status cards
FAST_RESPONSE_THRESHOLD = 2.0


class SingleTaskStatus:
    """Manages single-task status card lifecycle.

    Usage:
        status = SingleTaskStatus(client, channel_id, thread_ts)
        await status.start("Processing your request")
        # ... do work ...
        await status.complete()  # or status.delete() for fast responses

    Supports both sync (WebClient) and async (AsyncWebClient) Slack clients.
    """

    def __init__(
        self,
        client: Union[WebClient, AsyncWebClient],
        channel_id: str,
        thread_ts: Optional[str] = None,
    ):
        """Initialize SingleTaskStatus.

        Args:
            client: Slack WebClient (sync or async).
            channel_id: Channel to post status card in.
            thread_ts: Thread to post in (optional, posts to channel root if None).
        """
        self.client = client
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self._message_ts: Optional[str] = None
        self._action_text: Optional[str] = None
        self._start_time: Optional[float] = None

    @property
    def message_ts(self) -> Optional[str]:
        """Get the message timestamp of the status card."""
        return self._message_ts

    async def start(self, action_text: str) -> Optional[str]:
        """Post initial status card showing action in progress.

        Args:
            action_text: Description of the action being performed.

        Returns:
            Message timestamp of the posted card, or None on error.
        """
        self._action_text = action_text
        self._start_time = datetime.now(timezone.utc).timestamp()

        blocks = build_single_task_blocks(action_text, status="running")

        try:
            if isinstance(self.client, AsyncWebClient):
                response = await self.client.chat_postMessage(
                    channel=self.channel_id,
                    thread_ts=self.thread_ts,
                    text=f"Working on: {action_text}",
                    blocks=blocks,
                )
            else:
                # Sync client - run in thread to avoid blocking
                response = await asyncio.to_thread(
                    self.client.chat_postMessage,
                    channel=self.channel_id,
                    thread_ts=self.thread_ts,
                    text=f"Working on: {action_text}",
                    blocks=blocks,
                )
            self._message_ts = response.get("ts")
            logger.debug(
                "Posted single-task status card",
                extra={
                    "message_ts": self._message_ts,
                    "action_text": action_text,
                    "channel_id": self.channel_id,
                },
            )
            return self._message_ts
        except Exception as e:
            logger.warning(f"Failed to post single-task status card: {e}")
            return None

    async def complete(self) -> None:
        """Update status card to show completion.

        If processing was fast (<2s), deletes the card instead.
        """
        if not self._message_ts or not self._action_text:
            return

        # Check if this was a fast response
        if self._start_time:
            elapsed = datetime.now(timezone.utc).timestamp() - self._start_time
            if elapsed < FAST_RESPONSE_THRESHOLD:
                # Fast response - delete the card to avoid clutter
                await self.delete()
                return

        # Update to done status
        blocks = build_single_task_blocks(self._action_text, status="done")

        try:
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_update(
                    channel=self.channel_id,
                    ts=self._message_ts,
                    text=f"Done: {self._action_text}",
                    blocks=blocks,
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_update,
                    channel=self.channel_id,
                    ts=self._message_ts,
                    text=f"Done: {self._action_text}",
                    blocks=blocks,
                )
            logger.debug(
                "Updated single-task status to done",
                extra={
                    "message_ts": self._message_ts,
                    "action_text": self._action_text,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to update single-task status: {e}")

    async def error(self, error_message: Optional[str] = None) -> None:
        """Update status card to show error.

        Args:
            error_message: Optional error message to append.
        """
        if not self._message_ts or not self._action_text:
            return

        action_text = self._action_text
        if error_message:
            action_text = f"{action_text} ({error_message[:50]})"

        blocks = build_single_task_blocks(action_text, status="error")

        try:
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_update(
                    channel=self.channel_id,
                    ts=self._message_ts,
                    text=f"Failed: {action_text}",
                    blocks=blocks,
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_update,
                    channel=self.channel_id,
                    ts=self._message_ts,
                    text=f"Failed: {action_text}",
                    blocks=blocks,
                )
            logger.debug(
                "Updated single-task status to error",
                extra={
                    "message_ts": self._message_ts,
                    "error_message": error_message,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to update single-task status to error: {e}")

    async def delete(self) -> None:
        """Delete the status card.

        Used for fast responses where the card would just be clutter.
        """
        if not self._message_ts:
            return

        try:
            if isinstance(self.client, AsyncWebClient):
                await self.client.chat_delete(
                    channel=self.channel_id,
                    ts=self._message_ts,
                )
            else:
                # Sync client - run in thread to avoid blocking
                await asyncio.to_thread(
                    self.client.chat_delete,
                    channel=self.channel_id,
                    ts=self._message_ts,
                )
            logger.debug(
                "Deleted single-task status card",
                extra={"message_ts": self._message_ts},
            )
            self._message_ts = None
        except Exception as e:
            # Deletion failures are common (message already deleted, permissions)
            logger.debug(f"Could not delete single-task status card: {e}")

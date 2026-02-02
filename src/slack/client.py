"""Slack client wrapper with message type routing and rate limiting.

Ref: Spec Part 9.2 - Slack Client
Ref: RESEARCH.md - Rate-Limited Client Wrapper
"""
import asyncio
import logging
from typing import Union

from slack_sdk.web.async_client import AsyncWebClient

from src.domain.types import ChannelId, ThreadTs, UserId
from src.slack.types import SlackMessage, SlackWriteTarget, WRITE_TARGETS

logger = logging.getLogger(__name__)

# Type alias for content (text or blocks)
Content = Union[str, list[dict]]


class RateLimiter:
    """Simple rate limiter for Slack API calls.

    Ref: RESEARCH.md - Pitfall 2 (Rate Limit Violations)
    Slack allows ~1 msg/sec per channel. We use a global limiter for simplicity.
    """

    def __init__(self, calls_per_second: float = 1.0):
        self.semaphore = asyncio.Semaphore(1)
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0

    async def acquire(self) -> None:
        """Wait until rate limit allows another call."""
        async with self.semaphore:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = self.min_interval - (now - self.last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_call = loop.time()


class SlackClient:
    """Wrapper for Slack API with message type routing.

    Ref: Spec Part 9.2
    """

    def __init__(self, client: AsyncWebClient):
        self.client = client
        self._rate_limiter = RateLimiter(calls_per_second=1.0)

    async def send(
        self,
        message_type: str,
        channel_id: ChannelId,
        content: Content,
        thread_ts: ThreadTs | None = None,
        user_id: UserId | None = None,
    ) -> SlackMessage | None:
        """Send message to appropriate target based on type.

        This is the main entry point. Routes to channel/thread/ephemeral
        based on WRITE_TARGETS mapping.
        """
        target = WRITE_TARGETS.get(message_type, SlackWriteTarget.THREAD)

        match target:
            case SlackWriteTarget.CHANNEL:
                return await self.post_to_channel(channel_id, content)
            case SlackWriteTarget.THREAD:
                if not thread_ts:
                    raise ValueError(f"Thread target requires thread_ts: {message_type}")
                return await self.post_to_thread(channel_id, thread_ts, content)
            case SlackWriteTarget.EPHEMERAL:
                if not user_id:
                    raise ValueError(f"Ephemeral target requires user_id: {message_type}")
                await self.post_ephemeral(channel_id, user_id, content, thread_ts)
                return None

    async def post_to_channel(
        self,
        channel_id: ChannelId,
        content: Content,
    ) -> SlackMessage:
        """Post to channel (visible to all)."""
        await self._rate_limiter.acquire()

        kwargs: dict = {"channel": channel_id}
        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "New update"  # Fallback for notifications

        result = await self.client.chat_postMessage(**kwargs)
        return SlackMessage(
            ts=result["ts"],
            channel_id=channel_id,
            text=kwargs.get("text", ""),
        )

    async def post_to_thread(
        self,
        channel_id: ChannelId,
        thread_ts: ThreadTs,
        content: Content,
    ) -> SlackMessage:
        """Post to thread."""
        await self._rate_limiter.acquire()

        kwargs: dict = {"channel": channel_id, "thread_ts": thread_ts}
        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "Update"

        result = await self.client.chat_postMessage(**kwargs)
        return SlackMessage(
            ts=result["ts"],
            channel_id=channel_id,
            text=kwargs.get("text", ""),
            thread_ts=thread_ts,
        )

    async def post_ephemeral(
        self,
        channel_id: ChannelId,
        user_id: UserId,
        content: Content,
        thread_ts: ThreadTs | None = None,
    ) -> None:
        """Post ephemeral message (only visible to user)."""
        await self._rate_limiter.acquire()

        kwargs: dict = {"channel": channel_id, "user": user_id}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "Info"

        await self.client.chat_postEphemeral(**kwargs)

    async def update_message(
        self,
        channel_id: ChannelId,
        ts: str,
        content: Content,
    ) -> None:
        """Update existing message."""
        await self._rate_limiter.acquire()

        kwargs: dict = {"channel": channel_id, "ts": ts}
        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "Updated"

        await self.client.chat_update(**kwargs)

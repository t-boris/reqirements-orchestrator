"""Response gate — decides whether handle_message should respond.

The bot responds to a regular message (non-@mention) ONLY when:
- DM (channel_type == "im") - always respond
- Bot thread - a thread where the bot has previously posted
- Entity thread - a thread with linked entities (proposals, decisions)

Top-level channel messages and threads the bot hasn't participated in
are blocked to avoid disrupting human-to-human conversations.

Ref: .planning/ISSUES.md ISS-009, ISS-010
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class GateResult(Enum):
    """Outcome of the response gate check."""
    DIRECT_MESSAGE = "direct_message"
    BOT_THREAD = "bot_thread"
    ENTITY_THREAD = "entity_thread"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class GateOutput:
    """Result of check_response_gate()."""
    result: GateResult
    reason: str


class BotThreadTracker:
    """Tracks threads where the bot has posted.

    Three-tier lookup:
    1. In-memory set (O(1)) - populated when bot posts via say()
    2. Entity store (DB query on cache miss) - get_entities_in_thread()
    3. Slack API (fallback) - conversations_replies(limit=10), check for bot_id

    Results cached (positive + negative) to avoid repeated lookups.
    """

    def __init__(self) -> None:
        # channel_id -> set of thread_ts where bot has posted
        self._known_threads: dict[str, set[str]] = {}
        # channel_id -> set of thread_ts confirmed as non-bot threads
        self._negative_cache: dict[str, set[str]] = {}

    def record_bot_response(self, channel_id: str, thread_ts: str) -> None:
        """Record that the bot posted in a thread."""
        if not thread_ts:
            return
        self._known_threads.setdefault(channel_id, set()).add(thread_ts)
        # Remove from negative cache if present
        neg = self._negative_cache.get(channel_id)
        if neg:
            neg.discard(thread_ts)

    def is_known_bot_thread(self, channel_id: str, thread_ts: str) -> bool:
        """Check if thread is a known bot thread (in-memory)."""
        return thread_ts in self._known_threads.get(channel_id, set())

    def is_known_non_bot_thread(self, channel_id: str, thread_ts: str) -> bool:
        """Check if thread was previously confirmed as non-bot."""
        return thread_ts in self._negative_cache.get(channel_id, set())

    def cache_negative(self, channel_id: str, thread_ts: str) -> None:
        """Cache a thread as confirmed non-bot thread."""
        self._negative_cache.setdefault(channel_id, set()).add(thread_ts)


# Module-level singleton
_tracker: BotThreadTracker | None = None


def get_tracker() -> BotThreadTracker:
    """Get the module-level BotThreadTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = BotThreadTracker()
    return _tracker


async def check_response_gate(event: dict, client) -> GateOutput:
    """Decide whether handle_message should respond to this event.

    Args:
        event: Slack message event dict
        client: Slack AsyncWebClient (for API fallback)

    Returns:
        GateOutput with result and reason
    """
    channel_type = event.get("channel_type", "")
    channel_id = event.get("channel", "")
    thread_ts = event.get("thread_ts")

    # 1. DMs - always respond
    if channel_type == "im":
        return GateOutput(GateResult.DIRECT_MESSAGE, "Direct message")

    # 2. No thread_ts - top-level channel message, block
    if not thread_ts:
        return GateOutput(GateResult.BLOCKED, "Top-level channel message (no @mention)")

    # 3. In-memory known bot thread
    tracker = get_tracker()
    if tracker.is_known_bot_thread(channel_id, thread_ts):
        return GateOutput(GateResult.BOT_THREAD, "Known bot thread (in-memory)")

    # 4. Negative cache - previously confirmed non-bot thread
    if tracker.is_known_non_bot_thread(channel_id, thread_ts):
        return GateOutput(GateResult.BLOCKED, "Known non-bot thread (cached)")

    # 5. Entity store - check for linked entities in thread
    try:
        from src.infrastructure.aggregate_loader import load_aggregate

        aggregate = await load_aggregate(channel_id)
        from src.domain.types import ThreadTs as ThreadTsType

        entities = aggregate.get_entities_in_thread(ThreadTsType(thread_ts))
        if entities:
            # Entity thread - also record as bot thread for future lookups
            tracker.record_bot_response(channel_id, thread_ts)
            return GateOutput(GateResult.ENTITY_THREAD, f"Thread has {len(entities)} linked entities")
    except Exception as e:
        logger.debug(f"Entity store lookup failed: {e}")

    # 6. Slack API fallback - check if bot has posted in thread
    try:
        replies = await client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=10,
        )
        messages = replies.get("messages", [])
        for msg in messages:
            if msg.get("bot_id"):
                tracker.record_bot_response(channel_id, thread_ts)
                return GateOutput(GateResult.BOT_THREAD, "Bot found in thread history (API)")
    except Exception as e:
        logger.debug(f"Slack API thread check failed: {e}")

    # 7. Nothing found - block and cache negative
    tracker.cache_negative(channel_id, thread_ts)
    return GateOutput(GateResult.BLOCKED, "Thread without bot participation")

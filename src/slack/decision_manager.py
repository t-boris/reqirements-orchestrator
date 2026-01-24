"""Decision Manager - Canonical message pattern for decisions.

Philosophy from CONTEXT.md:
- Each Decision has ONE canonical message in the channel (pinned)
- All discussion happens in the thread under this message
- When decision changes, the canonical message is UPDATED (not new message)
- The channel is not a log of what happened — it's a representation of what IS TRUE NOW

The canonical message is like HEAD in git. It always shows the current active version.
"""
import logging
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

from src.db.connection import get_connection
from src.db.decision_store import DecisionStore
from src.schemas.decision import Decision

logger = logging.getLogger(__name__)


class DecisionManager:
    """Manages canonical Slack messages for decisions.

    Ensures each decision has exactly one message that reflects current truth.

    ARCHITECTURE:
    - Database is truth
    - Jira is projection
    - Slack is presentation (UI layer)

    FAILURE TOLERANCE:
    - Message update failures are logged, not raised
    - Caller can continue with approval/sync regardless of Slack
    - Retries are safe (idempotent updates)
    """

    def __init__(self, client: AsyncWebClient):
        self._client = client

    async def post_canonical_message(
        self,
        decision: Decision,
        blocks: list[dict],
    ) -> str:
        """Post the canonical message for a new decision.

        This message becomes the single source of truth for this decision.
        Should be pinned for visibility.

        Args:
            decision: The Decision entity
            blocks: Slack blocks for the decision card

        Returns:
            Message timestamp (ts) of the canonical message
        """
        response = await self._client.chat_postMessage(
            channel=decision.channel_id,
            blocks=blocks,
            text=f"Decision: {decision.title}",  # Fallback text
        )

        message_ts = response["ts"]

        # Update decision with canonical message reference
        async with get_connection() as conn:
            store = DecisionStore(conn)
            await store.set_canonical_message(
                decision_id=decision.id,
                message_ts=message_ts,
            )

        logger.info(
            "Posted canonical message for decision",
            extra={
                "decision_id": decision.id,
                "message_ts": message_ts,
                "channel_id": decision.channel_id,
            }
        )

        return message_ts

    async def update_canonical_message(
        self,
        decision: Decision,
        blocks: list[dict],
        expected_version: int | None = None,
    ) -> bool:
        """Update canonical message with idempotency guarantee.

        IDEMPOTENT: Same version produces same blocks. Safe to retry.
        VERSION-CHECKED: Stale updates are skipped silently.
        FAILURE-SAFE: Update failure doesn't change decision state.

        This is the "update in place" pattern — the message moves in time.

        Args:
            decision: The updated Decision entity
            blocks: New Slack blocks for the decision card
            expected_version: For idempotency check - if provided and doesn't
                match decision.version, update is skipped (stale)

        Returns:
            True if updated (or skipped as stale), False if no canonical message
            or Slack API error
        """
        if not decision.canonical_message_ts:
            logger.warning(
                "No canonical message to update",
                extra={"decision_id": decision.id}
            )
            return False

        # Version check for idempotency
        if expected_version is not None and decision.version != expected_version:
            logger.warning(
                "Skipping stale update: expected v%d, decision at v%d",
                expected_version,
                decision.version,
                extra={
                    "decision_id": decision.id,
                    "expected_version": expected_version,
                    "actual_version": decision.version,
                }
            )
            # Stale update is success - no action needed
            return True

        try:
            await self._client.chat_update(
                channel=decision.channel_id,
                ts=decision.canonical_message_ts,
                blocks=blocks,
                text=f"Decision: {decision.title}",
            )

            logger.info(
                "Updated canonical message for decision",
                extra={
                    "decision_id": decision.id,
                    "version": decision.version,
                    "status": decision.status.value,
                }
            )
            return True

        except Exception as e:
            # Log error but don't raise - Slack is presentation layer
            # Architecture: Database (truth) → Jira (projection) → Slack (presentation)
            logger.error(
                "Failed to update canonical message",
                extra={
                    "decision_id": decision.id,
                    "error": str(e),
                }
            )
            return False

    async def post_to_discussion_thread(
        self,
        decision: Decision,
        text: str,
        blocks: list[dict] | None = None,
    ) -> str | None:
        """Post to the discussion thread under the canonical message.

        All discussion, version previews, and confirmations go in the thread.

        Args:
            decision: The Decision entity
            text: Message text
            blocks: Optional Slack blocks

        Returns:
            Thread message ts, or None if no canonical message exists
        """
        if not decision.canonical_message_ts:
            logger.warning(
                "No canonical message for thread post",
                extra={"decision_id": decision.id}
            )
            return None

        response = await self._client.chat_postMessage(
            channel=decision.channel_id,
            thread_ts=decision.canonical_message_ts,
            blocks=blocks,
            text=text,
        )

        return response["ts"]

    async def mark_deprecated(
        self,
        decision: Decision,
        replacement_decision: Decision | None = None,
    ) -> bool:
        """Update canonical message to show deprecated status.

        The message is not deleted — it's marked as historical with pointer to replacement.

        Args:
            decision: The deprecated Decision
            replacement_decision: Optional replacement Decision

        Returns:
            True if updated successfully
        """
        from src.slack.blocks.decision_cards import build_deprecated_decision_blocks

        blocks = build_deprecated_decision_blocks(
            decision=decision,
            replacement=replacement_decision,
        )

        return await self.update_canonical_message(decision, blocks)

    async def pin_canonical_message(
        self,
        decision: Decision,
    ) -> bool:
        """Pin the canonical message for visibility.

        Pinned decisions appear in channel bookmarks.
        """
        if not decision.canonical_message_ts:
            return False

        try:
            await self._client.pins_add(
                channel=decision.channel_id,
                timestamp=decision.canonical_message_ts,
            )
            return True
        except Exception as e:
            # Already pinned or other error
            logger.debug(f"Could not pin message: {e}")
            return False

    async def get_decision_for_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Decision | None:
        """Get the decision associated with a thread.

        When user posts in a decision's discussion thread, we need to know
        which decision they're discussing.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp (parent message ts)

        Returns:
            Decision if thread is a decision discussion, None otherwise
        """
        async with get_connection() as conn:
            store = DecisionStore(conn)
            # Query by canonical_message_ts (thread parent)
            return await store.get_by_canonical_message(
                channel_id=channel_id,
                message_ts=thread_ts,
            )

    async def is_decision_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if a thread is a decision discussion thread."""
        decision = await self.get_decision_for_thread(channel_id, thread_ts)
        return decision is not None

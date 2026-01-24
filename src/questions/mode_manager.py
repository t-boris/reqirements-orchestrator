"""Mode manager for Active/Passive conversation mode.

Centralizes mode transition logic and timeout handling.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.db.conversation_mode_store import ConversationModeStore
from src.schemas.conversation_mode import (
    ConversationMode,
    ConversationModeState,
    ModeTransitionReason,
    should_activate,
    should_deactivate,
)

logger = logging.getLogger(__name__)

# Timeout for automatic deactivation (10 minutes)
MODE_TIMEOUT_MINUTES = 10


class ModeManager:
    """Manage conversation mode transitions.

    Handles:
    - Detecting when to activate (mention, command, blocked)
    - Detecting when to deactivate (complete, timeout, cancel)
    - Checking current mode state
    - Timeout enforcement
    """

    def __init__(self, store: ConversationModeStore) -> None:
        self._store = store

    async def check_and_activate(
        self,
        channel_id: str,
        thread_ts: str,
        reason: ModeTransitionReason,
    ) -> bool:
        """Check if should activate and do so.

        Returns True if transitioned to ACTIVE.
        """
        if not should_activate(reason):
            return False

        state = await self._store.get_or_create(channel_id, thread_ts)

        if state.mode == ConversationMode.ACTIVE:
            # Already active, just update activity
            await self._store.update_activity(channel_id, thread_ts)
            return False

        await self._store.transition(channel_id, thread_ts, ConversationMode.ACTIVE, reason)
        logger.info(f"Activated mode for {channel_id}/{thread_ts}: {reason}")
        return True

    async def check_and_deactivate(
        self,
        channel_id: str,
        thread_ts: str,
        reason: ModeTransitionReason,
    ) -> bool:
        """Check if should deactivate and do so.

        Returns True if transitioned to PASSIVE.
        """
        if not should_deactivate(reason):
            return False

        state = await self._store.get_or_create(channel_id, thread_ts)

        if state.mode == ConversationMode.PASSIVE:
            return False

        await self._store.transition(channel_id, thread_ts, ConversationMode.PASSIVE, reason)
        logger.info(f"Deactivated mode for {channel_id}/{thread_ts}: {reason}")
        return True

    async def check_timeout(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if mode should timeout due to inactivity.

        Returns True if timed out and deactivated.
        """
        state = await self._store.get_or_create(channel_id, thread_ts)

        if state.mode != ConversationMode.ACTIVE:
            return False

        timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=MODE_TIMEOUT_MINUTES)

        if state.last_activity < timeout_threshold:
            await self._store.transition(
                channel_id,
                thread_ts,
                ConversationMode.PASSIVE,
                ModeTransitionReason.TIMEOUT,
            )
            logger.info(f"Mode timed out for {channel_id}/{thread_ts}")
            return True

        return False

    async def is_active(self, channel_id: str, thread_ts: str) -> bool:
        """Check if currently in ACTIVE mode."""
        state = await self._store.get_or_create(channel_id, thread_ts)
        return state.mode == ConversationMode.ACTIVE

    async def get_state(self, channel_id: str, thread_ts: str) -> ConversationModeState:
        """Get current mode state."""
        return await self._store.get_or_create(channel_id, thread_ts)

    async def record_activity(self, channel_id: str, thread_ts: str) -> None:
        """Record user activity (updates last_activity timestamp)."""
        await self._store.update_activity(channel_id, thread_ts)


def detect_activation_reason(
    message: str,
    bot_user_id: str,
    is_command: bool = False,
) -> Optional[ModeTransitionReason]:
    """Detect if message should activate bot.

    Args:
        message: Message text
        bot_user_id: Bot's Slack user ID
        is_command: True if this is a /command

    Returns:
        ModeTransitionReason if should activate, None otherwise
    """
    if is_command:
        return ModeTransitionReason.COMMAND

    # Check for @mention
    if f"<@{bot_user_id}>" in message:
        return ModeTransitionReason.MENTION

    return None

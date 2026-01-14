"""Session identity and state management for Slack threads."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Per-session locks to serialize processing
_session_locks: dict[str, asyncio.Lock] = {}


@dataclass
class SessionIdentity:
    """Canonical session identity from Slack event."""

    team_id: str
    channel_id: str
    thread_ts: str  # Thread timestamp (parent message ts)

    @property
    def session_id(self) -> str:
        """Canonical session ID: team:channel:thread_ts"""
        return f"{self.team_id}:{self.channel_id}:{self.thread_ts}"

    @classmethod
    def from_event(cls, event: dict, team_id: str) -> Optional["SessionIdentity"]:
        """Extract session identity from Slack event.

        Returns None if not a thread message (no session context).
        """
        channel_id = event.get("channel")
        # thread_ts if in thread, else ts if starting new thread
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not channel_id or not thread_ts:
            return None

        return cls(
            team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )


def get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create lock for session.

    Ensures one run at a time per thread to prevent race conditions.
    """
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


async def with_session_lock(session_id: str):
    """Async context manager for session lock.

    Usage:
        async with with_session_lock(session_id):
            # process session
    """
    lock = get_session_lock(session_id)
    async with lock:
        yield


def cleanup_session_lock(session_id: str) -> None:
    """Remove session lock when session is closed.

    Call when thread is archived or session completed.
    """
    if session_id in _session_locks:
        del _session_locks[session_id]
        logger.debug(f"Cleaned up lock for session {session_id}")

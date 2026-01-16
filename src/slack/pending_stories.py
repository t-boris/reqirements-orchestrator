"""Pending story creation store.

Stores generated stories temporarily until user confirms/cancels.
MVP: In-memory storage with 1-hour TTL.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# TTL for pending stories (1 hour)
PENDING_STORIES_TTL = timedelta(hours=1)


@dataclass
class PendingStories:
    """Pending story creation data."""

    id: str
    epic_key: str
    stories: list[dict]
    created_at: datetime = field(default_factory=datetime.utcnow)


class PendingStoriesStore:
    """Store pending story creations.

    MVP: In-memory dict storage with TTL cleanup.
    """

    def __init__(self):
        """Initialize empty store."""
        self._pending: dict[str, PendingStories] = {}

    def store(self, epic_key: str, stories: list[dict]) -> str:
        """Store pending stories and return ID.

        Args:
            epic_key: The epic to create stories under
            stories: List of story dicts with title, description, acceptance_criteria

        Returns:
            Unique ID to retrieve the stories later
        """
        self._cleanup_expired()

        pending_id = str(uuid.uuid4())[:8]  # Short ID for button value
        pending = PendingStories(
            id=pending_id,
            epic_key=epic_key,
            stories=stories,
        )
        self._pending[pending_id] = pending

        logger.info(
            "Stored pending stories",
            extra={
                "pending_id": pending_id,
                "epic_key": epic_key,
                "story_count": len(stories),
            },
        )

        return pending_id

    def get(self, pending_id: str) -> Optional[PendingStories]:
        """Retrieve pending stories by ID.

        Args:
            pending_id: ID returned by store()

        Returns:
            PendingStories if found and not expired, None otherwise
        """
        self._cleanup_expired()
        return self._pending.get(pending_id)

    def remove(self, pending_id: str) -> bool:
        """Remove pending stories after use.

        Args:
            pending_id: ID to remove

        Returns:
            True if removed, False if not found
        """
        if pending_id in self._pending:
            del self._pending[pending_id]
            logger.info(f"Removed pending stories: {pending_id}")
            return True
        return False

    def _cleanup_expired(self):
        """Remove expired entries."""
        now = datetime.utcnow()
        expired = [
            pid
            for pid, pending in self._pending.items()
            if now - pending.created_at > PENDING_STORIES_TTL
        ]
        for pid in expired:
            del self._pending[pid]
            logger.debug(f"Cleaned up expired pending stories: {pid}")


# Global singleton
_store: Optional[PendingStoriesStore] = None


def get_pending_stories_store() -> PendingStoriesStore:
    """Get or create global PendingStoriesStore singleton."""
    global _store
    if _store is None:
        _store = PendingStoriesStore()
    return _store

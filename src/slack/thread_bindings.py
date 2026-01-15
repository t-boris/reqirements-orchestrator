"""Thread to Jira ticket binding store.

Manages thread → Jira ticket bindings for duplicate linking.
MVP: In-memory storage. Can migrate to DB later.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ThreadBinding:
    """A binding between a Slack thread and a Jira ticket."""

    channel_id: str
    thread_ts: str
    issue_key: str
    bound_at: datetime
    bound_by: str  # Slack user ID


class ThreadBindingStore:
    """Store thread → Jira ticket bindings.

    MVP: In-memory dict storage. Thread-safe for single process.
    """

    def __init__(self):
        """Initialize empty binding store."""
        # Key format: "channel_id:thread_ts"
        self._bindings: dict[str, ThreadBinding] = {}

    def _make_key(self, channel_id: str, thread_ts: str) -> str:
        """Create storage key from channel and thread."""
        return f"{channel_id}:{thread_ts}"

    async def bind(
        self,
        channel_id: str,
        thread_ts: str,
        issue_key: str,
        bound_by: str,
    ) -> ThreadBinding:
        """Bind a thread to a Jira ticket.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            issue_key: Jira issue key to link to
            bound_by: Slack user ID who created the binding

        Returns:
            Created ThreadBinding
        """
        key = self._make_key(channel_id, thread_ts)

        binding = ThreadBinding(
            channel_id=channel_id,
            thread_ts=thread_ts,
            issue_key=issue_key,
            bound_at=datetime.utcnow(),
            bound_by=bound_by,
        )

        self._bindings[key] = binding

        logger.info(
            "Thread bound to Jira ticket",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "issue_key": issue_key,
                "bound_by": bound_by,
            },
        )

        return binding

    async def get_binding(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ThreadBinding]:
        """Get binding for a thread if exists.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            ThreadBinding if exists, None otherwise
        """
        key = self._make_key(channel_id, thread_ts)
        return self._bindings.get(key)

    async def unbind(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Remove binding for a thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            True if binding existed and was removed, False otherwise
        """
        key = self._make_key(channel_id, thread_ts)

        if key in self._bindings:
            del self._bindings[key]
            logger.info(
                "Thread unbound from Jira ticket",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                },
            )
            return True

        return False


# Global singleton for MVP
_binding_store: Optional[ThreadBindingStore] = None


def get_binding_store() -> ThreadBindingStore:
    """Get or create global ThreadBindingStore singleton."""
    global _binding_store
    if _binding_store is None:
        _binding_store = ThreadBindingStore()
    return _binding_store

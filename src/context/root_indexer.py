"""Root message indexer for channel activity tracking."""
import logging
import re
from typing import Optional

from psycopg import AsyncConnection

from src.db.models import RootIndex
from src.db.root_index_store import RootIndexStore

logger = logging.getLogger(__name__)


class RootIndexer:
    """Indexes root messages (thread starters) for channel context.

    Called when:
    - New thread detected (index root)
    - Epic bound to thread (link_epic)
    - Ticket created (add_ticket)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._store = RootIndexStore(conn)

    async def on_new_thread(
        self,
        team_id: str,
        channel_id: str,
        root_ts: str,
        root_text: str,
    ) -> RootIndex:
        """Index a new thread's root message.

        Args:
            team_id: Slack team ID.
            channel_id: Slack channel ID.
            root_ts: Root message timestamp.
            root_text: Text of root message.

        Returns:
            Created or updated RootIndex.
        """
        # Extract summary (first 100 chars, clean)
        summary = self._extract_summary(root_text)

        # Extract entities (simple: @mentions, #channels, ticket keys)
        entities = self._extract_entities(root_text)

        return await self._store.index_root(
            team_id=team_id,
            channel_id=channel_id,
            root_ts=root_ts,
            text_summary=summary,
            entities=entities,
        )

    async def on_epic_bound(
        self,
        team_id: str,
        channel_id: str,
        root_ts: str,
        epic_id: str,
    ) -> RootIndex:
        """Update index when epic is bound to thread."""
        return await self._store.link_epic(team_id, channel_id, root_ts, epic_id)

    async def on_ticket_created(
        self,
        team_id: str,
        channel_id: str,
        root_ts: str,
        ticket_key: str,
    ) -> RootIndex:
        """Update index when ticket is created from thread."""
        return await self._store.add_ticket(team_id, channel_id, root_ts, ticket_key)

    def _extract_summary(self, text: str) -> str:
        """Extract brief summary from root text."""
        # Clean whitespace, take first 100 chars
        clean = " ".join(text.split())
        return clean[:100] + ("..." if len(clean) > 100 else "")

    def _extract_entities(self, text: str) -> list[str]:
        """Extract @mentions, #channels, PROJ-123 patterns."""
        entities = []

        # @mentions
        mentions = re.findall(r"<@(\w+)>", text)
        entities.extend([f"@{m}" for m in mentions[:5]])

        # #channels
        channels = re.findall(r"<#(\w+)\|[^>]+>", text)
        entities.extend([f"#{c}" for c in channels[:3]])

        # Ticket keys (PROJ-123)
        tickets = re.findall(r"\b([A-Z]+-\d+)\b", text)
        entities.extend(tickets[:5])

        return entities[:10]  # Max 10 entities

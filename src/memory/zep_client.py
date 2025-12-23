"""
Zep Memory Client - Long-term memory with temporal knowledge graph.

Provides:
- Per-channel session isolation
- Message storage with metadata
- Fact extraction and retrieval
- Semantic search across memories
"""

from typing import Any

import structlog
from zep_python import ZepClient
from zep_python.memory import Memory, Message, Session
from zep_python.exceptions import NotFoundError

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# Zep Client Singleton
# =============================================================================

_client: ZepClient | None = None


async def get_zep_client() -> "ZepMemoryClient":
    """
    Get or create the singleton Zep client wrapper.

    Returns:
        ZepMemoryClient instance.
    """
    global _client

    if _client is None:
        _client = ZepClient(base_url=settings.zep_api_url)
        logger.info("zep_client_initialized", url=settings.zep_api_url)

    return ZepMemoryClient(_client)


# =============================================================================
# Memory Client Wrapper
# =============================================================================


class ZepMemoryClient:
    """
    Wrapper around Zep client with convenience methods for requirements workflow.

    Handles session management, message storage, and semantic search.
    """

    def __init__(self, client: ZepClient):
        """
        Initialize the memory client.

        Args:
            client: Zep client instance.
        """
        self.client = client
        self.memory = MemoryOperations(client)
        self.facts = FactOperations(client)

    async def ensure_session(self, channel_id: str, user_id: str | None = None) -> str:
        """
        Ensure a session exists for the channel.

        Creates session if it doesn't exist.

        Args:
            channel_id: Slack channel ID.
            user_id: Optional user ID for session metadata.

        Returns:
            Session ID.
        """
        session_id = f"channel-{channel_id}"

        try:
            await self.client.memory.aget_session(session_id)
        except NotFoundError:
            session = Session(
                session_id=session_id,
                metadata={
                    "channel_id": channel_id,
                    "created_by": user_id,
                    "type": "slack_channel",
                },
            )
            await self.client.memory.aadd_session(session)
            logger.info("zep_session_created", session_id=session_id)

        return session_id

    async def close(self) -> None:
        """Close the Zep client connection."""
        if self.client:
            await self.client.aclose()


# =============================================================================
# Memory Operations
# =============================================================================


class MemoryOperations:
    """
    Memory operations for storing and retrieving conversation history.
    """

    def __init__(self, client: ZepClient):
        self.client = client

    async def add(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """
        Add messages to a session's memory.

        Args:
            session_id: Zep session ID.
            messages: List of message dicts with role, content, and optional metadata.
        """
        zep_messages = []
        for msg in messages:
            zep_messages.append(
                Message(
                    role=msg.get("role", "user"),
                    role_type=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    metadata=msg.get("metadata", {}),
                )
            )

        memory = Memory(messages=zep_messages)
        await self.client.memory.aadd_memory(session_id, memory)

        logger.debug(
            "memory_added",
            session_id=session_id,
            message_count=len(messages),
        )

    async def get(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get recent messages from a session.

        Args:
            session_id: Zep session ID.
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts.
        """
        try:
            memory = await self.client.memory.aget_memory(session_id)

            messages = []
            for msg in (memory.messages or [])[-limit:]:
                messages.append({
                    "role": msg.role,
                    "content": msg.content,
                    "metadata": msg.metadata or {},
                    "created_at": msg.created_at,
                })

            return messages

        except NotFoundError:
            return []

    async def search(
        self,
        session_id: str,
        text: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Semantic search across session memories.

        Args:
            session_id: Zep session ID.
            text: Search query text.
            limit: Maximum results to return.

        Returns:
            List of search results with relevance scores.
        """
        try:
            results = await self.client.memory.asearch_memory(
                session_id=session_id,
                text=text,
                limit=limit,
            )

            memories = []
            for result in results:
                if result.message:
                    memories.append({
                        "content": result.message.content,
                        "role": result.message.role,
                        "score": result.score,
                        "metadata": result.message.metadata or {},
                        "created_at": result.message.created_at,
                    })

            return memories

        except NotFoundError:
            return []

    async def clear(self, session_id: str) -> bool:
        """
        Clear all memory for a session.

        Args:
            session_id: Zep session ID.

        Returns:
            True if successful.
        """
        try:
            await self.client.memory.adelete_memory(session_id)
            logger.info("memory_cleared", session_id=session_id)
            return True
        except NotFoundError:
            return True  # Already cleared


# =============================================================================
# Fact Operations
# =============================================================================


class FactOperations:
    """
    Fact operations for the temporal knowledge graph.

    Facts are extracted entities and relationships from conversations.
    """

    def __init__(self, client: ZepClient):
        self.client = client

    async def get_facts(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get extracted facts for a session.

        Args:
            session_id: Zep session ID.

        Returns:
            List of fact dicts.
        """
        try:
            memory = await self.client.memory.aget_memory(session_id)

            facts = []
            for fact in memory.facts or []:
                facts.append({
                    "content": fact.fact,
                    "created_at": fact.created_at,
                })

            return facts

        except NotFoundError:
            return []

    async def add_fact(
        self,
        session_id: str,
        fact_content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Manually add a fact to the knowledge graph.

        Note: Zep typically extracts facts automatically, but this allows
        explicit addition for requirements and decisions.

        Args:
            session_id: Zep session ID.
            fact_content: The fact to add.
            metadata: Optional metadata.
        """
        # Add as a system message that will be processed by Zep
        memory = Memory(
            messages=[
                Message(
                    role="system",
                    role_type="system",
                    content=f"[FACT] {fact_content}",
                    metadata=metadata or {},
                )
            ]
        )
        await self.client.memory.aadd_memory(session_id, memory)

        logger.debug("fact_added", session_id=session_id, fact=fact_content[:50])


# =============================================================================
# Utility Functions
# =============================================================================


async def store_requirement(
    channel_id: str,
    requirement: dict[str, Any],
    user_id: str,
    jira_key: str | None = None,
) -> None:
    """
    Store a completed requirement in memory.

    Creates a structured memory entry for the requirement.

    Args:
        channel_id: Slack channel ID.
        requirement: Requirement dict with title, description, etc.
        user_id: User who created the requirement.
        jira_key: Optional Jira issue key.
    """
    client = await get_zep_client()
    session_id = await client.ensure_session(channel_id, user_id)

    content = f"""Requirement created:
Title: {requirement.get('title', 'Untitled')}
Type: {requirement.get('issue_type', 'Story')}
Description: {requirement.get('description', '')}
Acceptance Criteria: {', '.join(requirement.get('acceptance_criteria', []))}
Jira: {jira_key or 'Not synced'}"""

    await client.memory.add(
        session_id=session_id,
        messages=[
            {
                "role": "assistant",
                "content": content,
                "metadata": {
                    "type": "requirement",
                    "jira_key": jira_key,
                    "user_id": user_id,
                    "issue_type": requirement.get("issue_type"),
                },
            }
        ],
    )

    logger.info(
        "requirement_stored",
        channel_id=channel_id,
        title=requirement.get("title"),
        jira_key=jira_key,
    )


async def get_relevant_context(
    channel_id: str,
    message: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Get relevant context for a message from memory.

    Combines semantic search results with recent facts.

    Args:
        channel_id: Slack channel ID.
        message: Current message to find context for.
        limit: Maximum results per category.

    Returns:
        Dict with 'memories' and 'facts' lists.
    """
    client = await get_zep_client()
    session_id = f"channel-{channel_id}"

    try:
        # Get semantic search results
        memories = await client.memory.search(
            session_id=session_id,
            text=message,
            limit=limit,
        )

        # Get recent facts
        facts = await client.facts.get_facts(session_id)

        return {
            "memories": memories,
            "facts": facts[-limit:],  # Most recent facts
            "session_id": session_id,
        }

    except Exception as e:
        logger.warning("context_retrieval_failed", error=str(e))
        return {
            "memories": [],
            "facts": [],
            "session_id": session_id,
        }


async def clear_channel_memory(channel_id: str) -> bool:
    """
    Clear all memory for a channel.

    Used by /req-clean command.

    Args:
        channel_id: Slack channel ID.

    Returns:
        True if successful.
    """
    client = await get_zep_client()
    session_id = f"channel-{channel_id}"

    try:
        await client.memory.clear(session_id)
        logger.info("channel_memory_cleared", channel_id=channel_id)
        return True
    except Exception as e:
        logger.error("memory_clear_failed", channel_id=channel_id, error=str(e))
        return False

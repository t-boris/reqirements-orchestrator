"""
Zep Memory Client - Long-term memory with temporal knowledge graph.

Provides:
- Per-channel session isolation
- Message storage with metadata
- Fact extraction and retrieval
- Semantic search across memories

Note: Using direct HTTP requests to Zep CE API (no zep-python due to httpx conflicts).
"""

from typing import Any

import httpx
import structlog

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# Zep HTTP Client Singleton
# =============================================================================

_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Get or create the HTTP client for Zep."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.zep_api_url,
            timeout=30.0,
        )
        logger.info("zep_http_client_initialized", url=settings.zep_api_url)
    return _client


async def get_zep_client() -> "ZepMemoryClient":
    """
    Get or create the singleton Zep client wrapper.

    Returns:
        ZepMemoryClient instance.
    """
    client = await get_http_client()
    return ZepMemoryClient(client)


# =============================================================================
# Memory Client Wrapper
# =============================================================================


class ZepMemoryClient:
    """
    Wrapper around Zep HTTP API with convenience methods for requirements workflow.

    Handles session management, message storage, and semantic search.
    Uses direct HTTP requests to Zep CE API.
    """

    def __init__(self, client: httpx.AsyncClient):
        """
        Initialize the memory client.

        Args:
            client: httpx AsyncClient for Zep API.
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
            # Try to get existing session
            response = await self.client.get(f"/api/v1/sessions/{session_id}")
            if response.status_code == 200:
                return session_id
        except Exception:
            pass

        # Session doesn't exist, create it
        try:
            response = await self.client.post(
                "/api/v1/sessions",
                json={
                    "session_id": session_id,
                    "metadata": {
                        "channel_id": channel_id,
                        "created_by": user_id,
                        "type": "slack_channel",
                    },
                },
            )
            if response.status_code in (200, 201):
                logger.info("zep_session_created", session_id=session_id)
        except Exception as e:
            logger.debug("session_create_skipped", error=str(e))

        return session_id

    async def close(self) -> None:
        """Close the HTTP client connection."""
        global _client
        if _client is not None:
            await _client.aclose()
            _client = None


# =============================================================================
# Memory Operations
# =============================================================================


class MemoryOperations:
    """
    Memory operations for storing and retrieving conversation history.
    Uses direct HTTP requests to Zep CE API.
    """

    def __init__(self, client: httpx.AsyncClient):
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
        try:
            zep_messages = [
                {
                    "role": msg.get("role", "user"),
                    "role_type": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "metadata": msg.get("metadata", {}),
                }
                for msg in messages
            ]

            response = await self.client.post(
                f"/api/v1/sessions/{session_id}/memory",
                json={"messages": zep_messages},
            )

            if response.status_code in (200, 201):
                logger.debug(
                    "memory_added",
                    session_id=session_id,
                    message_count=len(messages),
                )
            else:
                logger.warning(
                    "memory_add_failed",
                    session_id=session_id,
                    status=response.status_code,
                )
        except Exception as e:
            logger.warning("memory_add_failed", session_id=session_id, error=str(e))

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
            response = await self.client.get(
                f"/api/v1/sessions/{session_id}/memory",
                params={"lastn": limit},
            )

            if response.status_code != 200:
                return []

            data = response.json()
            messages = []
            for msg in data.get("messages", [])[-limit:]:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "metadata": msg.get("metadata", {}),
                    "created_at": msg.get("created_at"),
                })

            return messages

        except Exception:
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
            response = await self.client.post(
                f"/api/v1/sessions/{session_id}/search",
                json={"text": text, "metadata": {}},
                params={"limit": limit},
            )

            if response.status_code != 200:
                return []

            data = response.json()
            memories = []
            for result in data or []:
                msg = result.get("message", {})
                if msg:
                    memories.append({
                        "content": msg.get("content", ""),
                        "role": msg.get("role", "user"),
                        "score": result.get("score", 0.0),
                        "metadata": msg.get("metadata", {}),
                        "created_at": msg.get("created_at"),
                    })

            return memories

        except Exception:
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
            response = await self.client.delete(
                f"/api/v1/sessions/{session_id}/memory"
            )
            if response.status_code in (200, 204):
                logger.info("memory_cleared", session_id=session_id)
                return True
            return False
        except Exception:
            return True  # Already cleared or doesn't exist


# =============================================================================
# Fact Operations
# =============================================================================


class FactOperations:
    """
    Fact operations for the temporal knowledge graph.

    Facts are extracted entities and relationships from conversations.
    Uses direct HTTP requests to Zep CE API.
    """

    def __init__(self, client: httpx.AsyncClient):
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
            response = await self.client.get(
                f"/api/v1/sessions/{session_id}/memory"
            )

            if response.status_code != 200:
                return []

            data = response.json()
            facts = []
            for fact in data.get("facts", []) or []:
                facts.append({
                    "content": fact.get("fact", fact.get("content", "")),
                    "created_at": fact.get("created_at"),
                })

            return facts

        except Exception:
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
        try:
            response = await self.client.post(
                f"/api/v1/sessions/{session_id}/memory",
                json={
                    "messages": [
                        {
                            "role": "system",
                            "role_type": "system",
                            "content": f"[FACT] {fact_content}",
                            "metadata": metadata or {},
                        }
                    ]
                },
            )
            if response.status_code in (200, 201):
                logger.debug("fact_added", session_id=session_id, fact=fact_content[:50])
        except Exception as e:
            logger.warning("fact_add_failed", error=str(e))


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

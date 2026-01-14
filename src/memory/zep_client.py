"""Zep client for semantic memory operations.

Provides:
- Epic storage and search (for suggestions)
- Thread summary storage (for dedup detection)

Phase 4: Store and retrieve only, no enforcement.
"""

import logging
from typing import Optional

from zep_python.client import AsyncZep
from zep_python.types import Message

from src.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncZep | None = None


def get_zep_client() -> AsyncZep:
    """Get or create Zep client singleton."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncZep(
            base_url=settings.zep_api_url,
            api_key=settings.zep_api_key,
        )
        logger.info(f"Zep client initialized: {settings.zep_api_url}")
    return _client


# --- Epic Memory Operations ---


async def store_epic(
    epic_key: str,
    summary: str,
    description: str,
    status: str = "active",
) -> None:
    """Store Epic in Zep for semantic search.

    Creates a session for the Epic with its content as memory.
    """
    client = get_zep_client()

    # Use epic_key as session_id
    session_id = f"epic:{epic_key}"

    try:
        # Create session if not exists
        await client.memory.add_session(
            session_id=session_id,
            metadata={
                "epic_key": epic_key,
                "status": status,
                "type": "epic_definition",
            },
        )
    except Exception:
        pass  # Session may already exist

    # Add Epic content as memory
    message = Message(
        role="system",
        role_type="system",
        content=f"Epic {epic_key}: {summary}\n\n{description}",
    )

    await client.memory.add(session_id, messages=[message])
    logger.info(f"Stored Epic in Zep: {epic_key}")


async def search_epics(
    query: str,
    limit: int = 3,
    status_filter: str = "active",
) -> list[dict]:
    """Search for Epics semantically similar to query.

    Returns list of {epic_key, summary, score} dicts.
    """
    client = get_zep_client()

    try:
        response = await client.memory.search_sessions(
            text=query,
            limit=limit,
            record_filter={"status": status_filter, "type": "epic_definition"},
            search_scope="messages",
        )

        results = []
        for result in response.results or []:
            if result.session_id and result.session_id.startswith("epic:"):
                epic_key = result.session_id[5:]  # Remove "epic:" prefix
                results.append({
                    "epic_key": epic_key,
                    "summary": result.message.content[:200] if result.message else "",
                    "score": result.score or 0.0,
                })
        return results
    except Exception as e:
        logger.warning(f"Epic search failed: {e}")
        return []


# --- Thread Summary Operations ---


async def store_thread_summary(
    session_id: str,
    epic_key: str,
    summary: str,
    key_points: list[str],
) -> None:
    """Store thread summary for dedup detection.

    Args:
        session_id: team:channel:thread_ts
        epic_key: Linked Epic key
        summary: Natural language summary
        key_points: List of key discussion points
    """
    client = get_zep_client()

    try:
        await client.memory.add_session(
            session_id=session_id,
            metadata={
                "epic_key": epic_key,
                "type": "thread_summary",
            },
        )
    except Exception:
        pass  # Session may already exist

    content = f"Thread summary: {summary}\n\nKey points:\n" + "\n".join(
        f"- {p}" for p in key_points
    )

    message = Message(
        role="assistant",
        role_type="assistant",
        content=content,
    )

    await client.memory.add(session_id, messages=[message])
    logger.info(f"Stored thread summary: {session_id}")


async def search_similar_threads(
    query: str,
    epic_key: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """Search for threads similar to query.

    Used for dedup detection in Phase 4C.

    Args:
        query: Message content to find similar threads
        epic_key: Optionally filter to same Epic
        limit: Max results

    Returns list of {session_id, summary, score} dicts.
    """
    client = get_zep_client()

    try:
        record_filter: dict = {"type": "thread_summary"}
        if epic_key:
            record_filter["epic_key"] = epic_key

        response = await client.memory.search_sessions(
            text=query,
            limit=limit,
            record_filter=record_filter,
            search_scope="messages",
        )

        results = []
        for result in response.results or []:
            results.append({
                "session_id": result.session_id,
                "summary": result.message.content if result.message else "",
                "score": result.score or 0.0,
            })
        return results
    except Exception as e:
        logger.warning(f"Thread search failed: {e}")
        return []

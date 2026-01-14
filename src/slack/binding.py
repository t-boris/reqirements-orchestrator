"""Epic binding flow - connect threads to Epics."""

import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.blocks import build_session_card, build_epic_selector
from src.slack.session import SessionIdentity
from src.db.session_store import SessionStore
from src.memory.zep_client import search_epics

logger = logging.getLogger(__name__)


async def suggest_epics(text: str, channel_id: str) -> list[dict]:
    """Suggest relevant Epics based on message content.

    Uses Zep semantic search to find related active Epics.
    Returns list of {key, summary, score} dicts.
    """
    try:
        # Search for similar epics using Zep
        results = await search_epics(text, limit=3)
        return [
            {
                "key": r.get("epic_key"),
                "summary": r.get("summary", ""),
                "score": r.get("score", 0.0),
            }
            for r in results
            if r.get("epic_key")
        ]
    except Exception as e:
        logger.warning(f"Epic search failed: {e}")
        return []


async def start_binding_flow(
    client: WebClient,
    identity: SessionIdentity,
    message_text: str,
    store: SessionStore,
) -> None:
    """Start Epic binding flow for new session.

    1. Search for relevant Epics
    2. Post epic selector to thread
    3. Wait for user selection (handled by action handler)
    """
    # Get or create session
    session = await store.get_or_create(
        channel_id=identity.channel_id,
        thread_ts=identity.thread_ts,
    )

    # If already bound, post session card
    if session.epic_id:
        blocks = build_session_card(
            epic_key=session.epic_id,
            epic_summary=None,  # TODO: Fetch from Jira
            session_status="Active",
            thread_ts=identity.thread_ts,
        )
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Session active",
            blocks=blocks,
        )
        return

    # Suggest Epics
    suggested = await suggest_epics(message_text, identity.channel_id)

    # Post epic selector
    blocks = build_epic_selector(
        suggested_epics=suggested,
        message_preview=message_text,
    )

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text="Which Epic does this relate to?",
        blocks=blocks,
    )


async def bind_epic(
    identity: SessionIdentity,
    epic_key: str,
    store: SessionStore,
    client: WebClient,
) -> None:
    """Bind session to selected Epic.

    Called when user clicks Epic selection button.
    """
    # Update session with epic_id
    await store.update_epic(
        channel_id=identity.channel_id,
        thread_ts=identity.thread_ts,
        epic_id=epic_key,
    )

    logger.info(
        f"Session bound to Epic",
        extra={
            "session_id": identity.session_id,
            "epic_key": epic_key,
        }
    )

    # Post session card
    blocks = build_session_card(
        epic_key=epic_key,
        epic_summary=None,  # TODO: Fetch from Jira
        session_status="Active - collecting requirements",
        thread_ts=identity.thread_ts,
    )

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f"Session linked to {epic_key}",
        blocks=blocks,
    )

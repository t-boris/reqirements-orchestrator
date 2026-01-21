"""Epic binding flow - connect threads to Epics."""

import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.blocks import build_session_card, build_epic_selector
from src.slack.session import SessionIdentity
from src.db.workitem_store import WorkItemStore
from src.db.models import WorkItem, WorkItemType, WorkItemStatus
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
    store: WorkItemStore,
) -> None:
    """Start Epic binding flow for new conversation.

    1. Check if thread already has a WorkItem
    2. If not, search for relevant Epics and show selector
    3. Wait for user selection (handled by action handler)
    """
    # Check for existing WorkItem in this thread
    items = await store.list_by_channel(
        identity.channel_id,
        limit=1,
    )
    # Find item that originated from this thread
    existing = next(
        (item for item in items if item.source_thread_ts == identity.thread_ts),
        None,
    )

    # If already has WorkItem with jira_key (bound to Epic), show card
    if existing and existing.jira_key:
        blocks = build_session_card(
            epic_key=existing.jira_key,
            epic_summary=existing.summary,
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

    # Suggest Epics based on message content
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
    store: WorkItemStore,
    client: WebClient,
) -> None:
    """Bind conversation to selected Epic.

    Creates or updates a WorkItem linking this thread to the Epic.
    Called when user clicks Epic selection button.
    """
    # Check if there's already a WorkItem from this thread
    items = await store.list_by_channel(identity.channel_id, limit=50)
    existing = next(
        (item for item in items if item.source_thread_ts == identity.thread_ts),
        None,
    )

    # Get epic info from Jira
    epic_summary = "Epic"
    try:
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        settings = get_settings()
        jira = JiraService(settings)
        epic = await jira.get_issue(epic_key)
        epic_summary = epic.summary
        await jira.close()
    except Exception as e:
        logger.warning(f"Failed to fetch epic summary: {e}")

    if existing:
        # Update existing WorkItem with jira_key
        await store.update(
            existing.id,
            jira_key=epic_key,
            status=WorkItemStatus.ACTIVE,
        )
        workitem = await store.get(existing.id)
    else:
        # Create new WorkItem linked to this Epic
        workitem = await store.create(
            channel_id=identity.channel_id,
            item_type=WorkItemType.STORY,  # Default to story under epic
            summary=f"Work from thread (under {epic_key})",
            created_by=identity.user_id or "unknown",
            source_thread_ts=identity.thread_ts,
        )
        # Set jira_key to link to epic
        workitem = await store.update(
            workitem.id,
            jira_key=epic_key,
            status=WorkItemStatus.ACTIVE,
        )

    logger.info(
        "Thread bound to Epic via WorkItem",
        extra={
            "session_id": identity.session_id,
            "epic_key": epic_key,
            "workitem_id": workitem.id,
        }
    )

    # Post and pin epic link message
    try:
        from src.context.jira_linker import JiraLinker
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        settings = get_settings()
        jira = JiraService(settings)
        linker = JiraLinker(client, jira)

        await linker.on_epic_bound(
            channel_id=identity.channel_id,
            thread_ts=identity.thread_ts,
            epic_key=epic_key,
            epic_summary=epic_summary,
        )

        await jira.close()
    except Exception as e:
        logger.warning(f"Failed to create epic pin: {e}")

    # Post session card
    blocks = build_session_card(
        epic_key=epic_key,
        epic_summary=epic_summary,
        session_status="Active - collecting requirements",
        thread_ts=identity.thread_ts,
    )

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f"Session linked to {epic_key}",
        blocks=blocks,
    )

"""Review continuation handlers.

Handles multi-ticket preview flow and intermediate review states.
Note: File named continue_.py to avoid Python keyword conflict.
"""

import logging

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

logger = logging.getLogger(__name__)


async def show_multi_ticket_preview(
    items: list[dict],
    identity: SessionIdentity,
    client: WebClient,
    metadata: dict,
):
    """Show multi-ticket preview and update state.

    Args:
        items: List of extracted items (id, type, title, description, parent_id)
        identity: Session identity for state management
        client: Slack WebClient
        metadata: Original scope gate metadata (channel_id, thread_ts, topic)
    """
    from src.schemas.state import WorkflowStep, PendingAction
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    channel_id = metadata.get("channel_id", "")
    thread_ts = metadata.get("thread_ts", "")
    topic = metadata.get("topic", "")

    runner = get_runner(identity)
    state = await runner._get_current_state()

    # Calculate total content size
    total_chars = sum(len(i.get("description", "")) + len(i.get("title", "")) for i in items)

    # Find epic ID if present
    epic_id = None
    for item in items:
        if item["type"] == "epic":
            epic_id = item["id"]
            break

    # Build MultiTicketState
    multi_ticket_state = {
        "items": items,
        "epic_id": epic_id,
        "total_chars": total_chars,
        "confirmed_quantity": False,
        "confirmed_size": False,
        "created_keys": [],
    }

    # Get current ui_version and increment
    ui_version = state.get("ui_version", 0) + 1

    # Update state
    await runner._update_state({
        "multi_ticket_state": multi_ticket_state,
        "workflow_step": WorkflowStep.MULTI_TICKET_PREVIEW,
        "pending_action": PendingAction.WAITING_STORY_EDIT,
        "ui_version": ui_version,
    })

    # Build and post preview blocks
    preview_blocks = build_multi_ticket_preview_blocks(items, ui_version, thread_ts=thread_ts)

    epic_count = sum(1 for i in items if i["type"] == "epic")
    story_count = sum(1 for i in items if i["type"] == "story")

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=preview_blocks,
        text=f"Multi-ticket preview: {epic_count} epic(s), {story_count} story(ies)",
    )

    logger.info(
        "Posted multi-ticket preview",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "item_count": len(items),
            "epic_count": epic_count,
            "story_count": story_count,
            "topic": topic,
        }
    )

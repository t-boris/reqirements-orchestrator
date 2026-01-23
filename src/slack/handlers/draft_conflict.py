"""Draft conflict resolution handlers (Phase 27.3).

Handles button clicks for resolving multi-user draft conflicts:
- draft_conflict_resolve_existing: Keep the original value
- draft_conflict_resolve_proposed: Use the new proposed value

After resolution:
1. Updates the conflict record
2. Updates the message to show resolution
3. Applies the chosen value to the draft
"""
import logging
from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_draft_conflict_resolve_existing(ack, body, client: WebClient, action):
    """Handle 'Keep original' button click."""
    ack()
    _run_async(_handle_draft_conflict_resolve_async(body, client, action, "existing"))


def handle_draft_conflict_resolve_proposed(ack, body, client: WebClient, action):
    """Handle 'Use new' button click."""
    ack()
    _run_async(_handle_draft_conflict_resolve_async(body, client, action, "proposed"))


async def _handle_draft_conflict_resolve_async(
    body: dict,
    client: WebClient,
    action: dict,
    resolution: str,
):
    """Async handler for conflict resolution.

    Args:
        body: Slack action body
        client: Slack WebClient
        action: Action payload with conflict_id as value
        resolution: Which side was chosen ('existing' or 'proposed')
    """
    from src.db import get_connection
    from src.db.conflict_store import ConflictStore
    from src.db.user_metadata_store import UserMetadataStore
    from src.slack.blocks.draft_conflict import build_draft_conflict_resolved_blocks

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    thread_ts = body["message"].get("thread_ts") or message_ts
    user_id = body["user"]["id"]

    conflict_id = action.get("value")
    if not conflict_id:
        logger.warning("No conflict_id in action value")
        return

    logger.info(
        f"Resolving draft conflict: {conflict_id} -> {resolution}",
        extra={
            "user_id": user_id,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
        }
    )

    try:
        # Update conflict as resolved
        async with get_connection() as conn:
            store = ConflictStore(conn)
            conflict = await store.resolve(conflict_id, resolution, user_id)

        if not conflict:
            logger.warning(f"Conflict not found: {conflict_id}")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, couldn't find that conflict. It may have already been resolved.",
            )
            return

        # Get display name for resolution message
        async with get_connection() as conn:
            user_store = UserMetadataStore(conn)
            display_name = await user_store.get_display_name(user_id, default=f"<@{user_id}>")

        # Build resolved blocks
        resolved_blocks = build_draft_conflict_resolved_blocks(
            conflict=conflict,
            resolution=resolution,
            resolved_by_name=display_name,
        )

        # Update the message to show resolution
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=resolved_blocks,
            text="Conflict resolved",
        )

        # Apply the resolution to the draft
        await _apply_conflict_resolution(channel_id, thread_ts, conflict, resolution)

        logger.info(
            f"Conflict resolved successfully",
            extra={
                "conflict_id": conflict_id,
                "resolution": resolution,
                "resolved_by": user_id,
            }
        )

    except Exception as e:
        logger.error(f"Failed to resolve conflict: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Sorry, something went wrong resolving that conflict. Please try again.",
        )


async def _apply_conflict_resolution(
    channel_id: str,
    thread_ts: str,
    conflict,
    resolution: str,
):
    """Apply the chosen resolution to the draft state.

    Updates the draft field with the chosen value and records
    the new attribution.

    Args:
        channel_id: Channel ID
        thread_ts: Thread timestamp
        conflict: The resolved DraftConflict
        resolution: Which side was chosen ('existing' or 'proposed')
    """
    from src.graph.runner import get_runner
    from src.slack.session import SessionIdentity

    # Get runner for this thread
    identity = SessionIdentity(
        team_id="",  # Will be filled from checkpoint state
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
        draft = state.get("draft")

        if not draft:
            logger.warning("No draft found to apply resolution")
            return

        # Get the chosen side
        chosen_side = conflict.existing if resolution == "existing" else conflict.proposed

        # Apply resolution based on field type
        field_name = conflict.field_name

        # Handle simple string fields
        if hasattr(draft, field_name):
            # Use set_with_attribution to preserve who said it
            draft.set_with_attribution(
                field=field_name,
                value=chosen_side.content,
                author_user_id=chosen_side.attribution.author_user_id,
                source_message_ts=chosen_side.attribution.source_message_ts,
                source_permalink=chosen_side.attribution.source_permalink,
            )

            # Update state with modified draft
            state["draft"] = draft
            await runner._update_state(state)

            logger.info(
                f"Applied conflict resolution to draft.{field_name}",
                extra={
                    "field": field_name,
                    "author": chosen_side.attribution.author_user_id,
                }
            )
        else:
            logger.warning(f"Unknown field for conflict resolution: {field_name}")

    except Exception as e:
        logger.warning(f"Could not apply conflict resolution: {e}")


def register_draft_conflict_handlers(app):
    """Register draft conflict handlers with the Slack app.

    Called from src/slack/router.py to register action handlers.

    Args:
        app: Slack Bolt App instance
    """
    app.action("draft_conflict_resolve_existing")(handle_draft_conflict_resolve_existing)
    app.action("draft_conflict_resolve_proposed")(handle_draft_conflict_resolve_proposed)

"""Draft-related dispatch handlers.

Handles draft conflict detection and transform operations.
"""

import logging
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def _handle_draft_conflict(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle draft conflict detected during extraction.

    Posts conflict UI with resolution buttons for each detected conflict.

    Args:
        result: Decision result with conflicts list
        identity: Session identity
        client: Slack WebClient
    """
    from src.slack.blocks.draft_conflict import build_draft_conflict_blocks
    from src.schemas.conflict import DraftConflict

    conflicts_data = result.get("conflicts", [])
    if not conflicts_data:
        logger.warning("No conflicts data in conflict result")
        return

    # Post each conflict with its resolution buttons
    for conflict_data in conflicts_data:
        try:
            conflict = DraftConflict(**conflict_data)
            blocks = build_draft_conflict_blocks(conflict)

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=blocks,
                text=f"Conflict detected in {conflict.field_name}",
            )

            logger.info(
                "Posted conflict UI",
                extra={
                    "conflict_id": conflict.conflict_id,
                    "field_name": conflict.field_name,
                    "channel_id": identity.channel_id,
                    "thread_ts": identity.thread_ts,
                },
            )
        except Exception as e:
            logger.error(f"Failed to post conflict UI: {e}", exc_info=True)

    # Post summary if multiple conflicts
    if len(conflicts_data) > 1:
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":warning: {len(conflicts_data)} conflicts detected. Please resolve each one above.",
        )


async def _handle_transform_applied(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle transform_applied action - show new structure.

    R8: After each Draft form change, bot must show the new form.

    Posts structure visualization with version-bound buttons after
    any structural mutation to the draft.

    Args:
        result: Decision result with transform_result and structured_draft
        identity: Session identity
        client: Slack WebClient
    """
    from src.slack.blocks.draft_structure import build_structure_blocks
    from src.schemas.structured_draft import StructuredDraft

    transform_result = result.get("transform_result", {})
    operation = result.get("operation", "unknown")
    reason = result.get("reason", "")

    # Get structured draft from result or fetch from runner
    structured_draft_data = result.get("structured_draft")

    if structured_draft_data is None:
        # Try to get from runner state
        runner = get_runner(identity)
        state = await runner._get_current_state()
        structured_draft = state.get("structured_draft")
    elif isinstance(structured_draft_data, dict):
        # Reconstruct from dict
        structured_draft = StructuredDraft(**structured_draft_data)
    else:
        structured_draft = structured_draft_data

    if not structured_draft:
        # No draft to show
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Transform applied: {reason}",
        )
        return

    # Build structure blocks with actions
    structure_blocks = build_structure_blocks(
        draft=structured_draft,
        show_actions=True,
        include_version=True,
    )

    # Post the structure visualization
    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        blocks=structure_blocks,
        text=f"Draft structure updated (version {structured_draft.version})",
    )

    logger.info(
        "Posted structure after transform",
        extra={
            "operation": operation,
            "success": transform_result.get("success"),
            "draft_id": structured_draft.id,
            "version": structured_draft.version,
            "item_count": len(structured_draft.items),
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
        },
    )

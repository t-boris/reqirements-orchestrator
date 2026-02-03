"""Modal view submission handlers.

Ref: RESEARCH.md - Slack modals require view submission handlers registered via app.view()
"""

import json
import logging

from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)


def register_view_handlers(app: AsyncApp) -> None:
    """Register all view (modal) submission handlers on the Bolt app."""

    @app.view("edit_adr_modal")
    async def handle_edit_adr_modal(ack, body: dict, client, view: dict) -> None:
        """Handle submission of the Edit ADR modal.

        1. Parse submitted values
        2. Re-fetch current message blocks (prevents stale data)
        3. Find and update the matching ADR section
        4. chat_update the message
        """
        await ack()

        # Parse submitted values
        values = view.get("state", {}).get("values", {})
        title = values.get("title_block", {}).get("title_input", {}).get("value", "")
        decision_type = (
            values.get("type_block", {}).get("type_select", {})
            .get("selected_option", {}).get("value", "architecture")
        )
        decision_text = values.get("decision_block", {}).get("decision_input", {}).get("value", "")
        rationale = values.get("rationale_block", {}).get("rationale_input", {}).get("value", "")
        alternatives_raw = (
            values.get("alternatives_block", {}).get("alternatives_input", {}).get("value") or ""
        )
        alternatives = [a.strip() for a in alternatives_raw.split(",") if a.strip()]

        # Parse private_metadata for context
        try:
            metadata = json.loads(view.get("private_metadata", "{}"))
        except (json.JSONDecodeError, TypeError):
            logger.error("Failed to parse edit_adr_modal private_metadata")
            return

        adr_index = metadata.get("adr_index")
        channel_id = metadata.get("channel_id")
        message_ts = metadata.get("message_ts")

        if adr_index is None or not channel_id or not message_ts:
            logger.error(f"Missing metadata in edit_adr_modal: {metadata}")
            return

        # Re-fetch current message blocks to prevent stale data
        try:
            result = await client.conversations_history(
                channel=channel_id,
                latest=message_ts,
                limit=1,
                inclusive=True,
            )
            messages = result.get("messages", [])
            if not messages:
                logger.error(f"Could not find message {message_ts} in {channel_id}")
                return
            blocks = messages[0].get("blocks", [])
        except Exception as e:
            logger.error(f"Failed to fetch message for modal update: {e}")
            return

        # Find section block matching *{adr_index+1}. prefix
        prefix = f"*{adr_index + 1}. "
        section_idx = None
        for i, block in enumerate(blocks):
            if block.get("type") != "section":
                continue
            text = block.get("text", {}).get("text", "")
            if text.startswith(prefix):
                section_idx = i
                break

        if section_idx is None:
            logger.warning(f"Could not find ADR #{adr_index + 1} section in message blocks")
            return

        # Rebuild section text with edited values
        alts = ""
        if alternatives:
            alts = f"\n_Alternatives: {', '.join(alternatives)}_"

        new_text = (
            f"*{adr_index + 1}. {title}*\n"
            f"{decision_text}\n"
            f"_Rationale: {rationale}_"
            f"{alts}"
        )

        blocks[section_idx]["text"]["text"] = new_text

        # Update the message
        try:
            await client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=blocks,
                text=f"Decision '{title}' updated",
            )
        except Exception as e:
            logger.error(f"Failed to update message after modal edit: {e}")

    logger.info("View handlers registered")

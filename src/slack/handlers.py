"""
Slack Handlers - Message and slash command handlers.

Processes incoming messages and routes them to the LangGraph workflow.
"""

import re
from typing import Any

import structlog
from slack_bolt.async_app import AsyncApp

from src.config.settings import get_settings
from src.graph import create_initial_state, create_thread_id, invoke_graph
from src.slack.approval import send_approval_request
from src.slack.formatter import format_response, format_error

logger = structlog.get_logger()
settings = get_settings()


def register_handlers(app: AsyncApp) -> None:
    """
    Register all message and command handlers with the Slack app.

    Args:
        app: Slack Bolt async app instance.
    """
    # =========================================================================
    # Message Handler
    # =========================================================================

    @app.event("message")
    async def handle_message(event: dict, say, client) -> None:
        """
        Handle all incoming messages.

        Processes messages through the LangGraph workflow and responds
        based on confidence thresholds.
        """
        # Skip bot messages and message changes
        if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            return

        # Skip messages from this bot
        if event.get("bot_id"):
            return

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        message_text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        message_ts = event.get("ts", "")

        # Check if bot was @mentioned
        bot_user_id = await _get_bot_user_id(client)
        is_mention = f"<@{bot_user_id}>" in message_text

        # Remove bot mention from message text
        if is_mention:
            message_text = re.sub(rf"<@{bot_user_id}>", "", message_text).strip()

        # Extract attachments
        attachments = await _process_attachments(event, client)

        logger.info(
            "message_received",
            channel_id=channel_id,
            user_id=user_id,
            is_mention=is_mention,
            has_attachments=len(attachments) > 0,
        )

        try:
            # Create initial state for the graph
            state = create_initial_state(
                channel_id=channel_id,
                user_id=user_id,
                message=message_text,
                thread_ts=thread_ts,
                attachments=attachments,
                is_mention=is_mention,
            )

            # Create thread ID for checkpointing
            thread_id = create_thread_id(channel_id, thread_ts)

            # Invoke the graph
            result = await invoke_graph(state, thread_id)

            # Handle response based on graph output
            if result.get("awaiting_human"):
                # Send approval request
                await send_approval_request(
                    client=client,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    draft=result.get("draft", {}),
                    conflicts=result.get("conflicts", []),
                    thread_id=thread_id,
                )

            elif result.get("should_respond") and result.get("response"):
                # Format and send response
                blocks = format_response(
                    response=result["response"],
                    draft=result.get("draft"),
                    jira_key=result.get("jira_issue_key"),
                )

                await say(
                    text=result["response"],
                    blocks=blocks,
                    thread_ts=thread_ts,
                )

            elif result.get("error"):
                # Send error message
                blocks = format_error(result["error"])
                await say(
                    text=f"Error: {result['error']}",
                    blocks=blocks,
                    thread_ts=thread_ts,
                )

            # If should_respond is False, bot stays silent (per design)

        except Exception as e:
            logger.exception("message_processing_failed", error=str(e))

            # Only respond with error if bot was mentioned
            if is_mention:
                await say(
                    text=f"Sorry, I encountered an error processing your message.",
                    thread_ts=thread_ts,
                )

    # =========================================================================
    # Slash Commands
    # =========================================================================

    @app.command("/req-status")
    async def handle_status_command(ack, command, client) -> None:
        """
        Show current graph state and metrics.

        Usage: /req-status
        """
        await ack()

        channel_id = command.get("channel_id", "")
        thread_ts = None  # Commands run in main channel

        try:
            from src.graph import get_thread_state

            thread_id = create_thread_id(channel_id, thread_ts)
            state = await get_thread_state(thread_id)

            if state:
                text = _format_status(state)
            else:
                text = "No active conversation state in this channel."

            await client.chat_postEphemeral(
                channel=channel_id,
                user=command["user_id"],
                text=text,
            )

        except Exception as e:
            logger.error("status_command_failed", error=str(e))
            await client.chat_postEphemeral(
                channel=channel_id,
                user=command["user_id"],
                text=f"Error getting status: {str(e)}",
            )

    @app.command("/req-clean")
    async def handle_clean_command(ack, command, client) -> None:
        """
        Clear memory and graph state for the channel.

        Usage: /req-clean
        """
        await ack()

        channel_id = command.get("channel_id", "")
        user_id = command.get("user_id", "")

        try:
            from src.graph import clear_thread
            from src.memory import clear_channel_memory

            # Clear graph state
            thread_id = create_thread_id(channel_id, None)
            await clear_thread(thread_id)

            # Clear Zep memory
            await clear_channel_memory(channel_id)

            await client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> Channel memory and state have been cleared.",
            )

            logger.info("channel_cleaned", channel_id=channel_id, user_id=user_id)

        except Exception as e:
            logger.error("clean_command_failed", error=str(e))
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Error cleaning channel: {str(e)}",
            )

    @app.command("/req-config")
    async def handle_config_command(ack, command, client) -> None:
        """
        Open channel configuration modal.

        Usage: /req-config
        """
        await ack()

        # Open configuration modal
        await client.views_open(
            trigger_id=command["trigger_id"],
            view=_build_config_modal(command["channel_id"]),
        )

    @app.command("/req-approve")
    async def handle_approve_command(ack, command, client) -> None:
        """
        Manage permanent approvals.

        Usage:
            /req-approve list - List all approvals
            /req-approve delete <id> - Delete an approval
        """
        await ack()

        channel_id = command.get("channel_id", "")
        user_id = command.get("user_id", "")
        args = command.get("text", "").strip().split()

        if not args or args[0] == "list":
            await _handle_approval_list(client, channel_id, user_id)
        elif args[0] == "delete" and len(args) > 1:
            await _handle_approval_delete(client, channel_id, user_id, args[1])
        else:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Usage: `/req-approve list` or `/req-approve delete <id>`",
            )

    # =========================================================================
    # Button Actions
    # =========================================================================

    @app.action(re.compile(r"^approve_"))
    async def handle_approve_action(ack, body, client) -> None:
        """Handle approval button clicks."""
        await ack()

        from src.slack.approval import handle_approval_action

        await handle_approval_action(body, client)

    @app.action(re.compile(r"^edit_"))
    async def handle_edit_action(ack, body, client) -> None:
        """Handle edit button clicks - opens modal."""
        await ack()

        from src.slack.approval import handle_edit_action

        await handle_edit_action(body, client)

    @app.action(re.compile(r"^reject_"))
    async def handle_reject_action(ack, body, client) -> None:
        """Handle reject button clicks."""
        await ack()

        from src.slack.approval import handle_reject_action

        await handle_reject_action(body, client)

    # =========================================================================
    # Modal Submissions
    # =========================================================================

    @app.view("config_modal")
    async def handle_config_submit(ack, body, view, client) -> None:
        """Handle configuration modal submission."""
        await ack()

        # Extract values from modal
        values = view.get("state", {}).get("values", {})
        channel_id = view.get("private_metadata", "")
        user_id = body.get("user", {}).get("id", "")

        # TODO: Save configuration to database
        # For now, just confirm

        await client.chat_postMessage(
            channel=channel_id,
            text=f"<@{user_id}> Channel configuration updated.",
        )

    @app.view("edit_requirement_modal")
    async def handle_edit_submit(ack, body, view, client) -> None:
        """Handle requirement edit modal submission."""
        await ack()

        from src.slack.approval import process_edit_submission

        await process_edit_submission(body, view, client)


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_bot_user_id(client) -> str:
    """Get the bot's user ID."""
    response = await client.auth_test()
    return response.get("user_id", "")


async def _process_attachments(event: dict, client) -> list[dict[str, Any]]:
    """
    Process and extract content from message attachments.

    Args:
        event: Slack message event.
        client: Slack client.

    Returns:
        List of processed attachment data.
    """
    attachments = []

    # Process files
    files = event.get("files", [])
    for file in files:
        attachment = {
            "type": "file",
            "name": file.get("name", ""),
            "mimetype": file.get("mimetype", ""),
            "url": file.get("url_private", ""),
        }

        # Try to read text file content
        if file.get("mimetype", "").startswith("text/"):
            try:
                # Download file content
                response = await client.files_info(file=file["id"])
                content = response.get("content", "")
                attachment["content"] = content[:10000]  # Limit size
            except Exception as e:
                logger.warning("file_download_failed", file=file["name"], error=str(e))

        attachments.append(attachment)

    return attachments


def _format_status(state: dict) -> str:
    """Format state for status display."""
    parts = [
        "*Current State*",
        f"Intent: `{state.get('intent', 'unknown')}`",
        f"Confidence: `{state.get('intent_confidence', 0):.0%}`",
        f"Active Persona: `{state.get('active_persona') or 'Main Bot'}`",
    ]

    if state.get("draft"):
        draft = state["draft"]
        parts.append(f"\n*Draft*")
        parts.append(f"Title: {draft.get('title', 'Untitled')}")
        parts.append(f"Type: {draft.get('issue_type', 'Unknown')}")

    if state.get("jira_issue_key"):
        parts.append(f"\n*Jira*: {state['jira_issue_key']}")

    if state.get("awaiting_human"):
        parts.append("\n_Awaiting human approval_")

    return "\n".join(parts)


def _build_config_modal(channel_id: str) -> dict:
    """Build the channel configuration modal."""
    return {
        "type": "modal",
        "callback_id": "config_modal",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Channel Configuration"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Configure requirements bot for this channel*",
                },
            },
            {
                "type": "input",
                "block_id": "project_key",
                "label": {"type": "plain_text", "text": "Jira Project Key"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "project_key_input",
                    "placeholder": {"type": "plain_text", "text": "e.g., MARO"},
                },
            },
            {
                "type": "input",
                "block_id": "default_issue_type",
                "label": {"type": "plain_text", "text": "Default Issue Type"},
                "element": {
                    "type": "static_select",
                    "action_id": "issue_type_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Story"}, "value": "Story"},
                        {"text": {"type": "plain_text", "text": "Task"}, "value": "Task"},
                        {"text": {"type": "plain_text", "text": "Bug"}, "value": "Bug"},
                        {"text": {"type": "plain_text", "text": "Epic"}, "value": "Epic"},
                    ],
                    "initial_option": {"text": {"type": "plain_text", "text": "Story"}, "value": "Story"},
                },
            },
        ],
    }


async def _handle_approval_list(client, channel_id: str, user_id: str) -> None:
    """Handle /req-approve list command."""
    from src.slack.approval import get_permanent_approvals

    approvals = await get_permanent_approvals(channel_id)

    if not approvals:
        text = "No permanent approvals configured for this channel."
    else:
        lines = ["*Permanent Approvals*\n"]
        for i, approval in enumerate(approvals, 1):
            lines.append(f"{i}. `{approval.get('pattern', '')}` - Created by <@{approval.get('user_id', '')}>")
        text = "\n".join(lines)

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=text,
    )


async def _handle_approval_delete(client, channel_id: str, user_id: str, approval_id: str) -> None:
    """Handle /req-approve delete command."""
    from src.slack.approval import delete_permanent_approval

    success = await delete_permanent_approval(channel_id, approval_id)

    if success:
        text = f"Approval `{approval_id}` has been deleted."
    else:
        text = f"Approval `{approval_id}` not found."

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=text,
    )

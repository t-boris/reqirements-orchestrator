"""Handlers for ticket update preview and confirmation flow.

Provides conversational update flow:
1. User requests update -> show preview with current/proposed
2. User can Apply, Edit, Cancel, or provide text feedback
3. Text feedback refines the proposed update
4. After apply -> post notification to channel
"""

import json
import logging
from datetime import datetime, timezone

from slack_bolt import Ack, Respond
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity, get_identity_from_body
from src.slack.blocks.update_preview import (
    build_update_preview_blocks,
    build_update_edit_modal,
    build_update_success_blocks,
)
from src.graph.runner import get_runner
from src.schemas.state import PendingAction, WorkflowStep

logger = logging.getLogger(__name__)


async def handle_update_preview_apply(
    ack: Ack,
    body: dict,
    client: WebClient,
    respond: Respond,
):
    """Handle Apply Changes button click - apply the update to Jira."""
    await ack()

    try:
        action = body["actions"][0]
        button_data = json.loads(action.get("value", "{}"))
        ticket_key = button_data.get("key")

        identity = get_identity_from_body(body)
        runner = get_runner(identity)

        # Get pending update from state
        state = await runner._get_current_state()
        pending_update = state.get("pending_update")

        if not pending_update or pending_update.get("ticket_key") != ticket_key:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text="This update is no longer active. Please start a new update request.",
            )
            return

        # Apply the update to Jira
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        settings = get_settings()
        jira = JiraService(settings)

        proposed_content = pending_update["proposed_content"]
        update_mode = pending_update.get("update_mode", "append")
        current_description = pending_update.get("current_description", "")

        # Build final description
        if update_mode == "append" and current_description:
            separator = "\n\n---\n\n"
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            new_description = f"{current_description}{separator}h3. Update from Slack ({timestamp})\n\n{proposed_content}"
        else:
            new_description = proposed_content

        # Apply update
        updated_issue = await jira.update_issue(
            ticket_key,
            {"description": new_description},
        )
        await jira.close()

        logger.info(
            "Ticket update applied",
            extra={
                "ticket_key": ticket_key,
                "update_mode": update_mode,
                "content_length": len(proposed_content),
            }
        )

        # Clear pending update state
        state["pending_update"] = None
        state["pending_action"] = None
        state["workflow_step"] = None
        await runner.update_state(state)

        # Update the preview message to show success
        success_blocks = build_update_success_blocks(
            ticket_key=ticket_key,
            ticket_url=updated_issue.url,
            update_summary=f"Added {len(proposed_content)} characters to description.",
        )

        # Update original message
        message_ts = pending_update.get("preview_message_ts")
        if message_ts:
            client.chat_update(
                channel=identity.channel_id,
                ts=message_ts,
                blocks=success_blocks,
                text=f"Updated {ticket_key}",
            )
        else:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=success_blocks,
                text=f"Updated {ticket_key}",
            )

        # Post channel notification
        await _post_update_notification(
            client=client,
            channel_id=identity.channel_id,
            thread_ts=identity.thread_ts,
            ticket_key=ticket_key,
            ticket_url=updated_issue.url,
            update_summary=f"Description updated from thread",
        )

    except Exception as e:
        logger.error(f"Failed to apply update: {e}", exc_info=True)
        client.chat_postMessage(
            channel=body.get("channel", {}).get("id"),
            thread_ts=body.get("message", {}).get("thread_ts"),
            text=f"Failed to apply update: {str(e)}",
        )


async def handle_update_preview_edit(
    ack: Ack,
    body: dict,
    client: WebClient,
):
    """Handle Edit button click - open modal to edit proposed content."""
    await ack()

    try:
        action = body["actions"][0]
        button_data = json.loads(action.get("value", "{}"))
        ticket_key = button_data.get("key")

        identity = get_identity_from_body(body)
        runner = get_runner(identity)

        # Get pending update from state
        state = await runner._get_current_state()
        pending_update = state.get("pending_update")

        if not pending_update or pending_update.get("ticket_key") != ticket_key:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text="This update is no longer active. Please start a new update request.",
            )
            return

        # Open edit modal
        modal = build_update_edit_modal(
            ticket_key=ticket_key,
            current_description=pending_update.get("current_description", ""),
            proposed_content=pending_update.get("proposed_content", ""),
            update_mode=pending_update.get("update_mode", "append"),
        )

        # Add thread context to metadata for post-submit routing
        metadata = json.loads(modal.get("private_metadata", "{}"))
        metadata["thread_ts"] = identity.thread_ts
        metadata["channel_id"] = identity.channel_id
        modal["private_metadata"] = json.dumps(metadata)

        client.views_open(
            trigger_id=body["trigger_id"],
            view=modal,
        )

    except Exception as e:
        logger.error(f"Failed to open edit modal: {e}", exc_info=True)


async def handle_update_preview_cancel(
    ack: Ack,
    body: dict,
    client: WebClient,
):
    """Handle Cancel button click - cancel the update."""
    await ack()

    try:
        action = body["actions"][0]
        button_data = json.loads(action.get("value", "{}"))
        ticket_key = button_data.get("key")

        identity = get_identity_from_body(body)
        runner = get_runner(identity)

        # Clear pending update state
        state = await runner._get_current_state()
        state["pending_update"] = None
        state["pending_action"] = None
        state["workflow_step"] = None
        await runner.update_state(state)

        # Update the preview message to show cancelled
        message_ts = body.get("message", {}).get("ts")
        if message_ts:
            client.chat_update(
                channel=identity.channel_id,
                ts=message_ts,
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Update to *{ticket_key}* cancelled."
                    }
                }],
                text=f"Update cancelled",
            )
        else:
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=f"Update to *{ticket_key}* cancelled.",
            )

        logger.info(f"Update cancelled for {ticket_key}")

    except Exception as e:
        logger.error(f"Failed to cancel update: {e}", exc_info=True)


async def handle_update_edit_modal_submit(
    ack: Ack,
    body: dict,
    client: WebClient,
    view: dict,
):
    """Handle edit modal submission - update proposed content and re-show preview."""
    await ack()

    try:
        # Extract values from modal
        values = view.get("state", {}).get("values", {})
        new_content = values.get("update_content_block", {}).get("update_content_input", {}).get("value", "")
        new_mode = values.get("update_mode_block", {}).get("update_mode_select", {}).get("selected_option", {}).get("value", "append")

        # Get context from metadata
        metadata = json.loads(view.get("private_metadata", "{}"))
        ticket_key = metadata.get("ticket_key")
        thread_ts = metadata.get("thread_ts")
        channel_id = metadata.get("channel_id")

        if not all([ticket_key, thread_ts, channel_id]):
            logger.error("Missing context in modal metadata")
            return

        identity = SessionIdentity(
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        runner = get_runner(identity)

        # Update pending state with edited content
        state = await runner._get_current_state()
        pending_update = state.get("pending_update")

        if not pending_update:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="This update is no longer active. Please start a new update request.",
            )
            return

        # Update pending state
        pending_update["proposed_content"] = new_content
        pending_update["update_mode"] = new_mode
        state["pending_update"] = pending_update
        state["ui_version"] = state.get("ui_version", 0) + 1
        await runner.update_state(state)

        # Rebuild and post new preview
        from src.config.settings import get_settings
        settings = get_settings()
        ticket_url = f"{settings.jira_url}/browse/{ticket_key}"

        preview_blocks = build_update_preview_blocks(
            ticket_key=ticket_key,
            ticket_url=ticket_url,
            current_description=pending_update.get("current_description", ""),
            proposed_content=new_content,
            update_mode=new_mode,
            ui_version=state["ui_version"],
        )

        # Post new preview
        result = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=preview_blocks,
            text=f"Updated preview for {ticket_key}",
        )

        # Store new preview message ts
        pending_update["preview_message_ts"] = result["ts"]
        state["pending_update"] = pending_update
        await runner.update_state(state)

        logger.info(
            "Update preview refreshed after edit",
            extra={"ticket_key": ticket_key, "new_mode": new_mode}
        )

    except Exception as e:
        logger.error(f"Failed to process edit modal: {e}", exc_info=True)


async def refine_update_from_feedback(
    identity: SessionIdentity,
    client: WebClient,
    feedback_text: str,
) -> bool:
    """Process user feedback to refine pending update.

    Args:
        identity: Session identity
        client: Slack client
        feedback_text: User's text feedback

    Returns:
        True if feedback was processed, False if no pending update
    """
    from src.llm import get_llm

    runner = get_runner(identity)
    state = await runner._get_current_state()
    pending_update = state.get("pending_update")

    if not pending_update:
        return False

    ticket_key = pending_update["ticket_key"]
    current_content = pending_update["proposed_content"]
    current_mode = pending_update.get("update_mode", "append")

    # Use LLM to interpret feedback and adjust content
    llm = get_llm()
    refinement_prompt = f'''You are helping refine a proposed update to Jira ticket {ticket_key}.

Current proposed content:
{current_content}

Current mode: {current_mode} (append = add to existing, replace = overwrite existing)

User feedback: {feedback_text}

Based on the feedback, provide:
1. The updated content (incorporating the feedback)
2. Whether to use "append" or "replace" mode

If the user says something like "replace everything", "start fresh", or "rewrite" - use replace mode.
If the user says "add", "also include", "and mention" - use append mode.
If the user says "ok", "apply", "do it", "looks good" - return APPLY_NOW as the content.
If the user says "cancel", "nevermind", "stop" - return CANCEL as the content.

Return in this exact format:
MODE: append|replace
CONTENT:
[the updated content here]
'''

    response = await llm.chat(refinement_prompt)

    # Parse response
    lines = response.strip().split("\n")
    new_mode = current_mode
    new_content = current_content

    if lines[0].startswith("MODE:"):
        mode_line = lines[0].replace("MODE:", "").strip().lower()
        if mode_line in ["append", "replace"]:
            new_mode = mode_line
        lines = lines[1:]

    # Find CONTENT: line and get everything after
    content_start = 0
    for i, line in enumerate(lines):
        if line.startswith("CONTENT:"):
            content_start = i + 1
            break

    if content_start > 0 and content_start < len(lines):
        new_content = "\n".join(lines[content_start:]).strip()

    # Check for special commands
    if new_content == "APPLY_NOW":
        # Trigger apply
        await _apply_update_directly(identity, client, pending_update)
        return True

    if new_content == "CANCEL":
        # Cancel update
        state["pending_update"] = None
        state["pending_action"] = None
        state["workflow_step"] = None
        await runner.update_state(state)

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Update to *{ticket_key}* cancelled.",
        )
        return True

    # Update state with refined content
    pending_update["proposed_content"] = new_content
    pending_update["update_mode"] = new_mode
    state["pending_update"] = pending_update
    state["ui_version"] = state.get("ui_version", 0) + 1
    await runner.update_state(state)

    # Post new preview
    from src.config.settings import get_settings
    settings = get_settings()
    ticket_url = f"{settings.jira_url}/browse/{ticket_key}"

    preview_blocks = build_update_preview_blocks(
        ticket_key=ticket_key,
        ticket_url=ticket_url,
        current_description=pending_update.get("current_description", ""),
        proposed_content=new_content,
        update_mode=new_mode,
        ui_version=state["ui_version"],
    )

    result = client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        blocks=preview_blocks,
        text=f"Updated preview for {ticket_key}",
    )

    # Store new preview ts
    pending_update["preview_message_ts"] = result["ts"]
    state["pending_update"] = pending_update
    await runner.update_state(state)

    logger.info(
        "Update refined from feedback",
        extra={
            "ticket_key": ticket_key,
            "new_mode": new_mode,
            "feedback": feedback_text[:100],
        }
    )

    return True


async def _apply_update_directly(
    identity: SessionIdentity,
    client: WebClient,
    pending_update: dict,
):
    """Apply update directly (called from feedback processing)."""
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    ticket_key = pending_update["ticket_key"]
    proposed_content = pending_update["proposed_content"]
    update_mode = pending_update.get("update_mode", "append")
    current_description = pending_update.get("current_description", "")

    settings = get_settings()
    jira = JiraService(settings)

    # Build final description
    if update_mode == "append" and current_description:
        separator = "\n\n---\n\n"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        new_description = f"{current_description}{separator}h3. Update from Slack ({timestamp})\n\n{proposed_content}"
    else:
        new_description = proposed_content

    # Apply update
    updated_issue = await jira.update_issue(
        ticket_key,
        {"description": new_description},
    )
    await jira.close()

    # Clear state
    runner = get_runner(identity)
    state = await runner._get_current_state()
    state["pending_update"] = None
    state["pending_action"] = None
    state["workflow_step"] = None
    await runner.update_state(state)

    # Post success
    success_blocks = build_update_success_blocks(
        ticket_key=ticket_key,
        ticket_url=updated_issue.url,
        update_summary=f"Added {len(proposed_content)} characters to description.",
    )

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        blocks=success_blocks,
        text=f"Updated {ticket_key}",
    )

    # Channel notification
    await _post_update_notification(
        client=client,
        channel_id=identity.channel_id,
        thread_ts=identity.thread_ts,
        ticket_key=ticket_key,
        ticket_url=updated_issue.url,
        update_summary="Description updated from thread",
    )


async def _post_update_notification(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    ticket_key: str,
    ticket_url: str,
    update_summary: str,
):
    """Post update notification to channel (not in thread).

    This notifies the channel that a ticket was updated from a thread discussion.
    """
    # Build thread link
    thread_link = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":pencil2: *<{ticket_url}|{ticket_key}>* updated from <{thread_link}|thread>\n_{update_summary}_"
            }
        }
    ]

    # Post to channel (no thread_ts = channel root)
    client.chat_postMessage(
        channel=channel_id,
        blocks=blocks,
        text=f"{ticket_key} updated",
    )

    logger.info(
        "Posted update notification to channel",
        extra={"ticket_key": ticket_key, "channel_id": channel_id}
    )

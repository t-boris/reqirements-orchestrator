"""
Approval System - Human-in-the-loop approval for Jira writes.

Handles:
- Sending approval requests with Block Kit UI
- Processing approval/reject/edit decisions
- Managing permanent approvals ("Approve Always")
"""

from typing import Any

import structlog

from src.config.settings import get_settings
# Note: graph imports done lazily inside functions to avoid circular imports
from src.slack.formatter import format_draft_preview, format_conflicts

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# In-Memory Approval Storage (Replace with DB in production)
# =============================================================================

# Maps channel_id -> list of approval patterns
_permanent_approvals: dict[str, list[dict[str, Any]]] = {}


# =============================================================================
# Approval Request
# =============================================================================


async def send_approval_request(
    client,
    channel_id: str,
    thread_ts: str | None,
    draft: dict[str, Any],
    conflicts: list[dict[str, Any]],
    thread_id: str,
) -> dict:
    """
    Send an approval request message with action buttons.

    Args:
        client: Slack client.
        channel_id: Channel to send to.
        thread_ts: Thread timestamp for reply.
        draft: Requirement draft to approve.
        conflicts: Any detected conflicts.
        thread_id: Graph thread ID for resumption.

    Returns:
        Slack API response.
    """
    blocks = _build_approval_blocks(draft, conflicts, thread_id)

    response = await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f"Please review the requirement: {draft.get('title', 'Untitled')}",
        blocks=blocks,
    )

    logger.info(
        "approval_request_sent",
        channel_id=channel_id,
        thread_id=thread_id,
        title=draft.get("title"),
    )

    return response


def _build_approval_blocks(
    draft: dict[str, Any],
    conflicts: list[dict[str, Any]],
    thread_id: str,
) -> list[dict]:
    """Build Block Kit blocks for approval message."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Review Requirement",
            },
        },
    ]

    # Add draft preview
    blocks.extend(format_draft_preview(draft))

    # Add conflicts if any
    if conflicts:
        blocks.extend(format_conflicts(conflicts))

    # Add approval buttons
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": f"approve_{thread_id}",
                "value": thread_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve Always"},
                "action_id": f"approve_always_{thread_id}",
                "value": thread_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": f"edit_{thread_id}",
                "value": thread_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reject"},
                "style": "danger",
                "action_id": f"reject_{thread_id}",
                "value": thread_id,
            },
        ],
    })

    return blocks


# =============================================================================
# Action Handlers
# =============================================================================


async def handle_approval_action(body: dict, client) -> None:
    """
    Handle Approve or Approve Always button click.

    Resumes the graph with approval decision.
    """
    # Lazy imports to avoid circular dependency
    from src.graph.state import HumanDecision
    from src.graph.graph import resume_graph

    action = body.get("actions", [{}])[0]
    action_id = action.get("action_id", "")
    thread_id = action.get("value", "")
    user_id = body.get("user", {}).get("id", "")
    channel_id = body.get("channel", {}).get("id", "")
    message_ts = body.get("message", {}).get("ts", "")

    # Determine decision type
    if "approve_always" in action_id:
        decision = HumanDecision.APPROVE_ALWAYS.value
        # Store permanent approval
        await _store_permanent_approval(channel_id, thread_id, user_id)
    else:
        decision = HumanDecision.APPROVE.value

    logger.info(
        "approval_received",
        thread_id=thread_id,
        decision=decision,
        user_id=user_id,
    )

    try:
        # Resume graph with approval
        result = await resume_graph(thread_id, decision)

        # Update the message to show result
        jira_key = result.get("jira_issue_key", "")
        text = f"Approved by <@{user_id}>. Created Jira issue: {jira_key}"

        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=text,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                },
            ],
        )

    except Exception as e:
        logger.error("approval_processing_failed", error=str(e))
        await client.chat_postMessage(
            channel=channel_id,
            text=f"Error processing approval: {str(e)}",
        )


async def handle_reject_action(body: dict, client) -> None:
    """
    Handle Reject button click.

    Resumes the graph with rejection decision.
    """
    # Lazy imports to avoid circular dependency
    from src.graph.state import HumanDecision
    from src.graph.graph import resume_graph

    action = body.get("actions", [{}])[0]
    thread_id = action.get("value", "")
    user_id = body.get("user", {}).get("id", "")
    channel_id = body.get("channel", {}).get("id", "")
    message_ts = body.get("message", {}).get("ts", "")

    logger.info(
        "rejection_received",
        thread_id=thread_id,
        user_id=user_id,
    )

    try:
        # Resume graph with rejection
        await resume_graph(thread_id, HumanDecision.REJECT.value)

        # Update the message
        text = f"Rejected by <@{user_id}>. No Jira issue was created."

        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=text,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                },
            ],
        )

    except Exception as e:
        logger.error("rejection_processing_failed", error=str(e))


async def handle_edit_action(body: dict, client) -> None:
    """
    Handle Edit button click.

    Opens a modal for editing the requirement.
    """
    action = body.get("actions", [{}])[0]
    thread_id = action.get("value", "")
    trigger_id = body.get("trigger_id", "")

    # Get current draft from graph state
    from src.graph import get_thread_state

    state = await get_thread_state(thread_id)
    draft = state.get("draft", {}) if state else {}

    # Open edit modal
    await client.views_open(
        trigger_id=trigger_id,
        view=_build_edit_modal(draft, thread_id),
    )


def _build_edit_modal(draft: dict[str, Any], thread_id: str) -> dict:
    """Build the requirement edit modal."""
    return {
        "type": "modal",
        "callback_id": "edit_requirement_modal",
        "private_metadata": thread_id,
        "title": {"type": "plain_text", "text": "Edit Requirement"},
        "submit": {"type": "plain_text", "text": "Save & Continue"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "title",
                "label": {"type": "plain_text", "text": "Title"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "title_input",
                    "initial_value": draft.get("title", ""),
                },
            },
            {
                "type": "input",
                "block_id": "description",
                "label": {"type": "plain_text", "text": "Description"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "description_input",
                    "multiline": True,
                    "initial_value": draft.get("description", ""),
                },
            },
            {
                "type": "input",
                "block_id": "issue_type",
                "label": {"type": "plain_text", "text": "Issue Type"},
                "element": {
                    "type": "static_select",
                    "action_id": "issue_type_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Story"}, "value": "Story"},
                        {"text": {"type": "plain_text", "text": "Task"}, "value": "Task"},
                        {"text": {"type": "plain_text", "text": "Bug"}, "value": "Bug"},
                        {"text": {"type": "plain_text", "text": "Epic"}, "value": "Epic"},
                    ],
                    "initial_option": {
                        "text": {"type": "plain_text", "text": draft.get("issue_type", "Story")},
                        "value": draft.get("issue_type", "Story"),
                    },
                },
            },
            {
                "type": "input",
                "block_id": "acceptance_criteria",
                "label": {"type": "plain_text", "text": "Acceptance Criteria"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "ac_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "One criterion per line"},
                    "initial_value": "\n".join(draft.get("acceptance_criteria", [])),
                },
            },
            {
                "type": "input",
                "block_id": "feedback",
                "label": {"type": "plain_text", "text": "Additional Feedback"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "feedback_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Any additional guidance for refining this requirement"},
                },
            },
        ],
    }


async def process_edit_submission(body: dict, view: dict, client) -> None:
    """
    Process the edit modal submission.

    Resumes the graph with edit decision and feedback.
    """
    # Lazy imports to avoid circular dependency
    from src.graph.state import HumanDecision
    from src.graph.graph import resume_graph

    thread_id = view.get("private_metadata", "")
    values = view.get("state", {}).get("values", {})
    user_id = body.get("user", {}).get("id", "")

    # Extract edited values
    title = values.get("title", {}).get("title_input", {}).get("value", "")
    description = values.get("description", {}).get("description_input", {}).get("value", "")
    issue_type = values.get("issue_type", {}).get("issue_type_select", {}).get("selected_option", {}).get("value", "Story")
    ac_text = values.get("acceptance_criteria", {}).get("ac_input", {}).get("value", "")
    feedback = values.get("feedback", {}).get("feedback_input", {}).get("value", "")

    # Parse acceptance criteria
    acceptance_criteria = [line.strip() for line in ac_text.split("\n") if line.strip()]

    # Build feedback for graph
    human_feedback = f"""Edited by user:
Title: {title}
Description: {description}
Issue Type: {issue_type}
Acceptance Criteria: {acceptance_criteria}
Additional Feedback: {feedback or 'None'}"""

    logger.info(
        "edit_submitted",
        thread_id=thread_id,
        user_id=user_id,
    )

    try:
        # Resume graph with edit
        await resume_graph(thread_id, HumanDecision.EDIT.value, human_feedback)

        # The graph will loop back and send a new approval request

    except Exception as e:
        logger.error("edit_processing_failed", error=str(e))


# =============================================================================
# Permanent Approvals
# =============================================================================


async def _store_permanent_approval(
    channel_id: str,
    pattern: str,
    user_id: str,
) -> None:
    """Store a permanent approval pattern."""
    if channel_id not in _permanent_approvals:
        _permanent_approvals[channel_id] = []

    _permanent_approvals[channel_id].append({
        "pattern": pattern,
        "user_id": user_id,
    })

    logger.info(
        "permanent_approval_stored",
        channel_id=channel_id,
        pattern=pattern,
        user_id=user_id,
    )


async def get_permanent_approvals(channel_id: str) -> list[dict[str, Any]]:
    """Get all permanent approvals for a channel."""
    return _permanent_approvals.get(channel_id, [])


async def delete_permanent_approval(channel_id: str, approval_id: str) -> bool:
    """Delete a permanent approval by ID (index)."""
    approvals = _permanent_approvals.get(channel_id, [])

    try:
        idx = int(approval_id) - 1  # 1-indexed from user perspective
        if 0 <= idx < len(approvals):
            approvals.pop(idx)
            return True
    except (ValueError, IndexError):
        pass

    return False


async def check_permanent_approval(channel_id: str, draft: dict[str, Any]) -> bool:
    """
    Check if a draft matches any permanent approval patterns.

    Args:
        channel_id: Channel ID.
        draft: Requirement draft to check.

    Returns:
        True if auto-approved.
    """
    approvals = _permanent_approvals.get(channel_id, [])

    # For now, simple matching - could be extended with pattern matching
    for approval in approvals:
        # If any approval exists for this channel, auto-approve
        # In a full implementation, match against patterns
        if approval.get("pattern"):
            logger.info(
                "permanent_approval_matched",
                channel_id=channel_id,
                pattern=approval["pattern"],
            )
            return True

    return False

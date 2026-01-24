"""Attachment UI blocks for Slack.

Builds Block Kit components for attachment messages.
Includes pin/unpin buttons, status display, file preview.
"""
from typing import Optional
from uuid import UUID

from src.schemas.attachment import Attachment, AttachmentStatus


def build_attachment_card(
    attachment: Attachment,
    show_pin_button: bool = True,
) -> list[dict]:
    """Build attachment card with actions.

    Shows file info, status, and pin/unpin button.

    Args:
        attachment: Attachment to display.
        show_pin_button: Whether to show pin/unpin button.

    Returns:
        List of Block Kit blocks.
    """
    # Status emoji
    status_emoji = {
        AttachmentStatus.PENDING: ":hourglass_flowing_sand:",
        AttachmentStatus.EXTRACTING: ":arrows_counterclockwise:",
        AttachmentStatus.READY: ":white_check_mark:",
        AttachmentStatus.FAILED: ":x:",
        AttachmentStatus.TOO_LARGE: ":package:",
    }.get(attachment.status, ":grey_question:")

    # File type emoji
    type_emoji = _get_type_emoji(attachment.mimetype)

    # Build header
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{type_emoji} *{attachment.filename}*\n"
                    f"{status_emoji} {attachment.status.value.title()}"
                    + (f" | :pushpin: Pinned" if attachment.pinned else "")
                ),
            },
        }
    ]

    # Add summary if available
    if attachment.summary:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_{attachment.summary}_",
                }
            ],
        })

    # Add actions if ready
    if attachment.status == AttachmentStatus.READY and show_pin_button:
        actions = _build_action_buttons(attachment)
        if actions:
            blocks.append({
                "type": "actions",
                "elements": actions,
            })

    return blocks


def build_attachment_notification(
    attachment: Attachment,
    action: str,
) -> list[dict]:
    """Build notification after attachment action.

    Args:
        attachment: Attachment that was acted on.
        action: Action taken (e.g., "pinned", "unpinned", "processed").

    Returns:
        List of Block Kit blocks.
    """
    emoji = ":pushpin:" if action == "pinned" else ":paperclip:"
    verb = action.title()

    return [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{emoji} {verb}: *{attachment.filename}*",
                }
            ],
        }
    ]


def build_pinned_context_line(
    attachments: list[Attachment],
) -> str:
    """Build status line showing pinned attachments.

    For display in thread status or context block.

    Args:
        attachments: List of pinned attachments.

    Returns:
        Status line text (e.g., ":pushpin: Pinned: spec.pdf, api.md").
    """
    if not attachments:
        return ""

    names = [a.filename for a in attachments[:3]]
    if len(attachments) > 3:
        names.append(f"+{len(attachments) - 3} more")

    return f":pushpin: Pinned: {', '.join(names)}"


def _build_action_buttons(attachment: Attachment) -> list[dict]:
    """Build action buttons for attachment.

    Pin if not pinned, Unpin if pinned.
    """
    buttons = []

    if attachment.pinned:
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Unpin from context"},
            "action_id": "attachment_unpin",
            "value": str(attachment.id),
        })
    else:
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": ":pushpin: Pin as context"},
            "style": "primary",
            "action_id": "attachment_pin",
            "value": str(attachment.id),
        })

    return buttons


def _get_type_emoji(mimetype: str) -> str:
    """Get emoji for file type."""
    if "pdf" in mimetype:
        return ":page_facing_up:"
    elif "word" in mimetype or "document" in mimetype:
        return ":memo:"
    elif "markdown" in mimetype:
        return ":clipboard:"
    elif "text" in mimetype:
        return ":page_with_curl:"
    else:
        return ":paperclip:"

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


# --- Transparency UI Blocks (Phase 34-07) ---


def build_used_attachments_footer(
    context: "AttachmentContext",
) -> list[dict]:
    """Build footer showing what attachments were used.

    Displays:
    - :paperclip: Used: filename (sections: 1, 2, 3)
    - [Show sources] [Stop using this file]

    Args:
        context: AttachmentContext from retriever.

    Returns:
        List of Block Kit blocks for response footer.
    """
    # Import here to avoid circular imports
    from src.documents.retriever import AttachmentContext

    if not context.pinned and not context.retrieved_chunks:
        return []

    blocks = []

    # Build "Used" summary
    used_files: dict[str, dict] = {}

    # Collect pinned files
    for p in context.pinned:
        filename = p["filename"]
        if filename not in used_files:
            used_files[filename] = {
                "id": p["id"],
                "sections": [],
                "pinned": True,
            }

    # Collect retrieved chunks
    for c in context.retrieved_chunks:
        filename = c["filename"]
        if filename not in used_files:
            used_files[filename] = {
                "id": c["attachment_id"],
                "sections": [],
                "pinned": False,
            }
        used_files[filename]["sections"].append(c["chunk_index"])

    # Build text
    used_parts = []
    for filename, info in used_files.items():
        part = f"*{filename}*"
        if info["pinned"]:
            part += " (:pushpin: pinned)"
        elif info["sections"]:
            sections = sorted(set(info["sections"]))[:5]
            part += f" (sections: {', '.join(map(str, sections))})"
        used_parts.append(part)

    used_text = ":paperclip: Used: " + ", ".join(used_parts)

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": used_text}
        ],
    })

    # Add action buttons if we have used files
    if used_files:
        actions = []

        # Show sources button (if we have retrieved chunks)
        if context.retrieved_chunks:
            actions.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Show sources"},
                "action_id": "attachment_show_sources",
                "value": _encode_source_ids(context),
            })

        # Stop using button (for each file, max 2 to fit Slack limits)
        for filename, info in list(used_files.items())[:2]:
            truncated_name = (
                f"{filename[:15]}..."
                if len(filename) > 15 else filename
            )
            actions.append({
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": f"Stop using {truncated_name}",
                },
                "action_id": "attachment_stop_using",
                "value": info["id"],
            })

        if actions:
            blocks.append({
                "type": "actions",
                "elements": actions,
            })

    return blocks


def build_sources_modal(
    context: "AttachmentContext",
) -> dict:
    """Build modal showing source content.

    Displays the actual chunks that were used.

    Args:
        context: AttachmentContext with retrieved chunks.

    Returns:
        Slack modal view payload.
    """
    blocks = []

    # Group chunks by file
    chunks_by_file: dict[str, list[dict]] = {}
    for c in context.retrieved_chunks:
        filename = c["filename"]
        if filename not in chunks_by_file:
            chunks_by_file[filename] = []
        chunks_by_file[filename].append(c)

    # Build blocks for each file
    for filename, chunks in chunks_by_file.items():
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": f":page_facing_up: {filename}"},
        })

        for chunk in chunks:
            # Truncate content for display
            content = chunk["content"][:1000]
            if len(chunk["content"]) > 1000:
                content += "..."

            # Build score display
            score = chunk.get("score", 0)
            score_text = f"(relevance: {score:.2f})" if score else ""

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Section {chunk['chunk_index']}* {score_text}\n```{content}```",
                },
            })

        blocks.append({"type": "divider"})

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Source Content"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks[:50],  # Slack limit
    }


def build_offer_attachments_block(
    context: "AttachmentContext",
) -> Optional[dict]:
    """Build block offering to use available attachments.

    For CHAT mode when attachments exist but aren't included.

    Args:
        context: AttachmentContext with offer_available.

    Returns:
        Block or None if no attachments to offer.
    """
    offer_msg = context.to_offer_message()
    if not offer_msg:
        return None

    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": offer_msg},
    }


def _encode_source_ids(context: "AttachmentContext") -> str:
    """Encode source IDs for button value.

    Slack button values have length limits (2000 chars).
    """
    import json
    ids = [c["attachment_id"] for c in context.retrieved_chunks[:5]]
    return json.dumps({"ids": ids, "query": ""})[:2000]

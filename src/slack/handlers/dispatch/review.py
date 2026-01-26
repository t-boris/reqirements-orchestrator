"""Review dispatch handlers.

Handles review responses and review continuation (persona-based analysis).
"""

import json
import logging
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

# Phase 37: Question blocks for review questions
from src.slack.blocks.question import build_question_blocks

# Phase 39: Actionable message tracker for stale button removal
from src.slack.actionable_message_tracker import clear_old_actionable_and_track_new

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def _handle_review_continuation(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle review_continuation action - synthesized response to user's answers."""
    continuation_msg = result.get("message", "")
    persona = result.get("persona", "")
    topic = result.get("topic", "")
    is_questions = result.get("is_questions", False)
    questions_data = result.get("questions_data", [])

    if persona:
        prefix = f"*{persona}:*\n\n"
    else:
        prefix = ""

    # If bot is asking questions, render with buttons (Phase 37)
    if is_questions and questions_data:
        intro_text = f"{prefix}Great, here are the key questions we need to resolve:"
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": intro_text}
            }
        ]

        # Add each question with options as buttons
        # Use review thread_ts as pseudo plan_id for button value encoding
        review_plan_id = f"review_{identity.thread_ts}"
        review_version = result.get("version", 1)

        for q_data in questions_data:
            question_blocks = build_question_blocks(
                question_data=q_data,
                plan_id=review_plan_id,
                plan_version=review_version,
            )
            blocks.extend(question_blocks)
            # Add divider between questions
            blocks.append({"type": "divider"})

        # Remove last divider
        if blocks and blocks[-1].get("type") == "divider":
            blocks.pop()

        # Add context about text replies
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "_Click buttons above or reply in thread to answer._",
            }]
        })

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts if identity.thread_ts else None,
            blocks=blocks,
            text=continuation_msg[:200],
        )
        return  # Questions rendered, exit early

    if continuation_msg:
        # Use same chunking logic as review (Slack block text limit is 3000 chars)
        full_text = prefix + continuation_msg
        MAX_MESSAGE_LENGTH = 2900

        # Split into message-sized chunks at natural boundaries
        message_chunks = []
        remaining = full_text
        while remaining:
            if len(remaining) <= MAX_MESSAGE_LENGTH:
                message_chunks.append(remaining)
                break

            split_at = MAX_MESSAGE_LENGTH
            para_break = remaining.rfind("\n\n", 0, MAX_MESSAGE_LENGTH)
            if para_break > MAX_MESSAGE_LENGTH // 2:
                split_at = para_break + 2
            else:
                line_break = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
                if line_break > MAX_MESSAGE_LENGTH // 2:
                    split_at = line_break + 1
                else:
                    space = remaining.rfind(" ", 0, MAX_MESSAGE_LENGTH)
                    if space > MAX_MESSAGE_LENGTH // 2:
                        split_at = space + 1

            message_chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()

        logger.info(f"Sending review_continuation: {len(full_text)} chars in {len(message_chunks)} message(s)")

        # Send each chunk as a separate Slack message
        for i, chunk in enumerate(message_chunks):
            is_last_message = (i == len(message_chunks) - 1)

            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": chunk}
                }
            ]

            # Add action buttons only to the last message
            if is_last_message:
                ticket_button_value = json.dumps({
                    "review_text": continuation_msg[:1500],
                    "topic": (topic or "")[:100],
                    "persona": persona or "",
                })
                approve_button_value = json.dumps({
                    "topic": (topic or "")[:100],
                    "persona": persona or "",
                })
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve & Post Decision"},
                            "action_id": "approve_architecture",
                            "value": approve_button_value,
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Turn into Jira ticket"},
                            "action_id": "review_to_ticket",
                            "value": ticket_button_value,
                        }
                    ]
                })

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts if identity.thread_ts else None,
                blocks=blocks,
                text=chunk[:200],
            )

        # Check if there are follow-up questions to ask
        has_followup = result.get("has_followup", False)
        followup_questions = result.get("questions_data", []) if has_followup else []

        if followup_questions:
            # Post follow-up question with buttons after the update
            review_plan_id = f"review_{identity.thread_ts}"
            review_version = result.get("version", 1)

            followup_blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "_I need a bit more information:_"}
                }
            ]

            for q_data in followup_questions:
                question_blocks = build_question_blocks(
                    question_data=q_data,
                    plan_id=review_plan_id,
                    plan_version=review_version,
                )
                followup_blocks.extend(question_blocks)

            followup_blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "_Reply in thread to answer._",
                }]
            })

            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts if identity.thread_ts else None,
                blocks=followup_blocks,
                text="Follow-up question",
            )


async def _handle_review(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle review action - persona-based analysis without Jira operations."""
    review_msg = result.get("message", "")
    persona = result.get("persona", "")
    topic = result.get("topic", "")

    # Format as review (persona indicator + analysis)
    if persona:
        prefix = f"*{persona} Review:*\n\n"
    else:
        prefix = ""

    if review_msg:
        # Split into multiple Slack messages to avoid collapse
        # Slack block text limit is 3000 chars, so we split at 2900 to be safe
        full_text = prefix + review_msg
        MAX_MESSAGE_LENGTH = 2900  # Keep under Slack's 3000 char block text limit

        # Split into message-sized chunks at natural boundaries
        message_chunks = []
        remaining = full_text
        while remaining:
            if len(remaining) <= MAX_MESSAGE_LENGTH:
                message_chunks.append(remaining)
                break

            # Find a good split point (prefer double newline, then single newline)
            split_at = MAX_MESSAGE_LENGTH
            # Try to find paragraph break
            para_break = remaining.rfind("\n\n", 0, MAX_MESSAGE_LENGTH)
            if para_break > MAX_MESSAGE_LENGTH // 2:
                split_at = para_break + 2
            else:
                # Try single newline
                line_break = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
                if line_break > MAX_MESSAGE_LENGTH // 2:
                    split_at = line_break + 1
                else:
                    # Fall back to space
                    space = remaining.rfind(" ", 0, MAX_MESSAGE_LENGTH)
                    if space > MAX_MESSAGE_LENGTH // 2:
                        split_at = space + 1

            message_chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()

        # Log chunking info
        logger.info(f"Sending review: {len(full_text)} chars in {len(message_chunks)} message(s)")

        # Send each chunk as a separate Slack message
        # Track last message with buttons for stale button removal
        last_actionable_ts = None

        for i, chunk in enumerate(message_chunks):
            is_last_message = (i == len(message_chunks) - 1)

            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": chunk}
                }
            ]

            # Add action buttons only to the last message
            if is_last_message:
                ticket_button_value = json.dumps({
                    "review_text": review_msg[:1500],
                    "topic": (topic or "")[:100],
                    "persona": persona or "",
                })

                # Build action buttons based on super_mode
                # "Approve & Post Decision" only for DECIDE mode
                super_mode = result.get("super_mode", "think")
                artifact_id = result.get("artifact_id")
                action_elements = []

                if super_mode == "decide":
                    approve_button_value = json.dumps({
                        "topic": (topic or "")[:100],
                        "persona": persona or "",
                    })
                    action_elements.append({
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve & Post Decision"},
                        "action_id": "approve_architecture",
                        "value": approve_button_value,
                        "style": "primary",
                    })
                elif artifact_id:
                    # In THINK mode with artifact - offer to capture as decision
                    capture_button_value = json.dumps({
                        "artifact_id": artifact_id,
                        "topic": (topic or "")[:100],
                        "persona": persona or "",
                    })
                    action_elements.append({
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Capture as Decision"},
                        "action_id": "capture_as_decision",
                        "value": capture_button_value,
                    })

                # "Turn into Jira ticket" always available
                action_elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Turn into Jira ticket"},
                    "action_id": "review_to_ticket",
                    "value": ticket_button_value,
                })

                blocks.append({
                    "type": "actions",
                    "elements": action_elements
                })

            try:
                post_result = client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts if identity.thread_ts else None,
                    blocks=blocks,
                    text=chunk[:200],  # Fallback text
                )
                # Track last message with buttons for cleanup
                if is_last_message and post_result.get("ts"):
                    last_actionable_ts = post_result["ts"]
            except Exception as e:
                logger.error(f"Failed to post review message {i+1}/{len(message_chunks)}: {e}")
                # Try posting without blocks as fallback
                try:
                    client.chat_postMessage(
                        channel=identity.channel_id,
                        thread_ts=identity.thread_ts if identity.thread_ts else None,
                        text=chunk[:3000],
                    )
                except Exception as e2:
                    logger.error(f"Fallback text-only message also failed: {e2}")

        # Clear old actionable buttons and track new message
        if last_actionable_ts and identity.thread_ts:
            clear_old_actionable_and_track_new(
                client,
                identity.channel_id,
                identity.thread_ts,
                last_actionable_ts,
            )

        # Phase 39: Post structured questions if available
        is_questions = result.get("is_questions", False)
        questions_data = result.get("questions_data", [])
        if is_questions and questions_data:
            # Build question blocks for ALL questions
            review_plan_id = f"review_{identity.thread_ts}"
            review_version = 1

            question_blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*To proceed, I need your input on these questions:*"}
                }
            ]

            for q_data in questions_data:
                q_blocks = build_question_blocks(
                    question_data=q_data,
                    plan_id=review_plan_id,
                    plan_version=review_version,
                )
                question_blocks.extend(q_blocks)
                question_blocks.append({"type": "divider"})

            # Remove last divider
            if question_blocks and question_blocks[-1].get("type") == "divider":
                question_blocks.pop()

            # Add context
            question_blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "_Click buttons above or reply in thread to answer._",
                }]
            })

            try:
                client.chat_postMessage(
                    channel=identity.channel_id,
                    thread_ts=identity.thread_ts if identity.thread_ts else None,
                    blocks=question_blocks,
                    text="Questions for you",
                )
                logger.info(f"Posted {len(questions_data)} structured review questions")
            except Exception as e:
                logger.error(f"Failed to post review questions: {e}")

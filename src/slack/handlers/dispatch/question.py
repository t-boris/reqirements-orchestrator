"""Question Engine dispatch handlers (Phase 36).

Handles question posting and budget exhausted scenarios.
"""

import logging
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def _handle_question_posted(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle question_posted action - post question UI to Slack.

    Called when the Question Engine generates a question for the user.
    Posts the question with interactive UI elements.

    Args:
        client: Slack WebClient
        result: Decision result with question_data, plan_id, plan_version
        identity: Session identity
    """
    question_data = result.get("question", {})
    plan_id = result.get("plan_id")
    plan_version = result.get("plan_version", 0)

    await _post_question_ui(
        client,
        identity.channel_id,
        identity.thread_ts,
        question_data,
        plan_id,
        plan_version,
    )

    logger.info(
        "Posted question UI",
        extra={
            "plan_id": plan_id,
            "plan_version": plan_version,
            "question_type": question_data.get("type", "unknown"),
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
        },
    )


async def _handle_budget_exhausted(
    client: WebClient,
    result: dict,
    identity: SessionIdentity,
) -> None:
    """Handle budget_exhausted action - post partial preview.

    Called when the Question Engine hits its question budget limit.
    Shows a partial preview with remaining fields.

    Args:
        client: Slack WebClient
        result: Decision result with pending_fields, plan_id
        identity: Session identity
    """
    pending_fields = result.get("pending_fields", [])
    plan_id = result.get("plan_id")

    await _post_budget_exhausted_ui(
        client,
        identity.channel_id,
        identity.thread_ts,
        pending_fields,
        plan_id,
    )

    logger.info(
        "Posted budget exhausted UI",
        extra={
            "plan_id": plan_id,
            "pending_fields_count": len(pending_fields),
            "channel_id": identity.channel_id,
            "thread_ts": identity.thread_ts,
        },
    )


async def _post_question_ui(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    question_data: dict,
    plan_id: str,
    plan_version: int,
) -> None:
    """Post question UI to Slack.

    Stub implementation - full UI in Plan 07.
    Attempts to import from src.slack.blocks.question if available,
    otherwise posts a simple text question.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        thread_ts: Slack thread timestamp
        question_data: Question data dict with question_text, options, etc.
        plan_id: TaskPlan ID
        plan_version: Plan version for state binding
    """
    question_text = question_data.get("question_text", "I have a question")

    try:
        # Try to import from question blocks module (Plan 07)
        from src.slack.blocks.question import build_question_blocks
        blocks = build_question_blocks(question_data, plan_id, plan_version)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=question_text,
        )
    except ImportError:
        # Fallback: simple text question
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=question_text,
        )


async def _post_budget_exhausted_ui(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    pending_fields: list[str],
    plan_id: str,
) -> None:
    """Post budget exhausted UI with partial preview.

    Stub implementation - full UI in Plan 07.
    Attempts to import from src.slack.blocks.question if available,
    otherwise posts a simple text message.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        thread_ts: Slack thread timestamp
        pending_fields: List of field names still needing values
        plan_id: TaskPlan ID
    """
    try:
        # Try to import from question blocks module (Plan 07)
        from src.slack.blocks.question import build_budget_exhausted_blocks
        blocks = build_budget_exhausted_blocks(pending_fields, plan_id)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text="I've hit my question limit. Here's what I have so far.",
        )
    except ImportError:
        # Fallback: simple text message
        fields_str = ", ".join(pending_fields[:5])
        if len(pending_fields) > 5:
            fields_str += f", and {len(pending_fields) - 5} more"
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"I've hit my question limit. Still need: {fields_str}\nYou can provide the remaining details or proceed with what we have.",
        )

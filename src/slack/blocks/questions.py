"""Question block builder for structured follow-up questions.

Renders LLM follow-up questions as Slack buttons for interactive UX.

Ref: Phase 8 - Smart UX Layer
"""

import json
import logging
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Slack Block Kit constraints
MAX_BUTTON_TEXT_LENGTH = 75
MAX_BUTTON_VALUE_LENGTH = 255
MAX_ELEMENTS_PER_ACTIONS_BLOCK = 5


def build_question_blocks(
    response_text: str,
    questions: list,
    thread_ts: str,
) -> list[dict[str, Any]]:
    """Build Slack blocks with text section + action buttons for follow-up questions.

    Args:
        response_text: The LLM response text to display.
        questions: List of FollowUpQuestion objects from ConverseLLMResponse.
        thread_ts: Thread timestamp for button value payloads.

    Returns:
        List of Slack Block Kit blocks.
    """
    blocks: list[dict[str, Any]] = []

    # Main response text section
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": response_text},
    })

    # Sort questions by priority (higher first)
    sorted_questions = sorted(questions, key=lambda q: q.priority, reverse=True)

    for question in sorted_questions:
        if question.question_type == "open_ended":
            # Open-ended questions are just text, no buttons
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"_{question.question_text}_"},
            })
            continue

        # Build buttons for choice and confirmation types
        elements = _build_option_buttons(question, thread_ts)

        if elements:
            # Add question text as context before buttons
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{question.question_text}*"},
            })
            blocks.append({
                "type": "actions",
                "elements": elements,
            })
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Type your answer if none of the options fit_"}],
            })

    return blocks


def _build_option_buttons(
    question,
    thread_ts: str,
) -> list[dict[str, Any]]:
    """Build button elements for a question's options.

    Args:
        question: A FollowUpQuestion with options.
        thread_ts: Thread timestamp for value payloads.

    Returns:
        List of button elements (max 5 per Slack actions block limit).
    """
    elements: list[dict[str, Any]] = []
    uid = uuid4().hex[:8]

    for idx, option in enumerate(question.options[:MAX_ELEMENTS_PER_ACTIONS_BLOCK]):
        label = option.label[:MAX_BUTTON_TEXT_LENGTH]

        # Extract action plan fields if present
        action = getattr(option, 'action', None)
        entity_ids = getattr(option, 'entity_ids', [])

        value_payload = _build_button_value(
            question_text=question.question_text,
            answer=option.label,
            thread_ts=thread_ts,
            action=action,
            entity_ids=entity_ids if action else [],  # Only include if action is set
        )

        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": f"answer_q_{uid}_{idx}",
            "value": value_payload,
        })

    return elements


def _build_button_value(
    question_text: str,
    answer: str,
    thread_ts: str,
    action: str | None = None,
    entity_ids: list[str] | None = None,
) -> str:
    """Build JSON value payload for a button, respecting 255 char limit.

    Args:
        question_text: The question being answered.
        answer: The selected answer text.
        thread_ts: Thread timestamp for conversation continuity.
        action: Optional action to execute (approve, commit, etc.)
        entity_ids: Optional list of entity IDs to act on.

    Returns:
        JSON string within Slack's 255 char limit.
    """
    payload: dict[str, Any] = {
        "answer": answer,
        "thread_ts": thread_ts,
    }

    # Include action plan if present
    if action:
        payload["action"] = action
        if entity_ids:
            payload["entity_ids"] = entity_ids

    # Add question_text (may be truncated)
    payload["question_text"] = question_text

    value = json.dumps(payload)

    # Truncate question_text if payload exceeds limit
    if len(value) > MAX_BUTTON_VALUE_LENGTH:
        # Calculate how much to truncate - prioritize keeping action/entity_ids
        overflow = len(value) - MAX_BUTTON_VALUE_LENGTH
        max_q_len = max(10, len(question_text) - overflow - 3)  # -3 for "..."
        payload["question_text"] = question_text[:max_q_len] + "..."
        value = json.dumps(payload)

    # If still too long (many entity_ids), truncate entity_ids
    if len(value) > MAX_BUTTON_VALUE_LENGTH and entity_ids:
        # Keep first few entity IDs that fit
        while len(value) > MAX_BUTTON_VALUE_LENGTH and payload.get("entity_ids"):
            payload["entity_ids"] = payload["entity_ids"][:-1]
            value = json.dumps(payload)

    return value

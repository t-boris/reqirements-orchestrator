"""Slack blocks for question UI.

Phase 36: Question Engine - Conversation Driver

Conversation-like question display with button options.
"""

from typing import Any, Optional

from src.questions.answer_mapper import encode_button_action_id, encode_button_value


def build_question_blocks(
    question_data: dict,
    plan_id: str,
    plan_version: int,
) -> list[dict]:
    """Build Slack blocks for a question.

    Args:
        question_data: Question info (question_id, question_type, question_text, options)
        plan_id: TaskPlan ID for version binding
        plan_version: Plan version for idempotency

    Returns:
        List of Slack blocks
    """
    question_id = question_data.get("question_id", "")
    question_text = question_data.get("question_text", "")
    question_type = question_data.get("question_type", "")
    options = question_data.get("options", [])
    target_field = question_data.get("target_field", "response")

    blocks = []

    # Question text section
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{question_text}*",
        },
    })

    # Options as buttons (if available)
    if options:
        button_elements = []
        for opt in options:
            option_id = opt.get("option_id", "")
            label = opt.get("label", "")
            is_recommended = opt.get("is_recommended", False)

            # Encode version in value for idempotency
            # Value format: "{plan_id}:{question_id}:{version}:{option_id}:{encoded_value}"
            value = encode_button_value(
                f"{plan_id}:{question_id}:{plan_version}",
                option_id,
                opt.get("value", option_id),
            )

            button = {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": f"{'* ' if is_recommended else ''}{label}"[:75],
                    "emoji": True,
                },
                "action_id": encode_button_action_id(question_id, option_id),
                "value": value,
            }

            # Highlight recommended
            if is_recommended:
                button["style"] = "primary"

            button_elements.append(button)

        blocks.append({
            "type": "actions",
            "elements": button_elements[:5],  # Slack limit
        })

        # Add description context if options have descriptions
        descriptions = [
            f"* *{opt['label']}*: {opt['description']}"
            for opt in options
            if opt.get("description")
        ]
        if descriptions:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "\n".join(descriptions[:4]),  # Max 4 descriptions
                }],
            })

    # Help text for text responses
    if question_type in ("COLLECT_FIELD", "ASK_USER", "collect_field", "ask_user") or not options:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "_Reply in thread to answer._",
            }],
        })

    # Add "Other" button for options-based questions
    if options and question_type in ("CONFIRM_SCOPE", "confirm_scope"):
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Other...",
                },
                "action_id": encode_button_action_id(question_id, "other"),
                "value": encode_button_value(
                    f"{plan_id}:{question_id}:{plan_version}",
                    "other",
                    "OTHER",
                ),
            }],
        })

    return blocks


def build_budget_exhausted_blocks(
    pending_fields: list[str],
    plan_id: str,
) -> list[dict]:
    """Build blocks for budget exhausted partial preview.

    Args:
        pending_fields: Fields that still need values
        plan_id: TaskPlan ID

    Returns:
        List of Slack blocks
    """
    blocks = []

    # Header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*I've hit my question limit*\n\nHere's what I have so far. You can proceed with gaps, wait for more input, or cancel.",
        },
    })

    # Pending fields
    if pending_fields:
        field_list = "\n".join(f"* {field}" for field in pending_fields)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Still missing:*\n{field_list}",
            },
        })

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Proceed with gaps"},
                "action_id": f"budget_proceed_{plan_id}",
                "value": f"{plan_id}:proceed",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Wait for input"},
                "action_id": f"budget_wait_{plan_id}",
                "value": f"{plan_id}:wait",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": f"budget_cancel_{plan_id}",
                "value": f"{plan_id}:cancel",
                "style": "danger",
            },
        ],
    })

    return blocks


def build_clarification_blocks(
    original_question: str,
    reason: str,
    question_id: str,
    plan_id: str,
    plan_version: int,
) -> list[dict]:
    """Build blocks asking for clarification on low-confidence answer.

    Args:
        original_question: The question that was asked
        reason: Why clarification is needed
        question_id: Question ID
        plan_id: TaskPlan ID
        plan_version: Plan version

    Returns:
        List of Slack blocks
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"I'm not quite sure I understood.\n\n*Original question:* {original_question}\n\n_{reason}_",
            },
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "_Please reply again or use buttons if available._",
            }],
        },
    ]


def build_review_question_blocks(
    question_data: dict,
    artifact_id: str | None = None,
) -> list[dict]:
    """Build Slack blocks for a review question.

    Simpler version of build_question_blocks for review open questions.
    Doesn't require plan versioning - uses artifact_id for context.

    Phase 39: Review questions with button options.

    Args:
        question_data: Question info (question_text, options)
        artifact_id: Review artifact ID (optional, for tracking)

    Returns:
        List of Slack blocks (question + buttons)
    """
    question_text = question_data.get("question_text", "")
    options = question_data.get("options", [])

    blocks = []

    # Divider before question
    blocks.append({"type": "divider"})

    # Question text section
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":question: *{question_text}*",
        },
    })

    # Options as buttons (if available)
    if options:
        button_elements = []
        for opt in options:
            option_id = opt.get("option_id", "")
            label = opt.get("label", "")
            value = opt.get("value", option_id)

            # Encode artifact_id in value for context
            button_value = f"review_answer:{artifact_id or 'none'}:{option_id}:{value}"

            button = {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": label[:75],
                    "emoji": True,
                },
                "action_id": f"review_question_{option_id}",
                "value": button_value,
            }

            button_elements.append(button)

        # Add "Other" button for free text response
        button_elements.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Something else...",
                "emoji": True,
            },
            "action_id": "review_question_other",
            "value": f"review_answer:{artifact_id or 'none'}:other:OTHER",
        })

        blocks.append({
            "type": "actions",
            "elements": button_elements[:5],  # Slack limit
        })

    # Help text
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "_Click a button or reply in thread to answer_",
        }],
    })

    return blocks

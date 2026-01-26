"""Slack blocks for triage questions.

Phase 44: Questions-First Collection Stage

Builds Slack Block Kit UI for triage questions with button options.
Follows patterns from src/slack/blocks/question.py but simpler (no plan_id/version).
"""
import json
from typing import Optional

from src.schemas.question import QuestionTask, QuestionType


def build_triage_question_blocks(
    question: QuestionTask,
    thread_ts: str,
) -> list[dict]:
    """Build Slack blocks for a triage question.

    Args:
        question: QuestionTask from TriageProvider
        thread_ts: Thread timestamp for button value encoding

    Returns:
        List of Slack blocks with question and buttons
    """
    blocks = []

    # Intro section with friendly greeting
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "Before I get started, I'd like to understand what you need:",
        },
    })

    # Divider
    blocks.append({"type": "divider"})

    # Question text in bold
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{question.question_text}*",
        },
    })

    # Check if this is an ASK_USER question (no buttons, free-form input)
    if question.question_type == QuestionType.ASK_USER or not question.has_options():
        # Context for free-form input
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "_Just reply in the thread with your answer._",
            }],
        })
        return blocks

    # Build buttons for options
    button_elements = []
    for opt in question.options:
        # Extract target field name (strip "triage." prefix)
        target_field = question.target_field or ""
        if target_field.startswith("triage."):
            target_field = target_field[7:]  # Remove "triage." prefix

        # Encode button value as JSON
        button_value = json.dumps({
            "question_id": question.question_id,
            "target_field": target_field,
            "value": opt.value,
            "thread_ts": thread_ts,
        })

        button = {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": opt.label[:75],  # Slack limit
                "emoji": True,
            },
            "action_id": f"triage_answer_{target_field}_{opt.option_id}",
            "value": button_value,
        }

        # Highlight recommended option with primary style
        if opt.is_recommended:
            button["style"] = "primary"

        button_elements.append(button)

    # Add actions block with buttons (max 5 per block)
    if button_elements:
        blocks.append({
            "type": "actions",
            "elements": button_elements[:5],
        })

        # Add descriptions as context if available
        descriptions = [
            f"* *{opt.label}*: {opt.description}"
            for opt in question.options
            if opt.description
        ]
        if descriptions:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "\n".join(descriptions[:4]),  # Max 4 descriptions
                }],
            })

    # Help text
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "_Click a button or just reply with more details._",
        }],
    })

    return blocks


def build_triage_complete_blocks() -> list[dict]:
    """Build blocks for triage completion acknowledgment.

    Returns:
        List of Slack blocks acknowledging triage completion.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Thanks! Let me process your request now...",
            },
        },
    ]

"""Scope gate UI blocks for AMBIGUOUS intent.

3-button scope gate with "Remember for this thread" option.
"""
from typing import Optional


def build_scope_gate_blocks(
    message_preview: str,
    include_remember: bool = True,
) -> list[dict]:
    """Build scope gate blocks for AMBIGUOUS intent.

    Shows 3 buttons:
    - "Review" - Route to review flow
    - "Create ticket" - Route to ticket flow
    - "Not now" - Dismiss and stop

    Plus optional "Remember for this thread" checkbox.

    Args:
        message_preview: First ~50 chars of user message for context
        include_remember: Whether to include remember checkbox

    Returns:
        Slack blocks for scope gate
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"I'm not sure what you'd like me to do with:\n> _{message_preview[:50]}{'...' if len(message_preview) > 50 else ''}_\n\nWhat would you like?",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Review / Analyze"},
                    "action_id": "scope_gate_review",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Create Ticket"},
                    "action_id": "scope_gate_ticket",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not now"},
                    "action_id": "scope_gate_dismiss",
                },
            ],
        },
    ]

    if include_remember:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Tip: You can select 'Remember' to set a default for this thread_",
            },
            "accessory": {
                "type": "checkboxes",
                "action_id": "scope_gate_remember",
                "options": [
                    {
                        "text": {"type": "mrkdwn", "text": "Remember for this thread"},
                        "value": "remember",
                    },
                ],
            },
        })

    return blocks


def build_scope_gate_dismissed_blocks() -> list[dict]:
    """Blocks shown after user selects 'Not now'."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Got it. Just @ me when you're ready.",
            },
        },
    ]


def build_scope_gate_remembered_blocks(intent: str) -> list[dict]:
    """Blocks shown after user selects an option with 'Remember'."""
    intent_display = "Review" if intent == "review" else "Create Ticket"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Got it. I'll default to *{intent_display}* for this thread. You can use `/maro forget` to clear this.",
            },
        },
    ]

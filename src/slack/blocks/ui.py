"""Slack blocks for UI elements: hints, buttons, help, personas."""

from typing import Optional


def build_persona_indicator(
    persona: str,
    message_count: int,
    max_indicator_messages: int = 2,
) -> Optional[str]:
    """Build persona indicator prefix for messages.

    Only shows indicator on first 1-2 messages after switch.

    Args:
        persona: Current persona name.
        message_count: Messages since persona change.
        max_indicator_messages: How many messages to show indicator.

    Returns:
        Indicator prefix string or None if past threshold.
    """
    if message_count >= max_indicator_messages:
        return None

    indicators = {
        "pm": ":memo:",
        "security": ":shield:",
        "architect": ":building_construction:",
    }

    emoji = indicators.get(persona, ":memo:")
    names = {
        "pm": "PM",
        "security": "Security",
        "architect": "Architect",
    }

    return f"{emoji} *{names.get(persona, 'PM')}:*"


def build_hint_with_buttons(message: str, buttons: list[dict]) -> list[dict]:
    """Build hint message with action buttons.

    Used for contextual hints that offer choices (e.g., persona selection).

    Args:
        message: Hint text to display
        buttons: List of {text, value} dicts for button options

    Returns:
        Slack blocks with message and action buttons
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn["text"], "emoji": True},
                    "action_id": f"hint_select_{btn['value']}",
                    "value": btn["value"],
                }
                for btn in buttons
            ]
        }
    ]
    return blocks


def build_welcome_blocks() -> list[dict]:
    """Build pinned quick-reference message for channel join.

    This is installation instructions, not a greeting.
    Posted once when MARO joins a channel.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*MARO is active in this channel*\n\nI help turn discussions into Jira tickets and keep context in sync."
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Try:*\n* `@MARO Create a Jira story for...`\n* `@MARO What do you think about this?`\n* `@MARO Review this as security`"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Commands:*\n* `/maro status` - show channel settings\n* `/maro help` - quick help\n* `/persona pm | architect | security`"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "I stay silent unless you mention me."
                }
            ]
        }
    ]

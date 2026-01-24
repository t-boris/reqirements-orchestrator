"""Decision card blocks for Slack UI.

Four visual states matching psychological weight (from CONTEXT.md):
1. Draft/Discussion mode -> Compact inline card (lightweight, tentative)
2. Approval moment -> Full decision block (heavy, "are you sure?")
3. Approved -> Compact but authoritative (infrastructure, not conversational)
4. Commit log -> Ultra compact (pure signal)

Same object, four visual identities: idea -> proposal -> law -> record
"""
import json
from typing import Optional

from src.schemas.decision import Decision, DecisionStatus, DecisionType


def build_compact_draft_card(
    decision: Decision,
) -> list[dict]:
    """Build compact inline card for PROPOSED decision.

    Used during discussion when decision is fluid and tentative.
    Click expands to show full details.

    Format:
    {type_emoji} Proposed decision:
    {title}
    [Edit] [Approve] [Discard]
    """
    # Decision type emoji
    type_emoji = _get_type_emoji(decision.decision_type)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{type_emoji} *Proposed decision:*\n{decision.title}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "decision_edit",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "decision_approve",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Discard"},
                    "style": "danger",
                    "action_id": "decision_discard",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
            ],
        },
    ]

    return blocks


def _get_type_emoji(decision_type: DecisionType) -> str:
    """Get emoji for decision type."""
    return {
        DecisionType.ARCH: "🧠",        # Architecture
        DecisionType.SCOPE: "📐",       # Scope
        DecisionType.CONSTRAINT: "🔒",  # Constraint
        DecisionType.PRIORITY: "⚡",    # Priority
        DecisionType.STRUCTURE: "🏗️",   # Structure
        DecisionType.PROCESS: "⚙️",     # Process
    }.get(decision_type, "🧠")

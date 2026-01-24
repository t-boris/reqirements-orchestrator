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


def build_approval_block(
    decision: Decision,
    linked_tickets: list[str] | None = None,
) -> list[dict]:
    """Build full decision block for approval moment.

    This is the "commit screen" — must feel heavy and formal.
    Shows what will happen when approved.

    Format:
    ━━━━━━━━━━━━━━━━━━━━━━
    {type_emoji} Decision DEC-{id} ({type}) — Ready for approval

    Title:
    {title}

    Description:
    {description}

    Will update Jira:
    - SCRUM-123
    - SCRUM-456

    Version: v{version}
    Status: PROPOSED
    ━━━━━━━━━━━━━━━━━━━━━━

    [Approve decision]   [Edit]   [Cancel]
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()

    # Build Jira tickets section
    jira_section = ""
    if linked_tickets:
        jira_list = "\n".join(f"• {key}" for key in linked_tickets)
        jira_section = f"\n\n*Will update Jira:*\n{jira_list}"

    blocks = [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{type_emoji} *Decision DEC-{decision.id[:8]}* ({type_label}) — Ready for approval",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Title:*\n{decision.title}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description:*\n{decision.description}",
            },
        },
    ]

    # Add Jira section if tickets linked
    if jira_section:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": jira_section,
            },
        })

    # Metadata
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Version: v{decision.version} | Status: {decision.status.value.upper()}",
            },
        ],
    })

    blocks.append({"type": "divider"})

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve decision"},
                "style": "primary",
                "action_id": "decision_approve",
                "value": json.dumps({
                    "decision_id": decision.id,
                    "version": decision.version,
                }),
            },
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
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": "decision_cancel",
                "value": json.dumps({
                    "decision_id": decision.id,
                    "version": decision.version,
                }),
            },
        ],
    })

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

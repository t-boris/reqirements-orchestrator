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


def build_rich_context_blocks(decision: Decision) -> list[dict]:
    """Build Slack blocks for decision rich context.

    Returns collapsible sections for rationale, context, alternatives, consequences.
    Empty list if no rich context.
    """
    if not decision.has_rich_context():
        return []

    blocks = []

    # Rationale section
    if decision.rationale:
        rationale_text = []
        for item in decision.rationale:
            prefix = "▸" if item.weight == "primary" else "•"
            rationale_text.append(f"{prefix} {item.text}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Rationale:*\n" + "\n".join(rationale_text),
            },
        })

    # Context section
    if decision.context:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Context (before):*\n{decision.context}",
            },
        })

    # Alternatives section
    if decision.alternatives:
        alt_text = []
        for alt in decision.alternatives:
            alt_text.append(f"• *{alt.option}*")
            alt_text.append(f"  _Rejected: {alt.rejected_reason}_")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Alternatives Considered:*\n" + "\n".join(alt_text),
            },
        })

    # Consequences section
    if decision.consequences:
        cons_text = []
        for cons in decision.consequences:
            severity_emoji = {
                "minor": "🟢",
                "moderate": "🟡",
                "major": "🔴",
            }.get(cons.severity, "⚪")
            cons_text.append(f"{severity_emoji} *{cons.area}:* {cons.impact}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Consequences:*\n" + "\n".join(cons_text),
            },
        })

    return blocks


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


def build_approved_card(
    decision: Decision,
    linked_tickets: list[str] | None = None,
) -> list[dict]:
    """Build compact but authoritative card for APPROVED decision.

    No longer conversational — this is infrastructure.

    Format:
    {type_emoji} DEC-{id} v{version} ({type}) — Approved
    {title}
    Applies to: SCRUM-123, SCRUM-456
    [Change] [Deprecate] [Show history]
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()

    applies_to = ""
    if linked_tickets:
        applies_to = f"\n_Applies to: {', '.join(linked_tickets)}_"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{type_emoji} *DEC-{decision.id[:8]}* v{decision.version} ({type_label}) — *Approved*\n"
                    f"{decision.title}{applies_to}"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Change"},
                    "action_id": "decision_change",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deprecate"},
                    "action_id": "decision_deprecate",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Show history"},
                    "action_id": "decision_history",
                    "value": json.dumps({
                        "decision_id": decision.id,
                    }),
                },
            ],
        },
    ]

    return blocks


def build_commit_log_entry(
    decision: Decision,
    linked_tickets: list[str] | None = None,
    approved_by: str | None = None,
) -> list[dict]:
    """Build ultra-compact commit log entry for Channel Work Board.

    Pure signal, no fluff. Like git log.

    Format:
    {type_emoji} DEC-{id} v{version}
    + {type}: {title}
    Affects: SCRUM-123, SCRUM-456
    by @user
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.capitalize()

    affects = ""
    if linked_tickets:
        affects = f"\nAffects: {', '.join(linked_tickets)}"

    by_user = ""
    if approved_by:
        by_user = f"\nby <@{approved_by}>"

    blocks = [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"{type_emoji} *DEC-{decision.id[:8]}* v{decision.version}\n"
                        f"+ {type_label}: {decision.title}{affects}{by_user}"
                    ),
                },
            ],
        },
    ]

    return blocks


def build_deprecated_decision_blocks(
    decision: Decision,
    replacement: Decision | None = None,
) -> list[dict]:
    """Build blocks for deprecated decision.

    Message is not deleted — marked as historical with pointer.

    Format:
    {type_emoji} Decision DEC-{id} ({type})
    Status: DEPRECATED
    Replaced by: DEC-{replacement_id}

    [This decision is no longer active]
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()

    replacement_text = ""
    if replacement:
        replacement_text = f"\nReplaced by: DEC-{replacement.id[:8]}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{type_emoji} *Decision DEC-{decision.id[:8]}* ({type_label})\n"
                    f"Status: *DEPRECATED*{replacement_text}"
                ),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_This decision is no longer active_",
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

"""Contradiction detection for structured constraints.

Rule 3: Cross-Thread Context - Only checks accepted constraints.
Subject match + value differs = conflict.
"""

import logging
from typing import Optional
from slack_sdk.web import WebClient

from src.knowledge.store import KnowledgeStore
from src.knowledge.models import Constraint, ConstraintStatus
from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)


async def check_for_contradictions(
    epic_key: str,
    subject: str,
    proposed_value: str,
    store: KnowledgeStore,
) -> list[Constraint]:
    """Check if proposed constraint conflicts with existing accepted constraints.

    Returns list of conflicting constraints (same subject, different value).
    """
    conflicts = await store.find_conflicting_constraints(
        epic_id=epic_key,
        subject=subject,
        value=proposed_value,
    )

    if conflicts:
        logger.info(
            f"Contradiction found",
            extra={
                "epic": epic_key,
                "subject": subject,
                "proposed": proposed_value,
                "conflicts": [c.value for c in conflicts],
            }
        )

    return conflicts


def build_contradiction_alert_blocks(
    subject: str,
    proposed_value: str,
    conflicts: list[Constraint],
    source_thread_ts: str,
) -> list[dict]:
    """Build blocks for contradiction alert.

    Shows the conflict and provides resolution actions.
    """
    blocks = []

    # Alert header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Potential Contradiction Detected",
            "emoji": True
        }
    })

    # Proposed constraint
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*New:* `{subject}` = `{proposed_value}`"
        }
    })

    # Existing conflicts
    conflict_text = "*Existing decisions:*\n"
    for c in conflicts:
        thread_link = f"<slack://channel?id={c.thread_ts}|Thread>"
        conflict_text += f"* `{c.subject}` = `{c.value}` ({thread_link})\n"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": conflict_text
        }
    })

    # Divider
    blocks.append({"type": "divider"})

    # Actions
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*How should we resolve this?*"
        }
    })

    # Encode conflict info in action values
    action_data = f"{subject}|{proposed_value}|{source_thread_ts}"

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Mark as conflict",
                    "emoji": True
                },
                "value": f"conflict:{action_data}",
                "action_id": "resolve_contradiction_conflict",
                "style": "danger",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Override previous",
                    "emoji": True
                },
                "value": f"override:{action_data}",
                "action_id": "resolve_contradiction_override",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Keep both (intentional)",
                    "emoji": True
                },
                "value": f"both:{action_data}",
                "action_id": "resolve_contradiction_both",
            },
        ]
    })

    # Context
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "Contradictions are detected only between accepted decisions with matching subjects."
        }]
    })

    return blocks


async def maybe_alert_contradiction(
    client: WebClient,
    identity: SessionIdentity,
    epic_key: str,
    subject: str,
    proposed_value: str,
    store: KnowledgeStore,
) -> bool:
    """Check for contradictions and post alert if found.

    Returns True if alert was posted, False otherwise.
    """
    conflicts = await check_for_contradictions(
        epic_key=epic_key,
        subject=subject,
        proposed_value=proposed_value,
        store=store,
    )

    if not conflicts:
        return False

    blocks = build_contradiction_alert_blocks(
        subject=subject,
        proposed_value=proposed_value,
        conflicts=conflicts,
        source_thread_ts=identity.thread_ts,
    )

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f"Contradiction detected: {subject}",
        blocks=blocks,
    )

    return True


async def get_constraints_summary(
    epic_key: str,
    store: KnowledgeStore,
) -> str:
    """Get human-readable summary of constraints for an Epic.

    Answers: "What constraints exist for this epic?"
    """
    constraints = await store.get_constraints_for_epic(
        epic_id=epic_key,
        status=ConstraintStatus.ACCEPTED,
    )

    if not constraints:
        return f"No accepted constraints for {epic_key} yet."

    lines = [f"*Accepted constraints for {epic_key}:*\n"]
    for c in constraints:
        lines.append(f"* `{c.subject}` = `{c.value}`")

    return "\n".join(lines)

"""Conflict resolution blocks for Jira sync (Phase 23.4).

Shows when both Slack and Jira changed the same section since last sync.
User must choose: Keep Slack / Keep Jira / Merge manually.

UX from 23-CONTEXT.md:
```
Sync conflict for PROJ-123 (Architecture Notes)
Slack version (commit C-0091): …
Jira version (edited by @alex): …
[Keep Slack] [Keep Jira] [Merge manually]
```
"""
import json
from typing import Any


def build_conflict_blocks(
    workitem_id: str,
    jira_key: str,
    conflicts: list[dict[str, Any]],
    *,
    channel_id: str,
) -> list[dict[str, Any]]:
    """Build blocks for sync conflict resolution.

    Args:
        workitem_id: WorkItem UUID
        jira_key: Jira issue key
        conflicts: List of conflict dicts with field, section, slack_value, jira_value
        channel_id: Channel for context

    Returns:
        List of Slack blocks
    """
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Sync conflict for {jira_key}",
            "emoji": True,
        }
    })

    # Show each conflict
    for i, conflict in enumerate(conflicts):
        section = conflict.get("section", conflict.get("field", "unknown"))
        slack_value = conflict.get("slack_value", "")
        jira_value = conflict.get("jira_value", "")

        # Section header
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Section: {section.replace('_', ' ').title()}*",
            }
        })

        # Slack version (truncated)
        slack_preview = _truncate(slack_value, 300)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Slack version:*\n```{slack_preview}```",
            }
        })

        # Jira version (truncated)
        jira_preview = _truncate(jira_value, 300)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Jira version:*\n```{jira_preview}```",
            }
        })

        # Resolution buttons for this conflict
        conflict_value = json.dumps({
            "workitem_id": workitem_id,
            "jira_key": jira_key,
            "section": section,
            "conflict_index": i,
            "channel_id": channel_id,
        })

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Keep Slack", "emoji": True},
                    "style": "primary",
                    "action_id": f"resolve_conflict_slack_{i}",
                    "value": conflict_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Keep Jira", "emoji": True},
                    "action_id": f"resolve_conflict_jira_{i}",
                    "value": conflict_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View full diff", "emoji": True},
                    "action_id": f"view_conflict_diff_{i}",
                    "value": conflict_value,
                },
            ]
        })

        if i < len(conflicts) - 1:
            blocks.append({"type": "divider"})

    # Footer with resolve all option
    if len(conflicts) > 1:
        resolve_all_value = json.dumps({
            "workitem_id": workitem_id,
            "jira_key": jira_key,
            "channel_id": channel_id,
        })

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Keep all Slack versions", "emoji": True},
                    "action_id": "resolve_all_slack",
                    "value": resolve_all_value,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Confirm"},
                        "text": {"type": "mrkdwn", "text": "This will overwrite all Jira changes with Slack versions."},
                        "confirm": {"type": "plain_text", "text": "Keep Slack"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Keep all Jira versions", "emoji": True},
                    "action_id": "resolve_all_jira",
                    "value": resolve_all_value,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Confirm"},
                        "text": {"type": "mrkdwn", "text": "This will overwrite all Slack changes with Jira versions."},
                        "confirm": {"type": "plain_text", "text": "Keep Jira"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
            ]
        })

    return blocks


def build_conflict_resolved_blocks(
    jira_key: str,
    resolution: str,  # "slack" | "jira" | "merged"
    section: str | None = None,
) -> list[dict[str, Any]]:
    """Build blocks shown after conflict is resolved.

    Args:
        jira_key: Jira issue key
        resolution: Which version was kept
        section: Specific section if single conflict

    Returns:
        List of Slack blocks
    """
    if resolution == "slack":
        text = f"Conflict resolved for {jira_key} — Slack version kept"
        if section:
            text += f" ({section.replace('_', ' ').title()})"
    elif resolution == "jira":
        text = f"Conflict resolved for {jira_key} — Jira version kept"
        if section:
            text += f" ({section.replace('_', ' ').title()})"
    else:
        text = f"Conflict resolved for {jira_key} — merged"

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text}
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "_Sync will complete on next update._"}
            ]
        }
    ]

    return blocks


def _truncate(text: str, max_length: int) -> str:
    """Truncate text with ellipsis.

    Args:
        text: Text to truncate
        max_length: Maximum length

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."

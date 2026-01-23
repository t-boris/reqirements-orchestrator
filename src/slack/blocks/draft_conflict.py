"""Draft conflict UI blocks for multi-user support (Phase 27.3).

Displays conflicts between multiple users' contributions to a draft.
Provides resolution buttons: "Keep original" / "Use new".
Shows full attribution for both sides.

Different from conflict.py which handles Jira sync conflicts (Phase 23.4).
This handles multi-user draft conflicts within the same thread.
"""
from typing import Any

from src.schemas.conflict import DraftConflict


def build_draft_conflict_blocks(conflict: DraftConflict) -> list[dict[str, Any]]:
    """Build Slack blocks for draft conflict display with resolution buttons.

    Shows both conflicting statements with their attributions,
    and provides buttons to choose which to keep.

    Args:
        conflict: The DraftConflict to display

    Returns:
        List of Slack blocks
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":warning: *Conflict Detected*"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": conflict.format_for_display()
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Which should we follow?*"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": conflict.existing.label or "Keep original",
                        "emoji": True
                    },
                    "action_id": "draft_conflict_resolve_existing",
                    "value": conflict.conflict_id,
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": conflict.proposed.label or "Use new",
                        "emoji": True
                    },
                    "action_id": "draft_conflict_resolve_proposed",
                    "value": conflict.conflict_id
                }
            ]
        }
    ]

    return blocks


def build_draft_conflict_resolved_blocks(
    conflict: DraftConflict,
    resolution: str,
    resolved_by_name: str,
) -> list[dict[str, Any]]:
    """Build blocks shown after conflict is resolved.

    Replaces the conflict buttons with resolution summary.

    Args:
        conflict: The resolved DraftConflict
        resolution: Which side was chosen ('existing' or 'proposed')
        resolved_by_name: Display name of user who resolved

    Returns:
        List of Slack blocks
    """
    # Get the chosen content
    if resolution == "existing":
        chosen_label = conflict.existing.label or "original"
        chosen_content = conflict.existing.content
    else:
        chosen_label = conflict.proposed.label or "new"
        chosen_content = conflict.proposed.content

    # Truncate content for display
    if len(chosen_content) > 100:
        chosen_content = chosen_content[:97] + "..."

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":white_check_mark: *Conflict resolved*\n"
                    f"Chose: *{chosen_label}*\n"
                    f"> {chosen_content}\n"
                    f"Resolved by {resolved_by_name}"
                )
            }
        }
    ]

    return blocks


def build_unresolved_conflicts_notice(count: int) -> list[dict[str, Any]]:
    """Build notice about unresolved conflicts blocking draft.

    Shown when user tries to approve/continue with pending conflicts.

    Args:
        count: Number of unresolved conflicts

    Returns:
        List of Slack blocks
    """
    text = (
        f":warning: *{count} unresolved conflict{'s' if count > 1 else ''}*\n"
        f"Please resolve the conflict{'s' if count > 1 else ''} above before continuing."
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text
            }
        }
    ]

    return blocks

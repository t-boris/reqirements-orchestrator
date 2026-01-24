"""Preflight sync UI blocks for Slack (Phase 29).

Builds Slack Block Kit UI for each conflict type:
1. IDEMPOTENT - Info message, no buttons
2. SAFE_DRIFT - Warning with proceed default
3. REAL_CONFLICT - Block with choice required
4. STRUCTURAL - Block with explanation

UX per conflict type from phase-29-CONTEXT.md.
"""
import json
from typing import Any

from src.sync.preflight import ConflictType, FieldChange, PreflightResult


def build_preflight_blocks(result: PreflightResult) -> list[dict[str, Any]]:
    """Build Slack blocks for preflight result.

    Dispatches to specific builder based on conflict_type.

    Args:
        result: PreflightResult from PreflightService.

    Returns:
        List of Slack Block Kit blocks.
    """
    if result.conflict_type == ConflictType.IDEMPOTENT:
        return _build_idempotent_blocks(result)
    elif result.conflict_type == ConflictType.SAFE_DRIFT:
        return _build_safe_drift_blocks(result)
    elif result.conflict_type == ConflictType.REAL_CONFLICT:
        return _build_real_conflict_blocks(result)
    elif result.conflict_type == ConflictType.STRUCTURAL:
        return _build_structural_blocks(result)
    else:
        # Fallback - shouldn't happen
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Unknown conflict type for {result.jira_key}",
                },
            }
        ]


def _build_idempotent_blocks(result: PreflightResult) -> list[dict[str, Any]]:
    """Build blocks for IDEMPOTENT conflict - operation already done.

    UX:
    ```
    :information_source: SCRUM-163 is already Done in Jira.
    Local state updated.
    ```

    No buttons - auto-success.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":information_source: {result.message}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Local state updated._",
                }
            ],
        },
    ]


def _build_safe_drift_blocks(result: PreflightResult) -> list[dict[str, Any]]:
    """Build blocks for SAFE_DRIFT conflict - non-overlapping changes.

    UX:
    ```
    :warning: SCRUM-163 was updated in Jira since last sync.
    Fields changed: assignee.
    Your operation affects: labels.

    No overlap detected.
    [Apply my change] [Pull Jira changes only] [Cancel]
    ```
    """
    blocks: list[dict[str, Any]] = []

    # Warning header
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: {result.message}",
            },
        }
    )

    # Show detected changes if any
    if result.detected_changes:
        changes_text = _format_changes(result.detected_changes)
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": changes_text,
                    }
                ],
            }
        )

    # Action buttons with JSON payloads
    payload = json.dumps(
        {
            "jira_key": result.jira_key,
            "operation": result.intended_operation,
            "fields": result.intended_fields,
        }
    )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Apply my change", "emoji": True},
                    "style": "primary",
                    "action_id": "preflight_proceed",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Pull Jira changes only", "emoji": True},
                    "action_id": "preflight_pull_only",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "preflight_cancel",
                    "value": payload,
                },
            ],
        }
    )

    return blocks


def _build_real_conflict_blocks(result: PreflightResult) -> list[dict[str, Any]]:
    """Build blocks for REAL_CONFLICT - overlapping field changes.

    UX:
    ```
    :rotating_light: Conflict detected for SCRUM-163

    Both Jira and Channel modified:
    - Description

    Jira version updated by @alex at 13:29
    Channel version updated in this channel at 13:21

    [Use Jira version] [Use Channel version] [Show diff] [Cancel]
    ```
    """
    blocks: list[dict[str, Any]] = []

    # Error header
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Conflict detected for {result.jira_key}",
                "emoji": True,
            },
        }
    )

    # Conflict details
    if result.overlapping_fields:
        overlap_list = "\n".join(f"- {f.title()}" for f in result.overlapping_fields)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Both Jira and Channel modified the same fields:\n{overlap_list}",
                },
            }
        )

    # Show change details
    if result.detected_changes:
        for change in result.detected_changes:
            if change.field in result.overlapping_fields:
                change_text = _format_single_change(change)
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": change_text,
                        },
                    }
                )

    blocks.append({"type": "divider"})

    # Action buttons with JSON payloads
    payload = json.dumps(
        {
            "jira_key": result.jira_key,
            "operation": result.intended_operation,
            "fields": result.intended_fields,
            "overlapping": result.overlapping_fields,
        }
    )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Use Jira version", "emoji": True},
                    "action_id": "preflight_use_jira",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Use Channel version", "emoji": True},
                    "style": "primary",
                    "action_id": "preflight_use_channel",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Show diff", "emoji": True},
                    "action_id": "preflight_show_diff",
                    "value": payload,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "action_id": "preflight_cancel",
                    "value": payload,
                },
            ],
        }
    )

    return blocks


def _build_structural_blocks(result: PreflightResult) -> list[dict[str, Any]]:
    """Build blocks for STRUCTURAL conflict - impossible operation.

    UX:
    ```
    :x: Cannot apply operation.

    SCRUM-163 is in status "Cancelled".
    Transition to Done is not allowed.

    [Reopen issue] [Cancel operation]
    ```
    """
    blocks: list[dict[str, Any]] = []

    # Error header
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":x: *Cannot apply operation.*\n\n{result.message}",
            },
        }
    )

    blocks.append({"type": "divider"})

    # Action buttons with JSON payloads
    payload = json.dumps(
        {
            "jira_key": result.jira_key,
            "operation": result.intended_operation,
            "fields": result.intended_fields,
        }
    )

    # Different buttons based on operation context
    buttons: list[dict[str, Any]] = []

    # If it's a deleted issue, offer different options
    if "not found" in result.message.lower() or "deleted" in result.message.lower():
        buttons.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Remove from tracking", "emoji": True},
                "action_id": "preflight_remove_tracking",
                "value": payload,
            }
        )
    else:
        # For status conflicts, offer reopen
        buttons.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reopen issue", "emoji": True},
                "action_id": "preflight_reopen",
                "value": payload,
            }
        )

    buttons.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Cancel operation", "emoji": True},
            "action_id": "preflight_cancel",
            "value": payload,
        }
    )

    blocks.append({"type": "actions", "elements": buttons})

    return blocks


def _format_changes(changes: list[FieldChange]) -> str:
    """Format list of field changes for context block."""
    lines = []
    for change in changes:
        if change.local_value and change.jira_value:
            lines.append(f"_{change.field}_: {change.local_value} -> {change.jira_value}")
        elif change.jira_value:
            lines.append(f"_{change.field}_: (empty) -> {change.jira_value}")
        else:
            lines.append(f"_{change.field}_: {change.local_value} -> (empty)")

        if change.changed_by:
            lines[-1] += f" (by <@{change.changed_by}>)"

    return "\n".join(lines)


def _format_single_change(change: FieldChange) -> str:
    """Format a single field change with more detail."""
    lines = [f"*{change.field.title()}:*"]

    if change.jira_value:
        jira_preview = _truncate(change.jira_value, 200)
        lines.append(f"Jira version: `{jira_preview}`")

    if change.local_value:
        local_preview = _truncate(change.local_value, 200)
        lines.append(f"Channel version: `{local_preview}`")

    if change.changed_by:
        at_text = ""
        if change.changed_at:
            at_text = f" at {change.changed_at.strftime('%H:%M')}"
        lines.append(f"Changed by <@{change.changed_by}>{at_text}")

    return "\n".join(lines)


def _truncate(text: str, max_length: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."

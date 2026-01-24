"""Sync report block builders for Slack output.

Provides UI components for /maro sync diagnostic command:
- Summary header with stats
- Changed section (with changes per issue)
- In sync section (collapsed if many)
- Missing locally section (with track buttons)
- Local only section (with remove buttons)

Button payloads use JSON format:
- sync_track_all: {"channel_id": "...", "keys": [...]}
- sync_track_selected: {"channel_id": "...", "keys": [...]}
- sync_remove: {"channel_id": "...", "key": "..."}
"""
import json
import logging
from typing import Optional

from src.sync.jira_sync import SyncResult, SyncIssue

logger = logging.getLogger(__name__)


def build_sync_report_blocks(
    result: SyncResult,
    jira_base_url: Optional[str] = None,
) -> list[dict]:
    """Build Slack blocks for sync report.

    Sections (from CONTEXT.md):
    1. Summary header with stats
    2. Changed section (with changes per issue)
    3. In sync section (collapsed if many)
    4. Missing locally section (with track buttons)
    5. Local only section (with remove buttons)

    Args:
        result: SyncResult from JiraSyncService.sync_channel()
        jira_base_url: Base URL for Jira links (optional)

    Returns:
        List of Slack Block Kit blocks
    """
    blocks: list[dict] = []

    # Header with stats
    blocks.extend(_build_header_section(result))

    # Changed section
    if result.changed:
        blocks.extend(_build_changed_section(result.changed, jira_base_url))

    # In sync section
    if result.in_sync:
        blocks.extend(_build_in_sync_section(result.in_sync, jira_base_url))

    # Missing locally section
    if result.missing_locally:
        blocks.extend(
            _build_missing_locally_section(
                result.missing_locally,
                result.channel_id,
                jira_base_url,
            )
        )

    # Local only section
    if result.local_only:
        blocks.extend(
            _build_local_only_section(
                result.local_only,
                result.channel_id,
                jira_base_url,
            )
        )

    # Errors section (if any)
    if result.errors:
        blocks.extend(_build_errors_section(result.errors))

    # Footer with timestamp
    timestamp = result.synced_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Synced at {timestamp} | {result.total_checked} issues checked"
        }]
    })

    return blocks


def _build_header_section(result: SyncResult) -> list[dict]:
    """Build header section with sync summary."""
    # Calculate totals
    total_synced = result.total_checked
    changes_detected = len(result.changed)
    in_sync_count = len(result.in_sync)
    missing_count = len(result.missing_locally)
    local_only_count = len(result.local_only)

    # Build summary text
    if total_synced == 0:
        summary_text = "No issues tracked in this channel"
        emoji = ":information_source:"
    elif changes_detected == 0 and missing_count == 0 and local_only_count == 0:
        summary_text = f"All {total_synced} issues in sync with Jira"
        emoji = ":white_check_mark:"
    else:
        summary_text = f"Synced {total_synced} tickets with Jira"
        emoji = ":arrows_counterclockwise:"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Sync Report",
                "emoji": True,
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{summary_text}*",
            }
        },
    ]

    # Stats line
    stats_parts = []
    if changes_detected > 0:
        stats_parts.append(f":warning: Changes detected: *{changes_detected}*")
    if in_sync_count > 0:
        stats_parts.append(f":white_check_mark: In sync: *{in_sync_count}*")
    if missing_count > 0:
        stats_parts.append(f":clipboard: Missing locally: *{missing_count}*")
    if local_only_count > 0:
        stats_parts.append(f":ghost: Local only: *{local_only_count}*")

    if stats_parts:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(stats_parts),
            }
        })

    blocks.append({"type": "divider"})

    return blocks


def _build_changed_section(
    changed: list[SyncIssue],
    jira_base_url: Optional[str],
) -> list[dict]:
    """Build changed section showing detected changes."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Changes detected* ({len(changed)} issue{'s' if len(changed) != 1 else ''})",
            }
        },
    ]

    # List each changed issue with its changes
    for issue in changed[:10]:  # Limit to 10 for UI
        link = _make_issue_link(issue.jira_key, jira_base_url)

        # Format changes for this issue
        change_lines = []
        for change in issue.changes:
            old_val = change.old_value or "(none)"
            new_val = change.new_value or "(none)"
            # Truncate long values
            if len(old_val) > 30:
                old_val = old_val[:27] + "..."
            if len(new_val) > 30:
                new_val = new_val[:27] + "..."

            change_lines.append(
                f"  _{change.field}_: `{old_val}` -> `{new_val}`"
            )

        change_text = "\n".join(change_lines)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"* {link}: {issue.summary[:50]}{'...' if len(issue.summary) > 50 else ''}\n{change_text}",
            }
        })

    if len(changed) > 10:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_... and {len(changed) - 10} more_"
            }]
        })

    blocks.append({"type": "divider"})

    return blocks


def _build_in_sync_section(
    in_sync: list[SyncIssue],
    jira_base_url: Optional[str],
) -> list[dict]:
    """Build in-sync section (collapsed if many)."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *In sync* ({len(in_sync)} issue{'s' if len(in_sync) != 1 else ''})",
            }
        },
    ]

    # Show summary only if more than 5 issues
    if len(in_sync) <= 5:
        for issue in in_sync:
            link = _make_issue_link(issue.jira_key, jira_base_url)
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"{link}: {issue.summary[:60]}{'...' if len(issue.summary) > 60 else ''} ({issue.status})"
                }]
            })
    else:
        # Just show count for many issues
        keys = ", ".join(issue.jira_key for issue in in_sync[:5])
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"{keys}... and {len(in_sync) - 5} more"
            }]
        })

    blocks.append({"type": "divider"})

    return blocks


def _build_missing_locally_section(
    missing: list[SyncIssue],
    channel_id: str,
    jira_base_url: Optional[str],
) -> list[dict]:
    """Build missing locally section with track buttons."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":clipboard: *Missing locally* ({len(missing)} issue{'s' if len(missing) != 1 else ''})",
            }
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "These issues exist in Jira under tracked epics but are not in this channel's registry:"
            }]
        },
    ]

    # List missing issues
    for issue in missing[:10]:  # Limit to 10 for UI
        link = _make_issue_link(issue.jira_key, jira_base_url)
        issue_type = issue.issue_type.capitalize() if issue.issue_type else "Issue"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"* {link}: {issue.summary[:50]}{'...' if len(issue.summary) > 50 else ''} ({issue_type})",
            }
        })

    if len(missing) > 10:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_... and {len(missing) - 10} more_"
            }]
        })

    # Action buttons
    all_keys = [issue.jira_key for issue in missing]
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Track All"},
                "action_id": "sync_track_all",
                "value": json.dumps({
                    "channel_id": channel_id,
                    "keys": all_keys,
                }),
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Ignore"},
                "action_id": "sync_ignore",
                "value": json.dumps({}),
            },
        ]
    })

    blocks.append({"type": "divider"})

    return blocks


def _build_local_only_section(
    local_only: list[SyncIssue],
    channel_id: str,
    jira_base_url: Optional[str],
) -> list[dict]:
    """Build local only section with remove buttons."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":ghost: *Local only* ({len(local_only)} issue{'s' if len(local_only) != 1 else ''})",
            }
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "These issues are tracked but not found in Jira (may be deleted):"
            }]
        },
    ]

    # List local-only issues with individual remove buttons
    for issue in local_only[:5]:  # Limit to 5 for UI
        link = _make_issue_link(issue.jira_key, jira_base_url)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"* {link}: {issue.summary[:50]}{'...' if len(issue.summary) > 50 else ''}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Remove"},
                "action_id": "sync_remove",
                "value": json.dumps({
                    "channel_id": channel_id,
                    "key": issue.jira_key,
                }),
            }
        })

    if len(local_only) > 5:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_... and {len(local_only) - 5} more_"
            }]
        })

    blocks.append({"type": "divider"})

    return blocks


def _build_errors_section(errors: list[str]) -> list[dict]:
    """Build errors section."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":x: *Errors* ({len(errors)})",
            }
        },
    ]

    # List errors (truncated)
    error_text = "\n".join(f"* {err[:100]}" for err in errors[:5])
    if len(errors) > 5:
        error_text += f"\n_... and {len(errors) - 5} more errors_"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": error_text,
        }
    })

    blocks.append({"type": "divider"})

    return blocks


def _make_issue_link(jira_key: str, jira_base_url: Optional[str]) -> str:
    """Make Slack markdown link for Jira issue."""
    if jira_base_url:
        return f"<{jira_base_url}/browse/{jira_key}|{jira_key}>"
    return f"*{jira_key}*"

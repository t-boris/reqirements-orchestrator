"""Sync UI block builders.

Builds Slack blocks for sync summary, conflict detail, and resolution UI.
"""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def build_sync_summary_blocks(
    channel_name: str,
    plan,
    jira_base_url: str = "",
) -> list[dict]:
    """Build Slack blocks for sync summary.

    Args:
        channel_name: Channel name for display
        plan: SyncPlan from SyncEngine
        jira_base_url: Base URL for Jira links

    Returns:
        List of Slack block objects
    """
    from src.slack.sync_engine import SyncPlan

    blocks = []

    # Header
    total_changes = len(plan.auto_apply) + len(plan.needs_review)
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Jira Sync for #{channel_name}",
            "emoji": True,
        }
    })

    # No changes case
    if total_changes == 0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: *All tracked issues are in sync with Jira*"
            }
        })
        if plan.in_sync:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"{len(plan.in_sync)} issue{'s' if len(plan.in_sync) != 1 else ''} verified in sync"
                }]
            })
        return blocks

    # Auto-apply section
    if plan.auto_apply:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Auto-apply ({len(plan.auto_apply)} change{'s' if len(plan.auto_apply) != 1 else ''})*\n"
                        "These will be applied automatically:"
            }
        })

        for change in plan.auto_apply[:10]:  # Limit to 10 for UI
            icon = ":arrow_right:" if change.change_type == "slack_ahead" else ":arrow_left:"
            if jira_base_url:
                link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
            else:
                link = f"*{change.issue_key}*"

            if change.change_type == "slack_ahead":
                change_text = f"{icon} {link}: {change.field} `{change.jira_value or '(none)'}` -> `{change.slack_value}`"
            else:
                change_text = f"{icon} {link}: {change.field} updated in Jira to `{change.jira_value}`"

            source_hint = ""
            if change.source.startswith("decision:"):
                source_hint = " _(from decision)_"
            elif change.source == "jira_update":
                source_hint = " _(Jira update)_"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": change_text + source_hint}
            })

    # Needs review section (conflicts)
    if plan.needs_review:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Needs Review ({len(plan.needs_review)} conflict{'s' if len(plan.needs_review) != 1 else ''})*\n"
                        "These require your decision:"
            }
        })

        for i, change in enumerate(plan.needs_review[:5]):  # Limit to 5 conflicts
            if jira_base_url:
                link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
            else:
                link = f"*{change.issue_key}*"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: {link}: *{change.field}*\n"
                            f"  - Slack: `{change.slack_value or '(none)'}`\n"
                            f"  - Jira: `{change.jira_value or '(none)'}`"
                }
            })

            # Add resolution buttons for each conflict
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Use Slack"},
                        "action_id": f"sync_use_slack_{i}",
                        "value": json.dumps({
                            "issue_key": change.issue_key,
                            "field": change.field,
                            "value": change.slack_value,
                            "source_ts": change.source_ts,
                        }),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Use Jira"},
                        "action_id": f"sync_use_jira_{i}",
                        "value": json.dumps({
                            "issue_key": change.issue_key,
                            "field": change.field,
                            "value": change.jira_value,
                        }),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip"},
                        "action_id": f"sync_skip_{i}",
                        "value": json.dumps({
                            "issue_key": change.issue_key,
                            "field": change.field,
                        }),
                    },
                ]
            })

    # Action buttons
    blocks.append({"type": "divider"})
    action_elements = []

    if plan.auto_apply:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": f"Apply {len(plan.auto_apply)} Changes"},
            "action_id": "sync_apply_all",
            "value": json.dumps({
                "changes": [
                    {
                        "issue_key": c.issue_key,
                        "field": c.field,
                        "slack_value": c.slack_value,
                        "jira_value": c.jira_value,
                        "change_type": c.change_type,
                        "source_ts": c.source_ts,
                    }
                    for c in plan.auto_apply
                ]
            }),
            "style": "primary",
        })

    action_elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Cancel"},
        "action_id": "sync_cancel",
        "value": "cancel",
    })

    blocks.append({
        "type": "actions",
        "elements": action_elements,
    })

    return blocks


def build_conflict_detail_blocks(
    change,
    jira_base_url: str = "",
    source_preview: str = "",
) -> list[dict]:
    """Build detailed conflict resolution blocks with side-by-side comparison.

    Args:
        change: ChangeDetection object
        jira_base_url: Base URL for Jira links
        source_preview: Preview text from source message

    Returns:
        List of Slack block objects
    """
    blocks = []

    if jira_base_url:
        link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
    else:
        link = f"*{change.issue_key}*"

    # Header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":warning: *Conflict: {link} {change.field}*"
        }
    })

    # Slack version
    slack_text = change.slack_value or "(no value)"
    if len(slack_text) > 500:
        slack_text = slack_text[:497] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Slack version*{' (from decision)' if change.source.startswith('decision:') else ''}:\n>{slack_text}"
        }
    })

    # Jira version
    jira_text = change.jira_value or "(no value)"
    if len(jira_text) > 500:
        jira_text = jira_text[:497] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Jira version*:\n>{jira_text}"
        }
    })

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Slack Version"},
                "action_id": "sync_use_slack",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.slack_value,
                    "source_ts": change.source_ts,
                }),
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Jira Version"},
                "action_id": "sync_use_jira",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.jira_value,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "sync_skip",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                }),
            },
        ]
    })

    return blocks


def build_full_conflict_blocks(
    change,
    jira_base_url: str = "",
) -> list[dict]:
    """Build full-page conflict resolution blocks.

    Shows detailed side-by-side comparison with all resolution options.

    Args:
        change: ChangeDetection object
        jira_base_url: Base URL for Jira links

    Returns:
        List of Slack block objects
    """
    blocks = []

    if jira_base_url:
        link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
    else:
        link = f"*{change.issue_key}*"

    # Header with warning
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Conflict: {change.issue_key} {change.field}",
            "emoji": True,
        }
    })

    # Context about the conflict
    source_info = ""
    if change.source.startswith("decision:"):
        source_info = " (from architecture decision)"
    elif change.source == "jira_update":
        source_info = " (updated in Jira)"

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Conflict detected{source_info} - choose which version to keep"
        }]
    })

    blocks.append({"type": "divider"})

    # Slack version section
    slack_text = change.slack_value or "(no value)"
    if len(slack_text) > 2000:
        slack_text = slack_text[:1997] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Slack version:*"
        }
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f">{slack_text.replace(chr(10), chr(10) + '>')}"
        }
    })

    blocks.append({"type": "divider"})

    # Jira version section
    jira_text = change.jira_value or "(no value)"
    if len(jira_text) > 2000:
        jira_text = jira_text[:1997] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Jira version:*"
        }
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f">{jira_text.replace(chr(10), chr(10) + '>')}"
        }
    })

    blocks.append({"type": "divider"})

    # Resolution buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Slack Version"},
                "action_id": "sync_use_slack",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.slack_value,
                    "source_ts": change.source_ts,
                }),
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Jira Version"},
                "action_id": "sync_use_jira",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.jira_value,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Merge..."},
                "action_id": "sync_merge",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "slack_value": change.slack_value,
                    "jira_value": change.jira_value,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "sync_skip",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                }),
            },
        ]
    })

    return blocks

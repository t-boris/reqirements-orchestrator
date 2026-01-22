"""Debug mode block builders for Slack output.

Provides formatting functions for debug status, state dumps, and debug output.
"""
from datetime import datetime, timezone
from typing import Optional

from src.debug.collector import DebugCollector


def build_debug_status_blocks(
    enabled: bool,
    set_by: Optional[str],
    set_at: Optional[datetime],
    channel_mode: str,
    default_project: Optional[str],
    listening_enabled: bool,
    workitem_counts: dict[str, int],
    jira_registry_count: int,
) -> list[dict]:
    """Build debug status blocks showing quick health check.

    Args:
        enabled: Whether debug mode is enabled
        set_by: User ID who enabled debug mode
        set_at: When debug mode was enabled
        channel_mode: Current channel mode (project/feature/bugs/ops)
        default_project: Default Jira project key
        listening_enabled: Whether listening is enabled
        workitem_counts: Dict with 'draft' and 'active' counts
        jira_registry_count: Number of tracked Jira issues

    Returns:
        List of Slack Block Kit blocks
    """
    # Build status text
    if enabled:
        status_emoji = ":white_check_mark:"
        status_text = "ON"

        if set_by:
            set_by_mention = f"<@{set_by}>"
            if set_at:
                time_ago = _format_time_ago(set_at)
                enabled_info = f" (enabled by {set_by_mention} {time_ago})"
            else:
                enabled_info = f" (enabled by {set_by_mention})"
        else:
            enabled_info = ""
    else:
        status_emoji = ":x:"
        status_text = "OFF"
        enabled_info = ""

    listening_text = "ON" if listening_enabled else "OFF"
    draft_count = workitem_counts.get("draft", 0)
    active_count = workitem_counts.get("active", 0)
    total_workitems = draft_count + active_count

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Debug Status", "emoji": True}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Debug Mode:* {status_emoji} {status_text}{enabled_info}\n"
                    f"*Channel Mode:* {channel_mode}\n"
                    f"*Default Project:* {default_project or 'None'}\n"
                    f"*Listening:* {listening_text}"
                )
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Active WorkItems:* {total_workitems} "
                    f"({draft_count} draft, {active_count} active)\n"
                    f"*Jira Registry:* {jira_registry_count} issues linked"
                )
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Use `/maro debug on` to enable | `/maro debug state` for full dump"
                }
            ]
        }
    ]

    return blocks


def build_debug_state_blocks(
    channel_context: dict,
    workitems: list[dict],
    jira_registry: list[dict],
    recent_activity: Optional[dict] = None,
) -> list[dict]:
    """Build debug state blocks showing full internal state dump.

    Args:
        channel_context: Dict with channel context data
        workitems: List of work items with id, summary, status, item_type, jira_key
        jira_registry: List of tracked Jira issues with issue_key, status
        recent_activity: Optional dict with recent activity data

    Returns:
        List of Slack Block Kit blocks
    """
    import json

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Debug State Dump", "emoji": True}
        }
    ]

    # === Channel Context ===
    if channel_context:
        ctx_str = json.dumps(channel_context, indent=2, default=str)
        # Truncate if too long for Slack (3000 char limit per text block)
        if len(ctx_str) > 2800:
            ctx_str = ctx_str[:2800] + "\n... (truncated)"
    else:
        ctx_str = "No channel context found"

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*=== Channel Context ===*"}
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"```{ctx_str}```"}
    })

    # === WorkItem Registry ===
    drafts = [w for w in workitems if w.get("status") == "draft"]
    actives = [w for w in workitems if w.get("status") == "active"]

    workitem_lines = []
    if drafts:
        workitem_lines.append(f"DRAFT ({len(drafts)}):")
        for w in drafts[:5]:  # Limit to 5
            summary = w.get("summary", "")[:40]
            item_type = w.get("item_type", "unknown")
            workitem_lines.append(f"  - {w.get('id', '')[:8]}: \"{summary}\" ({item_type})")
        if len(drafts) > 5:
            workitem_lines.append(f"  ... and {len(drafts) - 5} more")

    if actives:
        workitem_lines.append(f"ACTIVE ({len(actives)}):")
        for w in actives[:5]:  # Limit to 5
            summary = w.get("summary", "")[:40]
            item_type = w.get("item_type", "unknown")
            jira_key = w.get("jira_key")
            jira_info = f" [{jira_key}]" if jira_key else ""
            workitem_lines.append(f"  - {w.get('id', '')[:8]}: \"{summary}\" ({item_type}){jira_info}")
        if len(actives) > 5:
            workitem_lines.append(f"  ... and {len(actives) - 5} more")

    workitem_str = "\n".join(workitem_lines) if workitem_lines else "No work items"

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*=== WorkItem Registry ===*"}
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"```{workitem_str}```"}
    })

    # === Jira Registry ===
    if jira_registry:
        jira_lines = [f"Tracked ({len(jira_registry)}):"]
        for issue in jira_registry[:10]:  # Limit to 10
            issue_key = issue.get("issue_key", "?")
            status = issue.get("status", "Unknown")
            jira_lines.append(f"  - {issue_key}: {status}")
        if len(jira_registry) > 10:
            jira_lines.append(f"  ... and {len(jira_registry) - 10} more")
        jira_str = "\n".join(jira_lines)
    else:
        jira_str = "No issues tracked"

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*=== Jira Registry ===*"}
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"```{jira_str}```"}
    })

    # Footer with timestamp
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"Generated at {now}"}
        ]
    })

    return blocks


def build_debug_output_blocks(
    collector: DebugCollector,
    truncate_prompts: int = 300,
) -> tuple[list[dict], Optional[str]]:
    """Build debug output blocks from a DebugCollector.

    Args:
        collector: DebugCollector with accumulated debug entries
        truncate_prompts: Max length for LLM prompts/responses in blocks

    Returns:
        Tuple of (blocks, full_content_for_file).
        If LLM prompts exceed truncate_prompts, full_content is non-None
        and should be uploaded as a file attachment.
    """
    # Get blocks from collector (already has truncation)
    blocks = collector.to_slack_blocks(truncate_prompts=truncate_prompts)

    # Check if any LLM call has prompts longer than truncate limit
    has_long_content = any(
        len(call.prompt) > truncate_prompts or len(call.response) > truncate_prompts
        for call in collector.llm_calls
    )

    # If content was truncated, provide full file content
    full_content = None
    if has_long_content:
        full_content = collector.to_file_content()

    return blocks, full_content


def _format_time_ago(dt: datetime) -> str:
    """Format datetime as human-readable time ago string."""
    now = datetime.now(timezone.utc)

    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    else:
        days = seconds // 86400
        return f"{days}d ago"

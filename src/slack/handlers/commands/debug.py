"""Debug command handlers: /maro debug [on|off|status|state].

Handles debug mode control and state inspection.
"""

import logging
from datetime import datetime, timezone

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def handle_debug_command(
    channel_id: str,
    team_id: str,
    user_id: str,
    action: str,
    client: WebClient,
    say,
):
    """Handle /maro debug command - view or control debug mode.

    Actions:
    - on: Enable debug mode
    - off: Disable debug mode
    - status: Quick health check (default)
    - state: Full internal state dump
    """
    from src.db import get_connection
    from src.db.debug_store import DebugStore

    try:
        async with get_connection() as conn:
            store = DebugStore(conn)
            await store.create_tables()

            if action == "on":
                config = await store.enable(channel_id, user_id)
                say(
                    text="Debug mode enabled. You'll see detailed processing info for messages in this channel.",
                    channel=channel_id,
                )
                logger.info(
                    "Debug mode enabled",
                    extra={
                        "channel_id": channel_id,
                        "enabled_by": user_id,
                    }
                )

            elif action == "off":
                config = await store.disable(channel_id, user_id)
                say(
                    text="Debug mode disabled.",
                    channel=channel_id,
                )
                logger.info(
                    "Debug mode disabled",
                    extra={
                        "channel_id": channel_id,
                        "disabled_by": user_id,
                    }
                )

            elif action == "state":
                # Full internal state dump
                blocks = await _build_debug_state_blocks(channel_id, team_id, conn)
                client.chat_postMessage(
                    channel=channel_id,
                    text="Debug State",
                    blocks=blocks,
                )

            else:
                # Default: status - quick health check
                blocks = await _build_debug_status_blocks(channel_id, conn)
                client.chat_postMessage(
                    channel=channel_id,
                    text="Debug Status",
                    blocks=blocks,
                )

    except Exception as e:
        logger.error(f"Failed to handle debug command: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't process the debug command. Please try again.",
            channel=channel_id,
        )


async def _build_debug_status_blocks(channel_id: str, conn) -> list[dict]:
    """Build debug status blocks showing quick health check."""
    from src.db.debug_store import DebugStore
    from src.db.channel_mode_store import ChannelModeStore
    from src.db import ListeningStore
    from src.db.workitem_store import WorkItemStore
    from src.slack.channel_tracker import ChannelIssueTracker

    # Gather state from various stores
    debug_store = DebugStore(conn)
    debug_config = await debug_store.get(channel_id)

    mode_store = ChannelModeStore(conn)
    mode_config = await mode_store.get(channel_id)

    # Get team_id from debug_config context or use default
    listening_store = ListeningStore(conn)
    # We need to query without team_id filter - get by channel
    listening_state = None
    try:
        # ListeningStore.get_state requires team_id, so we do a direct query
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT enabled FROM channel_listening WHERE channel_id = %s",
                (channel_id,),
            )
            row = await cur.fetchone()
            listening_enabled = row[0] if row else False
    except Exception:
        listening_enabled = False

    # Work item counts
    try:
        workitem_store = WorkItemStore(conn)
        workitems = await workitem_store.list_by_channel(channel_id)
        draft_count = sum(1 for w in workitems if w.status.value == "draft")
        active_count = sum(1 for w in workitems if w.status.value == "active")
    except Exception:
        draft_count = 0
        active_count = 0

    # Jira registry count
    try:
        tracker = ChannelIssueTracker(conn)
        tracked = await tracker.get_tracked_issues(channel_id)
        jira_count = len(tracked)
    except Exception:
        jira_count = 0

    # Build status text
    if debug_config and debug_config.enabled:
        status_emoji = ":white_check_mark:"
        status_text = "ON"
        set_by = f"<@{debug_config.set_by}>"
        # Calculate time ago
        if debug_config.set_at:
            delta = datetime.now(timezone.utc) - debug_config.set_at
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                minutes = int(delta.total_seconds() // 60)
                time_ago = f"{minutes}m ago"
            elif hours < 24:
                time_ago = f"{hours}h ago"
            else:
                days = hours // 24
                time_ago = f"{days}d ago"
            enabled_info = f" (enabled by {set_by} {time_ago})"
        else:
            enabled_info = f" (enabled by {set_by})"
    else:
        status_emoji = ":x:"
        status_text = "OFF"
        enabled_info = ""

    channel_mode = mode_config.mode.value if mode_config else "project"
    default_project = mode_config.primary_epic if mode_config else None
    listening_text = "ON" if listening_enabled else "OFF"

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
                    f"*Active WorkItems:* {draft_count + active_count} "
                    f"({draft_count} draft, {active_count} active)\n"
                    f"*Jira Registry:* {jira_count} issues linked"
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


async def _build_debug_state_blocks(channel_id: str, team_id: str, conn) -> list[dict]:
    """Build debug state blocks showing full internal state dump."""
    from src.db.debug_store import DebugStore
    from src.db.channel_mode_store import ChannelModeStore
    from src.db.channel_context_store import ChannelContextStore
    from src.db.workitem_store import WorkItemStore
    from src.slack.channel_tracker import ChannelIssueTracker
    import json

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Debug State Dump", "emoji": True}
        }
    ]

    # === Channel Context ===
    try:
        ctx_store = ChannelContextStore(conn)
        ctx = await ctx_store.get_by_channel(team_id, channel_id)
        if ctx:
            ctx_data = {
                "version": ctx.version,
                "default_project": ctx.config.default_jira_project,
                "trigger_rule": ctx.config.trigger_rule,
                "epic_binding": ctx.config.epic_binding_behavior,
                "active_epics": len(ctx.activity.active_epics),
                "work_items": ctx.activity.item_counts,
            }
            ctx_str = json.dumps(ctx_data, indent=2)
        else:
            ctx_str = "No channel context found"
    except Exception as e:
        ctx_str = f"Error: {e}"

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*=== Channel Context ===*"}
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"```{ctx_str}```"}
    })

    # === WorkItem Registry ===
    try:
        workitem_store = WorkItemStore(conn)
        workitems = await workitem_store.list_by_channel(channel_id)

        # Group by status
        drafts = [w for w in workitems if w.status.value == "draft"]
        actives = [w for w in workitems if w.status.value == "active"]

        workitem_lines = []
        if drafts:
            workitem_lines.append(f"DRAFT ({len(drafts)}):")
            for w in drafts[:5]:  # Limit to 5
                workitem_lines.append(f"  - {w.id[:8]}: \"{w.summary[:40]}\" ({w.item_type.value})")
            if len(drafts) > 5:
                workitem_lines.append(f"  ... and {len(drafts) - 5} more")

        if actives:
            workitem_lines.append(f"ACTIVE ({len(actives)}):")
            for w in actives[:5]:  # Limit to 5
                jira_info = f" [{w.jira_key}]" if w.jira_key else ""
                workitem_lines.append(f"  - {w.id[:8]}: \"{w.summary[:40]}\" ({w.item_type.value}){jira_info}")
            if len(actives) > 5:
                workitem_lines.append(f"  ... and {len(actives) - 5} more")

        workitem_str = "\n".join(workitem_lines) if workitem_lines else "No work items"
    except Exception as e:
        workitem_str = f"Error: {e}"

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
    try:
        tracker = ChannelIssueTracker(conn)
        tracked = await tracker.get_tracked_issues(channel_id)

        if tracked:
            jira_lines = [f"Tracked ({len(tracked)}):"]
            for issue in tracked[:10]:  # Limit to 10
                status = issue.last_jira_status or "Unknown"
                jira_lines.append(f"  - {issue.issue_key}: {status}")
            if len(tracked) > 10:
                jira_lines.append(f"  ... and {len(tracked) - 10} more")
            jira_str = "\n".join(jira_lines)
        else:
            jira_str = "No issues tracked"
    except Exception as e:
        jira_str = f"Error: {e}"
        # Rollback to recover from failed query (prevents cascading failures)
        try:
            await conn.rollback()
        except Exception:
            pass

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*=== Jira Registry ===*"}
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"```{jira_str}```"}
    })

    # === Decisions ===
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT topic, decision_ts, synced_to_jira, created_at
                FROM channel_decisions
                WHERE channel_id = %s
                ORDER BY created_at DESC
                LIMIT 15
                """,
                (channel_id,),
            )
            decisions = await cur.fetchall()

        if decisions:
            decision_lines = [f"Decisions ({len(decisions)}):"]
            for d in decisions[:10]:
                topic = d[0][:40] if d[0] else "?"
                synced = "Y" if d[2] else "N"
                decision_lines.append(f"  {synced} {topic}")
            if len(decisions) > 10:
                decision_lines.append(f"  ... and {len(decisions) - 10} more")
            decision_str = "\n".join(decision_lines)
        else:
            decision_str = "No decisions recorded"
    except Exception as e:
        decision_str = f"Error: {e}"

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*=== Decisions ===*"}
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"```{decision_str}```"}
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

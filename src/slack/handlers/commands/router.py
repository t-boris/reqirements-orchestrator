"""Main command router: /maro, /jira, /help command routing.

Routes slash commands to appropriate handler modules.
This module is the main entry point and delegates to specific handlers.
"""

import logging

from slack_bolt import Ack
from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


# --- Slash Command Entry Points ---

def handle_help_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /help slash command - redirect to interactive /maro help."""
    from src.slack.handlers.commands.help import handle_help_command as _help

    ack()
    channel = command.get("channel_id")
    _run_async(_help(channel, client))


def handle_jira_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /jira slash command with subcommands.

    Subcommands:
    - /jira create [type] - Start new ticket session
    - /jira search <query> - Search existing tickets
    - /jira status - Show current session status
    """
    ack()  # Ack immediately

    channel = command.get("channel_id")
    user = command.get("user_id")
    text = command.get("text", "").strip()

    # Parse subcommand
    parts = text.split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""

    logger.info(
        "Jira command received",
        extra={
            "channel": channel,
            "user": user,
            "subcommand": subcommand,
            "command_args": args,
        }
    )

    if subcommand == "create":
        ticket_type = args.capitalize() if args else None
        say(
            text=f"Starting new ticket session{' for ' + ticket_type if ticket_type else ''}...",
            channel=channel,
        )
        # See .planning/ISSUES.md ISS-001

    elif subcommand == "search":
        if not args:
            say(text="Usage: /jira search <query>", channel=channel)
            return
        say(text=f"Searching for: {args}...", channel=channel)
        # See .planning/ISSUES.md ISS-002 (Completed Phase 7)

    elif subcommand == "status":
        say(text="No active session in this channel.", channel=channel)
        # See .planning/ISSUES.md ISS-003

    else:
        say(
            text="Available commands:\n* `/jira create [type]` - Start new ticket\n* `/jira search <query>` - Search tickets\n* `/jira status` - Session status",
            channel=channel,
        )


def handle_maro_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /maro slash command (sync wrapper).

    Routes to subcommands: enable, disable, status.
    Delegates to async implementation via _run_async().
    """
    ack()  # Ack immediately
    _run_async(_handle_maro_command_async(command, say, client))


async def _handle_maro_command_async(command: dict, say, client: WebClient):
    """Async implementation of /maro slash command.

    Routes to handler modules based on subcommand.

    Subcommands:
    - /maro enable - Enable listening in channel
    - /maro disable - Disable listening in channel
    - /maro status - Show current listening state
    - /maro help - Interactive help with examples
    - /maro track SCRUM-123 [SCRUM-124 ...] - Track issues in channel
    - /maro untrack SCRUM-123 - Remove issue from tracked list
    - /maro tracked - List all tracked issues for this channel
    - /maro board - Post/update pinned board with tracked issues
    - /maro board hide - Remove the pinned board
    - /maro sync - Show pending changes between Slack and Jira
    - /maro sync --auto - Apply obvious changes automatically
    - /maro mode - Show current channel mode
    - /maro mode project - Set mode to project (full work item types)
    - /maro mode feature --primary-epic PROJ-50 - Set mode focused on one epic
    - /maro mode bugs - Set mode to bugs/tasks only
    - /maro mode ops - Set mode to ops (incidents, runbooks)
    - /maro project SCRUM - Set default Jira project for this channel
    - /maro project - Show current default project
    - /maro debug - Show debug status
    - /maro debug on - Enable debug mode
    - /maro debug off - Disable debug mode
    - /maro debug status - Quick health check
    - /maro debug state - Full internal state dump
    - /maro explain - Explain MARO's last action/decision (OPS:EXPLAIN)
    - /maro decisions - List channel decisions with filters
    - /maro decision show <id> - Show decision details with linked tickets
    - /maro decision change <id> - Propose change to decision
    - /maro decision deprecate <id> - Mark decision as deprecated
    - /maro decision enrich <id> - Extract rich context for decision
    - /maro decision needs-context - List decisions needing enrichment
    """
    # Import handler modules
    from src.slack.handlers.commands.listening import (
        handle_enable_command,
        handle_disable_command,
        handle_status_command,
    )
    from src.slack.handlers.commands.tracking import (
        handle_track_command,
        handle_untrack_command,
        handle_tracked_command,
        handle_board_show_command,
        handle_board_hide_command,
    )
    from src.slack.handlers.commands.channel_config import (
        handle_mode_command,
        handle_project_command,
    )
    from src.slack.handlers.commands.debug import handle_debug_command
    from src.slack.handlers.commands.sync import handle_sync_command
    from src.slack.handlers.commands.decisions import (
        handle_decisions_command,
        handle_decision_subcommand,
    )
    from src.slack.handlers.commands.explain import handle_explain_command
    from src.slack.handlers.commands.help import handle_help_command

    channel = command.get("channel_id")
    team_id = command.get("team_id", "")
    user_id = command.get("user_id")
    text = command.get("text", "").strip()

    # Parse subcommand and args (keep original case for issue keys)
    parts = text.split()
    subcommand = parts[0].lower() if parts else ""
    args = parts[1:] if len(parts) > 1 else []

    logger.info(
        "MARO command received",
        extra={
            "channel": channel,
            "team_id": team_id,
            "user_id": user_id,
            "subcommand": subcommand,
            "command_args": args,
        }
    )

    # Route to appropriate handler
    if subcommand == "enable":
        await handle_enable_command(team_id, channel, user_id, say)
    elif subcommand == "disable":
        await handle_disable_command(team_id, channel, say)
    elif subcommand == "status":
        await handle_status_command(team_id, channel, say)
    elif subcommand == "help":
        await handle_help_command(channel, client)
    elif subcommand == "track":
        await handle_track_command(channel, user_id, args, client, say)
    elif subcommand == "untrack":
        await handle_untrack_command(channel, args, client, say)
    elif subcommand == "tracked":
        await handle_tracked_command(channel, say)
    elif subcommand == "board":
        # /maro board or /maro board hide
        board_action = args[0].lower() if args else "show"
        if board_action == "hide":
            await handle_board_hide_command(channel, client, say)
        else:
            await handle_board_show_command(channel, client, say)
    elif subcommand == "sync":
        # /maro sync or /maro sync --auto
        auto_mode = "--auto" in args or "-a" in args
        await handle_sync_command(channel, client, user_id, auto_mode)
    elif subcommand == "mode":
        await handle_mode_command(channel, user_id, args, say)
    elif subcommand == "project":
        await handle_project_command(channel, team_id, user_id, args, say)
    elif subcommand == "debug":
        # /maro debug [on|off|status|state]
        debug_action = args[0].lower() if args else "status"
        await handle_debug_command(channel, team_id, user_id, debug_action, client, say)
    elif subcommand == "explain":
        thread_ts = command.get("thread_ts")
        await handle_explain_command(channel, team_id, user_id, thread_ts, client, say)
    elif subcommand == "decisions":
        await handle_decisions_command(command, client)
    elif subcommand == "decision":
        await handle_decision_subcommand(command, args, client, say)
    else:
        # Default to help for empty or unknown
        await handle_help_command(channel, client)

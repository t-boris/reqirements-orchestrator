"""Slash command handlers: /maro, /persona, /jira, /help.

Handles all slash command interactions.
"""

import logging

from slack_bolt import Ack
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_help_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /help slash command - redirect to interactive /maro help."""
    ack()

    channel = command.get("channel_id")

    # Use the interactive help
    _run_async(_handle_maro_help(channel, client))


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


# --- MARO Slash Command Handlers ---

def handle_maro_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /maro slash command (sync wrapper).

    Routes to subcommands: enable, disable, status.
    Delegates to async implementation via _run_async().
    """
    ack()  # Ack immediately
    _run_async(_handle_maro_command_async(command, say, client))


async def _handle_maro_command_async(command: dict, say, client: WebClient):
    """Async implementation of /maro slash command.

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

    if subcommand == "enable":
        await _handle_maro_enable(team_id, channel, user_id, say)
    elif subcommand == "disable":
        await _handle_maro_disable(team_id, channel, say)
    elif subcommand == "status":
        await _handle_maro_status(team_id, channel, say)
    elif subcommand == "help":
        await _handle_maro_help(channel, client)
    elif subcommand == "track":
        await _handle_maro_track(channel, user_id, args, client, say)
    elif subcommand == "untrack":
        await _handle_maro_untrack(channel, args, client, say)
    elif subcommand == "tracked":
        await _handle_maro_tracked(channel, say)
    elif subcommand == "board":
        # /maro board or /maro board hide
        board_action = args[0].lower() if args else "show"
        if board_action == "hide":
            await _handle_maro_board_hide(channel, client, say)
        else:
            await _handle_maro_board_show(channel, client, say)
    elif subcommand == "sync":
        # /maro sync or /maro sync --auto
        auto_mode = "--auto" in args or "-a" in args
        await _handle_maro_sync(channel, client, user_id, auto_mode)
    elif subcommand == "mode":
        # /maro mode [project|feature|bugs|ops] [--primary-epic PROJ-50]
        await _handle_maro_mode(channel, user_id, args, say)
    elif subcommand == "project":
        # /maro project [PROJECT_KEY] - Set or show default Jira project
        await _handle_maro_project(channel, team_id, user_id, args, say)
    elif subcommand == "debug":
        # /maro debug [on|off|status|state]
        debug_action = args[0].lower() if args else "status"
        await _handle_maro_debug(channel, team_id, user_id, debug_action, client, say)
    elif subcommand == "explain":
        # /maro explain - Trigger OPS:EXPLAIN flow
        thread_ts = command.get("thread_ts")
        await _handle_maro_explain(channel, team_id, user_id, thread_ts, client, say)
    elif subcommand == "decisions":
        # /maro decisions - List channel decisions
        from src.slack.handlers.decision_commands import _handle_decisions_command_async
        await _handle_decisions_command_async(command, client)
    elif subcommand == "decision":
        # /maro decision show|change|deprecate <id>
        await _handle_decision_subcommand(command, args, client, say)
    else:
        # Default to help for empty or unknown
        await _handle_maro_help(channel, client)


async def _handle_maro_enable(
    team_id: str,
    channel_id: str,
    user_id: str,
    say,
):
    """Handle /maro enable - enable listening in channel."""
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            await store.create_tables()  # Ensure table exists
            state = await store.enable(team_id, channel_id, user_id)

        say(
            text="MARO is now listening in this channel to maintain context. "
                 "It won't reply unless mentioned or commanded.",
            channel=channel_id,
        )
        logger.info(
            "Listening enabled",
            extra={
                "team_id": team_id,
                "channel_id": channel_id,
                "enabled_by": user_id,
            }
        )
    except Exception as e:
        logger.error(f"Failed to enable listening: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't enable listening. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_disable(
    team_id: str,
    channel_id: str,
    say,
):
    """Handle /maro disable - disable listening in channel."""
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            state = await store.disable(team_id, channel_id)

        if state:
            say(
                text="MARO has stopped listening in this channel. "
                     "Conversation context will no longer be tracked.",
                channel=channel_id,
            )
        else:
            say(
                text="Listening was not enabled in this channel.",
                channel=channel_id,
            )
        logger.info(
            "Listening disabled",
            extra={"team_id": team_id, "channel_id": channel_id}
        )
    except Exception as e:
        logger.error(f"Failed to disable listening: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't disable listening. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_status(
    team_id: str,
    channel_id: str,
    say,
):
    """Handle /maro status - show current listening state."""
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            state = await store.get_state(team_id, channel_id)

        if not state:
            say(
                text="*MARO Listening Status:* Disabled\n\n"
                     "Use `/maro enable` to start listening in this channel.",
                channel=channel_id,
            )
        elif not state.enabled:
            say(
                text="*MARO Listening Status:* Disabled\n\n"
                     "Use `/maro enable` to start listening in this channel.",
                channel=channel_id,
            )
        else:
            # Build status message
            status_parts = ["*MARO Listening Status:* Enabled"]

            if state.enabled_at:
                enabled_time = state.enabled_at.strftime("%Y-%m-%d %H:%M UTC")
                status_parts.append(f"- Enabled at: {enabled_time}")

            if state.enabled_by:
                status_parts.append(f"- Enabled by: <@{state.enabled_by}>")

            if state.last_summary_at:
                summary_time = state.last_summary_at.strftime("%Y-%m-%d %H:%M UTC")
                status_parts.append(f"- Last summary at: {summary_time}")

            buffer_size = len(state.raw_buffer) if state.raw_buffer else 0
            status_parts.append(f"- Buffer size: {buffer_size} messages")

            say(
                text="\n".join(status_parts),
                channel=channel_id,
            )
    except Exception as e:
        logger.error(f"Failed to get listening status: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't retrieve the listening status. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_help(channel: str, client: WebClient):
    """Handle /maro help - show interactive help with example buttons."""
    from src.slack.onboarding import get_help_blocks

    try:
        blocks = get_help_blocks()

        client.chat_postMessage(
            channel=channel,
            text="What MARO can do",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Failed to show help: {e}", exc_info=True)
        # Fallback to simple text message
        try:
            client.chat_postMessage(
                channel=channel,
                text="MARO Help: Use `/maro enable` to enable listening, `/maro help` for full help.",
            )
        except Exception:
            logger.exception("Failed to post fallback help message")


# --- Jira Issue Tracking Commands (Phase 21) ---

# Regex pattern for Jira issue keys (e.g., SCRUM-123, PROJECT-1)
import re
ISSUE_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9]+-\d+$', re.IGNORECASE)


async def _handle_maro_track(
    channel_id: str,
    user_id: str,
    issue_keys: list[str],
    client: WebClient,
    say,
):
    """Handle /maro track SCRUM-123 [SCRUM-124 ...] - add issues to tracked list."""
    from src.db import get_connection
    from src.slack.channel_tracker import ChannelIssueTracker
    from src.slack.pinned_board import PinnedBoardManager
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    if not issue_keys:
        say(
            text="Usage: `/maro track SCRUM-123` or `/maro track SCRUM-123 SCRUM-124 SCRUM-125`",
            channel=channel_id,
        )
        return

    # Validate issue key format
    invalid_keys = [k for k in issue_keys if not ISSUE_KEY_PATTERN.match(k)]
    if invalid_keys:
        say(
            text=f"Invalid issue key format: {', '.join(invalid_keys)}. "
                 "Keys should be like SCRUM-123.",
            channel=channel_id,
        )
        return

    # Normalize to uppercase
    issue_keys = [k.upper() for k in issue_keys]

    # Validate keys exist in Jira
    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        tracked = []
        not_found = []
        already_tracked = []

        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            await tracker.create_tables()

            for issue_key in issue_keys:
                # Check if already tracked
                if await tracker.is_tracked(channel_id, issue_key):
                    already_tracked.append(issue_key)
                    continue

                # Validate exists in Jira
                try:
                    issue = await jira_service.get_issue(issue_key)
                    if issue:
                        # Track it
                        await tracker.track(channel_id, issue_key, user_id)
                        # Update sync status with current info
                        await tracker.update_sync_status(
                            channel_id,
                            issue_key,
                            status=issue.status,
                            summary=issue.summary,
                        )
                        tracked.append((issue_key, issue.summary, issue.status))
                    else:
                        not_found.append(issue_key)
                except Exception as e:
                    logger.warning(f"Could not verify {issue_key}: {e}")
                    not_found.append(issue_key)

        await jira_service.close()

        # Build response
        response_parts = []

        if tracked:
            lines = [f"Now tracking in this channel:"]
            for key, summary, status in tracked:
                lines.append(f"  <{jira_url}/browse/{key}|{key}>: {summary} ({status})")
            response_parts.append("\n".join(lines))

        if already_tracked:
            response_parts.append(
                f"Already tracked: {', '.join(already_tracked)}"
            )

        if not_found:
            response_parts.append(
                f"Not found in Jira: {', '.join(not_found)}"
            )

        say(text="\n\n".join(response_parts), channel=channel_id)

        # Refresh board if it exists (non-blocking)
        if tracked:
            try:
                async with get_connection() as conn:
                    manager = PinnedBoardManager(jira_base_url=jira_url)
                    await manager.refresh_if_exists(client, channel_id, conn)
            except Exception as e:
                # Non-blocking - log and continue
                logger.debug(f"Board refresh after track failed: {e}")

    except Exception as e:
        logger.error(f"Failed to track issues: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't track those issues. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_untrack(
    channel_id: str,
    issue_keys: list[str],
    client: WebClient,
    say,
):
    """Handle /maro untrack SCRUM-123 - remove issue from tracked list."""
    from src.db import get_connection
    from src.slack.channel_tracker import ChannelIssueTracker
    from src.slack.pinned_board import PinnedBoardManager
    from src.config.settings import get_settings

    if not issue_keys:
        say(
            text="Usage: `/maro untrack SCRUM-123`",
            channel=channel_id,
        )
        return

    # Just take the first key for untrack
    issue_key = issue_keys[0].upper()

    try:
        settings = get_settings()
        jira_url = settings.jira_url.rstrip("/")

        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            removed = await tracker.untrack(channel_id, issue_key)

        if removed:
            say(
                text=f"*{issue_key}* is no longer tracked in this channel.",
                channel=channel_id,
            )

            # Refresh board if it exists (non-blocking)
            try:
                async with get_connection() as conn:
                    manager = PinnedBoardManager(jira_base_url=jira_url)
                    await manager.refresh_if_exists(client, channel_id, conn)
            except Exception as e:
                # Non-blocking - log and continue
                logger.debug(f"Board refresh after untrack failed: {e}")
        else:
            say(
                text=f"*{issue_key}* is not tracked in this channel.",
                channel=channel_id,
            )

    except Exception as e:
        logger.error(f"Failed to untrack issue: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't untrack that issue. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_tracked(
    channel_id: str,
    say,
):
    """Handle /maro tracked - list all tracked issues for this channel."""
    from src.db import get_connection
    from src.slack.channel_tracker import ChannelIssueTracker
    from src.config.settings import get_settings

    try:
        settings = get_settings()
        jira_url = settings.jira_url.rstrip("/")

        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            issues = await tracker.get_tracked_issues(channel_id)

        if not issues:
            say(
                text="No Jira issues are tracked in this channel.\n\n"
                     "Use `/maro track SCRUM-123` to start tracking issues.",
                channel=channel_id,
            )
            return

        # Build response
        lines = [f"*Tracked Jira issues in this channel:*"]
        for issue in issues:
            summary = issue.last_jira_summary or "No summary"
            status = issue.last_jira_status or "Unknown"
            link = f"<{jira_url}/browse/{issue.issue_key}|{issue.issue_key}>"
            lines.append(f"  {link}: {summary} ({status})")

        say(text="\n".join(lines), channel=channel_id)

    except Exception as e:
        logger.error(f"Failed to list tracked issues: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't retrieve tracked issues. Please try again.",
            channel=channel_id,
        )


# --- Pinned Board Commands (Phase 21-02) ---

async def _handle_maro_board_show(
    channel_id: str,
    client: WebClient,
    say,
):
    """Handle /maro board - post or update the pinned board."""
    from src.db import get_connection
    from src.slack.channel_tracker import ChannelIssueTracker
    from src.slack.pinned_board import PinnedBoardManager
    from src.config.settings import get_settings

    try:
        settings = get_settings()
        jira_url = settings.jira_url.rstrip("/")

        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            issues = await tracker.get_tracked_issues(channel_id)

            if not issues:
                say(
                    text="No issues tracked. Use `/maro track SCRUM-123` first.",
                    channel=channel_id,
                )
                return

            manager = PinnedBoardManager(jira_base_url=jira_url)
            message_ts = await manager.post_or_update(client, channel_id, conn)

        if message_ts:
            say(
                text="Board updated in this channel.",
                channel=channel_id,
            )
        else:
            say(
                text="Sorry, I couldn't create the board. Please try again.",
                channel=channel_id,
            )

    except Exception as e:
        logger.error(f"Failed to show board: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't create the board. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_board_hide(
    channel_id: str,
    client: WebClient,
    say,
):
    """Handle /maro board hide - remove the pinned board."""
    from src.db import get_connection
    from src.slack.pinned_board import PinnedBoardManager
    from src.config.settings import get_settings

    try:
        settings = get_settings()
        jira_url = settings.jira_url.rstrip("/")

        async with get_connection() as conn:
            manager = PinnedBoardManager(jira_base_url=jira_url)
            removed = await manager.unpin(client, channel_id, conn)

        if removed:
            say(
                text="Board removed from this channel.",
                channel=channel_id,
            )
        else:
            say(
                text="No board found in this channel.",
                channel=channel_id,
            )

    except Exception as e:
        logger.error(f"Failed to hide board: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't remove the board. Please try again.",
            channel=channel_id,
        )


# --- Sync Commands (Phase 21-04) ---

async def _handle_maro_sync(
    channel_id: str,
    client: WebClient,
    user_id: str,
    auto_mode: bool = False,
):
    """Handle /maro sync command - show and apply Jira sync changes."""
    from src.slack.handlers.sync import handle_maro_sync

    await handle_maro_sync(channel_id, client, user_id, auto_mode)


# --- Mode Commands (Phase 23.2) ---

async def _handle_maro_mode(
    channel_id: str,
    user_id: str,
    args: list[str],
    say,
):
    """Handle /maro mode command - view or set channel mode.

    Usage:
    - /maro mode              - Show current mode
    - /maro mode project      - Full work item types
    - /maro mode feature --primary-epic PROJ-50 - Focus on one epic
    - /maro mode bugs         - Bug/task focused
    - /maro mode ops          - Incidents, runbooks
    """
    from src.db import get_connection
    from src.db.channel_mode_store import ChannelModeStore
    from src.db.models import ChannelMode

    # Parse arguments
    mode_arg = args[0].lower() if args else None
    primary_epic = None

    # Check for --primary-epic flag
    if "--primary-epic" in args or "-e" in args:
        try:
            flag_idx = args.index("--primary-epic") if "--primary-epic" in args else args.index("-e")
            if flag_idx + 1 < len(args):
                primary_epic = args[flag_idx + 1].upper()
        except (ValueError, IndexError):
            pass

    try:
        async with get_connection() as conn:
            store = ChannelModeStore(conn)
            await store.create_tables()

            # View current mode
            if not mode_arg:
                config = await store.get(channel_id)
                if not config:
                    say(
                        text="*Channel Mode:* project (default)\n\n"
                             "Use `/maro mode <mode>` to change. Available modes:\n"
                             "• `project` - Full work item types\n"
                             "• `feature --primary-epic PROJ-50` - Focus on one epic\n"
                             "• `bugs` - Bug/task focused\n"
                             "• `ops` - Incidents, runbooks",
                        channel=channel_id,
                    )
                else:
                    mode_desc = _get_mode_description(config.mode)
                    epic_info = f" (primary epic: {config.primary_epic})" if config.primary_epic else ""
                    set_info = f"\nSet by <@{config.set_by}>" if config.set_by else ""
                    say(
                        text=f"*Channel Mode:* {config.mode.value}{epic_info}\n"
                             f"{mode_desc}{set_info}",
                        channel=channel_id,
                    )
                return

            # Set mode
            valid_modes = {m.value: m for m in ChannelMode}
            if mode_arg not in valid_modes:
                say(
                    text=f"Unknown mode: `{mode_arg}`\n\n"
                         f"Available modes: {', '.join(valid_modes.keys())}",
                    channel=channel_id,
                )
                return

            mode = valid_modes[mode_arg]

            # Validate primary_epic for feature mode
            if mode == ChannelMode.FEATURE and not primary_epic:
                say(
                    text="Feature mode requires a primary epic.\n"
                         "Usage: `/maro mode feature --primary-epic PROJ-50`",
                    channel=channel_id,
                )
                return

            # Clear primary_epic if not feature mode
            if mode != ChannelMode.FEATURE:
                primary_epic = None

            # Set the mode
            config = await store.set_mode(channel_id, mode, user_id, primary_epic=primary_epic)

            mode_desc = _get_mode_description(mode)
            epic_info = f" with primary epic {primary_epic}" if primary_epic else ""
            say(
                text=f"Channel mode set to *{mode.value}*{epic_info}\n\n{mode_desc}",
                channel=channel_id,
            )

            logger.info(
                "Channel mode set",
                extra={
                    "channel_id": channel_id,
                    "mode": mode.value,
                    "primary_epic": primary_epic,
                    "set_by": user_id,
                }
            )

    except Exception as e:
        logger.error(f"Failed to handle mode command: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't process the mode command. Please try again.",
            channel=channel_id,
        )


def _get_mode_description(mode: "ChannelMode") -> str:
    """Get human-readable description for a channel mode."""
    from src.db.models import ChannelMode

    descriptions = {
        ChannelMode.PROJECT: "Full work item types enabled. All MARO features available.",
        ChannelMode.FEATURE: "Focused on primary epic. Stories and tasks preferred.",
        ChannelMode.BUGS: "Bug and task focused. Epic creation suppressed.",
        ChannelMode.OPS: "Incidents and runbooks. Stricter Jira writes.",
    }
    return descriptions.get(mode, "")


async def _handle_maro_project(
    channel_id: str,
    team_id: str,
    user_id: str,
    args: list[str],
    say,
) -> None:
    """Handle /maro project command.

    Usage:
    - /maro project           - Show current default project
    - /maro project SCRUM     - Set default Jira project to SCRUM
    - /maro project --clear   - Clear default project (use global)
    """
    from src.db import get_connection
    from src.db.channel_context_store import ChannelContextStore
    from src.db.models import ChannelConfig

    project_arg = args[0].upper() if args else None

    try:
        async with get_connection() as conn:
            store = ChannelContextStore(conn)
            await store.create_tables()

            ctx = await store.get_or_create(team_id, channel_id)

            # View current project
            if not project_arg:
                current = ctx.config.default_jira_project
                if current:
                    say(
                        text=f"*Default Jira Project:* `{current}`\n\n"
                             f"Tickets created in this channel will use this project.\n"
                             f"Use `/maro project <KEY>` to change.",
                        channel=channel_id,
                    )
                else:
                    from src.config.settings import get_settings
                    settings = get_settings()
                    global_proj = settings.jira_default_project
                    if global_proj:
                        say(
                            text=f"*Default Jira Project:* Not set for this channel\n\n"
                                 f"Using global default: `{global_proj}`\n"
                                 f"Use `/maro project <KEY>` to set a channel-specific project.",
                            channel=channel_id,
                        )
                    else:
                        say(
                            text="*Default Jira Project:* Not set\n\n"
                                 "Use `/maro project <KEY>` to set a default project for this channel.",
                            channel=channel_id,
                        )
                return

            # Clear project
            if project_arg == "--CLEAR":
                new_config = ChannelConfig(
                    default_jira_project=None,
                    secondary_projects=ctx.config.secondary_projects,
                    trigger_rule=ctx.config.trigger_rule,
                    epic_binding_behavior=ctx.config.epic_binding_behavior,
                    config_permissions=ctx.config.config_permissions,
                )
                await store.update_config(team_id, channel_id, new_config)
                say(
                    text="Default Jira project cleared for this channel.",
                    channel=channel_id,
                )
                return

            # Validate project key format
            if not project_arg.isalpha() or len(project_arg) < 2:
                say(
                    text=f"Invalid project key: `{project_arg}`\n\n"
                         f"Project keys should be uppercase letters (e.g., SCRUM, PROJ).",
                    channel=channel_id,
                )
                return

            # Set project
            new_config = ChannelConfig(
                default_jira_project=project_arg,
                secondary_projects=ctx.config.secondary_projects,
                trigger_rule=ctx.config.trigger_rule,
                epic_binding_behavior=ctx.config.epic_binding_behavior,
                config_permissions=ctx.config.config_permissions,
            )
            await store.update_config(team_id, channel_id, new_config)

            say(
                text=f"Default Jira project set to `{project_arg}` for this channel.\n\n"
                     f"All tickets created here will use this project.",
                channel=channel_id,
            )

            logger.info(
                "Channel default project set",
                extra={
                    "channel_id": channel_id,
                    "project": project_arg,
                    "set_by": user_id,
                }
            )

    except Exception as e:
        logger.error(f"Failed to handle project command: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't process the project command. Please try again.",
            channel=channel_id,
        )


# --- Debug Commands (Phase 24) ---

async def _handle_maro_debug(
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
    from datetime import datetime, timezone

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
                synced = "✓" if d[2] else "○"
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
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"Generated at {now}"}
        ]
    })

    return blocks


# --- OPS Commands (Phase 25.2) ---

async def _handle_maro_explain(
    channel_id: str,
    team_id: str,
    user_id: str,
    thread_ts: str | None,
    client: WebClient,
    say,
):
    """Handle /maro explain - show explanation of last decisions.

    Gets current session state and formats an explanation of:
    - Last intent classification
    - Current draft status
    - Recent decision actions

    If no thread_ts, finds most recent active session in the channel.
    """
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner, _runners

    # Find session - either from thread or most recent in channel
    identity = None

    if thread_ts:
        # Direct thread context
        identity = SessionIdentity(
            team_id=team_id or "default",
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        if identity.session_id not in _runners:
            identity = None

    # If no thread or session not found, look for any active session in this channel
    if identity is None:
        for session_id, runner in _runners.items():
            if runner.identity.channel_id == channel_id:
                identity = runner.identity
                break

    if identity is None:
        say(
            text="No active MARO sessions in this channel. Start a conversation by mentioning @MARO.",
            channel=channel_id,
        )
        return

    try:

        # Get runner and current state
        runner = get_runner(identity)
        state = await runner._get_current_state()

        # Build explanation
        parts = [":brain: *MARO Explain*\n"]

        # Intent info
        intent_result = state.get("intent_result", {})
        if intent_result:
            intent = intent_result.get("intent", "unknown")
            confidence = intent_result.get("confidence", 0)
            reasons = intent_result.get("reasons", [])
            parts.append(f"*Last Intent:* `{intent}` ({confidence:.0%} confidence)")
            if reasons:
                parts.append(f"_Reason: {reasons[0][:100]}_")

        # Draft info
        draft = state.get("draft")
        if draft:
            draft_title = draft.get("title", "Untitled") if isinstance(draft, dict) else getattr(draft, "title", "Untitled")
            draft_type = draft.get("issue_type", "Story") if isinstance(draft, dict) else getattr(draft, "issue_type", "Story")
            parts.append(f"\n*Current Draft:* {draft_type} - \"{draft_title[:50]}\"")

        # Decision info
        decision_result = state.get("decision_result", {})
        if decision_result:
            action = decision_result.get("action", "unknown")
            reason = decision_result.get("reason", "")
            parts.append(f"\n*Last Decision:* `{action}`")
            if reason:
                parts.append(f"_Reason: {reason[:100]}_")

        # Phase info
        phase = state.get("phase", "unknown")
        parts.append(f"\n*Phase:* `{phase}`")

        explanation = "\n".join(parts)

        # Post to the channel where command was run (with link to session thread)
        thread_link = f"<https://slack.com/archives/{identity.channel_id}/p{identity.thread_ts.replace('.', '')}|View thread>"
        explanation_with_link = explanation + f"\n\n{thread_link}"

        client.chat_postMessage(
            channel=channel_id,  # Post to command channel, not session channel
            text=explanation_with_link,
        )

        logger.info(
            "OPS:EXPLAIN completed",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "session_thread_ts": identity.thread_ts,
            }
        )

    except Exception as e:
        logger.error(f"Failed to run OPS:EXPLAIN: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't explain my decisions right now. Please try again.",
            channel=channel_id,
        )


# --- Decision Commands (Phase 30) ---

async def _handle_decision_subcommand(
    command: dict,
    args: list[str],
    client: WebClient,
    say,
):
    """Handle /maro decision <subcommand> commands.

    Subcommands:
    - show <id> - Show decision details
    - change <id> - Open change modal
    - deprecate <id> - Open deprecation modal
    """
    from src.slack.handlers.decision_commands import (
        _handle_decision_show_async,
        _handle_decision_change_async,
        _handle_decision_deprecate_async,
    )

    channel_id = command.get("channel_id")

    if not args:
        say(
            text="Usage:\n"
                 "- `/maro decision show <id>` - Show decision details\n"
                 "- `/maro decision change <id>` - Propose a change\n"
                 "- `/maro decision deprecate <id>` - Deprecate decision\n"
                 "- `/maro decision enrich <id>` - Extract rich context\n"
                 "- `/maro decision needs-context` - List decisions needing context",
            channel=channel_id,
        )
        return

    subcommand = args[0].lower()
    # Rebuild text with remaining args for the handlers
    command["text"] = " ".join(args)

    if subcommand == "show":
        await _handle_decision_show_async(command, client)
    elif subcommand == "change":
        await _handle_decision_change_async(command, client)
    elif subcommand == "deprecate":
        await _handle_decision_deprecate_async(command, client)
    elif subcommand == "enrich":
        if len(args) < 2:
            say(
                text="Usage: `/maro decision enrich <id>` - Enrich decision with context",
                channel=channel_id,
            )
            return
        await _handle_decision_enrich(
            channel_id=channel_id,
            user_id=command.get("user_id"),
            decision_id=args[1],
            client=client,
        )
    else:
        say(
            text=f"Unknown decision subcommand: `{subcommand}`\n\n"
                 "Available: show, change, deprecate, enrich",
            channel=channel_id,
        )


async def _handle_decision_enrich(
    channel_id: str,
    user_id: str,
    decision_id: str,
    client: WebClient,
) -> None:
    """Handle /maro decision enrich DEC-xxx command.

    Extracts rich context from decision's discussion thread
    and updates the decision.

    Args:
        channel_id: Slack channel ID
        user_id: User who invoked command
        decision_id: Decision ID (short or full UUID)
        client: Slack client
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.graph.nodes.decision_extraction import extract_rich_context

    # Normalize decision ID (handle DEC-xxx format)
    if decision_id.upper().startswith("DEC-"):
        decision_id = decision_id[4:]

    async with get_connection() as conn:
        store = DecisionStore(conn)

        # Get decision
        decision = await store.get(decision_id)
        if not decision:
            # Try prefix match
            decisions = await store.list_by_channel(channel_id, limit=100)
            matches = [d for d in decisions if d.id.startswith(decision_id)]
            if len(matches) == 1:
                decision = matches[0]
            elif len(matches) > 1:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Multiple decisions match `{decision_id}`. Please be more specific.",
                )
                return
            else:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Decision `{decision_id}` not found.",
                )
                return

        # Check if already has rich context
        if decision.has_rich_context():
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Decision DEC-{decision.id[:8]} already has rich context. Use `/maro decision show` to view.",
            )
            return

        # Get conversation from discussion thread
        conversation = ""
        if decision.discussion_thread_ts:
            try:
                result = client.conversations_replies(
                    channel=channel_id,
                    ts=decision.discussion_thread_ts,
                    limit=20,
                )
                messages = result.get("messages", [])
                conversation = "\n\n---\n\n".join(
                    m.get("text", "") for m in messages if m.get("text")
                )
            except Exception as e:
                logger.warning(f"Failed to fetch discussion thread: {e}")

        # If no thread, use description as context
        if not conversation:
            conversation = decision.description

        # Post progress message
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Extracting rich context for DEC-{decision.id[:8]}...",
        )

        # Extract rich context
        rich_context = await extract_rich_context(
            title=decision.title,
            description=decision.description,
            conversation_context=conversation,
        )

        # Update decision
        if any(rich_context.values()):
            await store.update_rich_context(
                decision_id=decision.id,
                rationale=rich_context.get("rationale"),
                context_before=rich_context.get("context_before"),
                alternatives=rich_context.get("alternatives"),
                consequences=rich_context.get("consequences"),
                updated_by=user_id,
            )

            # Build summary of what was extracted
            extracted = []
            if rich_context.get("rationale"):
                extracted.append(f"{len(rich_context['rationale'])} rationale points")
            if rich_context.get("context_before"):
                extracted.append("context")
            if rich_context.get("alternatives"):
                extracted.append(f"{len(rich_context['alternatives'])} alternatives")
            if rich_context.get("consequences"):
                extracted.append(f"{len(rich_context['consequences'])} consequences")

            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Enriched DEC-{decision.id[:8]} with: {', '.join(extracted)}.\nUse `/maro decision show {decision.id[:8]}` to view.",
            )
        else:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Could not extract rich context for DEC-{decision.id[:8]}. Try adding more context to the discussion thread.",
            )

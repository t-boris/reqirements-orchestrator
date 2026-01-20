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
            "args": args,
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


def handle_persona_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /persona slash command (sync wrapper).

    Delegates to async implementation via _run_async().
    """
    ack()  # Ack immediately
    _run_async(_handle_persona_command_async(command, say, client))


async def _handle_persona_command_async(command: dict, say, client: WebClient):
    """Async implementation of /persona slash command.

    Commands:
    - /persona [name] - Switch to persona (pm, security, architect)
    - /persona lock - Lock current persona for thread
    - /persona unlock - Allow persona switching again
    - /persona status - Show current persona and validators
    - /persona list - Show available personas
    """
    channel = command.get("channel_id")
    thread_ts = command.get("thread_ts") or command.get("ts", "")
    user = command.get("user_id")
    text = command.get("text", "").strip()

    logger.info(
        "Persona command received",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
            "command_text": text,
        }
    )

    # Get session state if we have a thread
    from src.personas.commands import handle_persona_command as exec_persona_cmd

    # Build minimal state if no session exists
    state = {
        "persona": "pm",
        "persona_lock": False,
        "persona_reason": "default",
    }

    # Try to get actual session state
    if thread_ts:
        try:
            identity = SessionIdentity(
                team_id=command.get("team_id", "default"),
                channel_id=channel,
                thread_ts=thread_ts,
            )
            # Check if runner exists for this session
            from src.graph.runner import _runners
            if identity.session_id in _runners:
                runner = get_runner(identity)
                current_state = await runner._get_current_state()
                state = {
                    "persona": current_state.get("persona", "pm"),
                    "persona_lock": current_state.get("persona_lock", False),
                    "persona_reason": current_state.get("persona_reason", "default"),
                    "persona_confidence": current_state.get("persona_confidence"),
                }
        except Exception as e:
            logger.warning(f"Could not get session state: {e}")

    # Execute command
    result = exec_persona_cmd(text, state)

    # Send response
    response_kwargs = {
        "channel": channel,
        "text": result.message,
    }
    if thread_ts:
        response_kwargs["thread_ts"] = thread_ts

    client.chat_postMessage(**response_kwargs)

    # Update session if state changed and we have a runner
    if result.state_update and thread_ts:
        try:
            identity = SessionIdentity(
                team_id=command.get("team_id", "default"),
                channel_id=channel,
                thread_ts=thread_ts,
            )
            from src.graph.runner import _runners
            if identity.session_id in _runners:
                runner = get_runner(identity)
                current_state = await runner._get_current_state()
                new_state = {**current_state, **result.state_update}
                await runner._update_state(new_state)
                logger.info(
                    "Persona state updated",
                    extra={
                        "session_id": identity.session_id,
                        "state_update": result.state_update,
                    }
                )
        except Exception as e:
            logger.warning(f"Could not update session state: {e}")


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
            "args": args,
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

    blocks = get_help_blocks()

    client.chat_postMessage(
        channel=channel,
        text="What MARO can do",
        blocks=blocks,
    )


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

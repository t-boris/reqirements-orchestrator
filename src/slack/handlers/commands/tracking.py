"""Jira issue tracking command handlers: track, untrack, tracked, board.

Handles Jira issue tracking and pinned board commands.
"""

import logging
import re

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)

# Regex pattern for Jira issue keys (e.g., SCRUM-123, PROJECT-1)
ISSUE_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9]+-\d+$', re.IGNORECASE)


async def handle_track_command(
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


async def handle_untrack_command(
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


async def handle_tracked_command(
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


async def handle_board_show_command(
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


async def handle_board_hide_command(
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

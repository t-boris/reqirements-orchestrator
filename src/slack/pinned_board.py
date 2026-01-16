"""Pinned board manager for tracked Jira issues in channels.

Manages a pinned message dashboard showing all tracked Jira issues
with current status, organized by status category.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.channel_tracker import TrackedIssue

logger = logging.getLogger(__name__)

# Rate limit: max 1 refresh per 30 seconds per channel
REFRESH_RATE_LIMIT_SECONDS = 30


def _format_timestamp(dt: datetime) -> str:
    """Format datetime as 'Jan 16, 2026 at 3:45 PM'."""
    return dt.strftime("%b %d, %Y at %-I:%M %p")


def _categorize_status(status: str) -> str:
    """Categorize Jira status into bucket.

    Returns one of: 'open', 'in_progress', 'done'
    """
    status_lower = status.lower() if status else ""

    # Done statuses
    if status_lower in ("done", "closed", "resolved", "complete", "completed"):
        return "done"

    # In progress statuses
    if status_lower in ("in progress", "in development", "in review", "review",
                        "testing", "in testing", "qa", "in qa", "blocked"):
        return "in_progress"

    # Default to open (backlog, to do, open, new, etc.)
    return "open"


class PinnedBoardManager:
    """Manages the pinned Jira board message per channel.

    Displays tracked issues organized by status with links and assignees.
    Stores board message_ts in database for updates.

    Usage:
        manager = PinnedBoardManager()
        message_ts = await manager.post_or_update(client, channel_id, conn)
        await manager.unpin(client, channel_id, conn)
    """

    def __init__(self, jira_base_url: str = ""):
        """Initialize board manager.

        Args:
            jira_base_url: Base URL for Jira links (e.g., "https://company.atlassian.net")
        """
        self._jira_base_url = jira_base_url.rstrip("/")

    def build_board_blocks(
        self,
        channel_name: str,
        issues: list[TrackedIssue],
    ) -> list[dict]:
        """Build Slack blocks showing tracked issues by status.

        Args:
            channel_name: Channel name for display (without #)
            issues: List of tracked issues with current Jira data

        Returns:
            List of Slack blocks for the board message.
        """
        now = datetime.now(timezone.utc)

        # Categorize issues by status
        open_issues: list[TrackedIssue] = []
        in_progress_issues: list[TrackedIssue] = []
        done_issues: list[TrackedIssue] = []

        for issue in issues:
            category = _categorize_status(issue.last_jira_status or "")
            if category == "done":
                done_issues.append(issue)
            elif category == "in_progress":
                in_progress_issues.append(issue)
            else:
                open_issues.append(issue)

        blocks = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Jira Issues Tracked in #{channel_name}",
                "emoji": True,
            }
        })

        # Updated timestamp
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Updated: {_format_timestamp(now)}",
                }
            ]
        })

        # If no issues at all
        if not issues:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No issues tracked yet._\n\nUse `/maro track SCRUM-123` to start tracking issues.",
                }
            })
            return blocks

        # Open section
        if open_issues:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Open ({len(open_issues)})*",
                }
            })
            for issue in open_issues:
                blocks.append(self._issue_block(issue))

        # In Progress section
        if in_progress_issues:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*In Progress ({len(in_progress_issues)})*",
                }
            })
            for issue in in_progress_issues:
                blocks.append(self._issue_block(issue))

        # Done section
        if done_issues:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Done ({len(done_issues)})*",
                }
            })
            for issue in done_issues:
                blocks.append(self._issue_block(issue, done=True))

        # Footer with refresh info
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Use `/maro board` to refresh  |  `/maro board hide` to remove",
                }
            ]
        })

        return blocks

    def _issue_block(self, issue: TrackedIssue, done: bool = False) -> dict:
        """Build a single issue line block.

        Args:
            issue: The tracked issue
            done: Whether this is in the done section (adds checkmark)

        Returns:
            Slack section block for the issue.
        """
        # Build issue link
        if self._jira_base_url:
            link = f"<{self._jira_base_url}/browse/{issue.issue_key}|{issue.issue_key}>"
        else:
            link = f"*{issue.issue_key}*"

        # Build summary
        summary = issue.last_jira_summary or "No summary"
        if len(summary) > 60:
            summary = summary[:57] + "..."

        # Build line
        if done:
            text = f"• {link}: {summary} :white_check_mark:"
        else:
            status = issue.last_jira_status or "Unknown"
            text = f"• {link}: {summary} _({status})_"

        return {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text,
            }
        }

    async def post_or_update(
        self,
        client: WebClient,
        channel_id: str,
        conn,
    ) -> Optional[str]:
        """Post a new board or update existing one.

        Args:
            client: Slack WebClient
            channel_id: Channel to post in
            conn: Database connection for tracker and board state

        Returns:
            Message timestamp of the board, or None if no issues tracked.
        """
        from src.slack.channel_tracker import ChannelIssueTracker
        from src.db.board_store import BoardStore

        tracker = ChannelIssueTracker(conn)
        board_store = BoardStore(conn)
        await board_store.create_tables()

        # Get tracked issues
        issues = await tracker.get_tracked_issues(channel_id)

        # Get channel name for display
        try:
            info = client.conversations_info(channel=channel_id)
            channel_name = info.get("channel", {}).get("name", channel_id)
        except Exception:
            channel_name = channel_id

        # Build blocks
        blocks = self.build_board_blocks(channel_name, issues)

        # Get existing board state
        board_state = await board_store.get_board(channel_id)

        if board_state and board_state.message_ts:
            # Update existing message
            try:
                client.chat_update(
                    channel=channel_id,
                    ts=board_state.message_ts,
                    text=f"Jira Issues Tracked in #{channel_name}",
                    blocks=blocks,
                )

                # Update last refresh time
                await board_store.update_refresh_time(channel_id)

                logger.info(
                    "Board message updated",
                    extra={
                        "channel_id": channel_id,
                        "message_ts": board_state.message_ts,
                        "issue_count": len(issues),
                    }
                )

                return board_state.message_ts

            except Exception as e:
                # Message may have been deleted, post new one
                logger.warning(
                    f"Could not update board message, posting new: {e}",
                    extra={"channel_id": channel_id}
                )

        # Post new message
        try:
            result = client.chat_postMessage(
                channel=channel_id,
                text=f"Jira Issues Tracked in #{channel_name}",
                blocks=blocks,
            )

            message_ts = result.get("ts")

            if message_ts:
                # Pin the message
                try:
                    client.pins_add(
                        channel=channel_id,
                        timestamp=message_ts,
                    )
                    logger.info(
                        "Board message pinned",
                        extra={"channel_id": channel_id, "message_ts": message_ts}
                    )
                except Exception as e:
                    # May fail if bot lacks pin permission - non-blocking
                    logger.warning(
                        f"Could not pin board message: {e}",
                        extra={"channel_id": channel_id}
                    )

                # Store board state
                await board_store.set_board(channel_id, message_ts)

                logger.info(
                    "Board message posted",
                    extra={
                        "channel_id": channel_id,
                        "message_ts": message_ts,
                        "issue_count": len(issues),
                    }
                )

            return message_ts

        except Exception as e:
            logger.error(
                f"Failed to post board message: {e}",
                extra={"channel_id": channel_id},
                exc_info=True,
            )
            return None

    async def unpin(
        self,
        client: WebClient,
        channel_id: str,
        conn,
    ) -> bool:
        """Unpin and delete the board message.

        Args:
            client: Slack WebClient
            channel_id: Channel containing the board
            conn: Database connection for board state

        Returns:
            True if board was removed, False if no board existed.
        """
        from src.db.board_store import BoardStore

        board_store = BoardStore(conn)
        board_state = await board_store.get_board(channel_id)

        if not board_state or not board_state.message_ts:
            return False

        message_ts = board_state.message_ts

        # Unpin the message
        try:
            client.pins_remove(
                channel=channel_id,
                timestamp=message_ts,
            )
        except Exception as e:
            logger.warning(
                f"Could not unpin board message: {e}",
                extra={"channel_id": channel_id}
            )

        # Delete the message
        try:
            client.chat_delete(
                channel=channel_id,
                ts=message_ts,
            )
        except Exception as e:
            logger.warning(
                f"Could not delete board message: {e}",
                extra={"channel_id": channel_id}
            )

        # Remove from database
        await board_store.remove_board(channel_id)

        logger.info(
            "Board message removed",
            extra={"channel_id": channel_id, "message_ts": message_ts}
        )

        return True

    async def refresh_if_exists(
        self,
        client: WebClient,
        channel_id: str,
        conn,
    ) -> bool:
        """Refresh board only if it exists for the channel.

        Rate-limited to max 1 refresh per 30 seconds per channel.

        Args:
            client: Slack WebClient
            channel_id: Channel to potentially refresh
            conn: Database connection

        Returns:
            True if board was refreshed, False if no board or rate limited.
        """
        from src.db.board_store import BoardStore

        board_store = BoardStore(conn)
        board_state = await board_store.get_board(channel_id)

        if not board_state or not board_state.message_ts:
            return False

        # Check rate limit
        now = datetime.now(timezone.utc)
        if board_state.last_refresh_at:
            elapsed = (now - board_state.last_refresh_at).total_seconds()
            if elapsed < REFRESH_RATE_LIMIT_SECONDS:
                logger.debug(
                    "Board refresh rate limited",
                    extra={
                        "channel_id": channel_id,
                        "elapsed_seconds": elapsed,
                        "limit_seconds": REFRESH_RATE_LIMIT_SECONDS,
                    }
                )
                return False

        # Do the refresh
        await self.post_or_update(client, channel_id, conn)
        return True

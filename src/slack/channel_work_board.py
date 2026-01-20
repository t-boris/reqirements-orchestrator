"""Channel Work Board manager for commit log and work items (Phase 23.3).

Displays a pinned message showing channel mode, recent commits (git-log style),
and active work items. Auto-updates on new commits.

Format:
Channel Work Board

Mode: project (set by @boris)

Recent Commits:
14:32 Decision: Use background worker [thread]
14:15 STORY draft created: Retry mechanism [thread]
13:50 EPIC PROJ-50 updated: Added auth requirements [thread]

Active Work Items:
- EPIC PROJ-50 Email System (active, Jira: PROJ-50)
- STORY (draft) Retry mechanism
- BUG PROJ-311 Duplicate emails (triage, Jira: PROJ-311)
"""
import logging
from datetime import datetime, timezone

from slack_sdk.web.async_client import AsyncWebClient
from psycopg import AsyncConnection

from src.db.models import CommitEntry, ChannelMode, ChannelModeConfig, WorkItem, WorkItemStatus
from src.db.commit_store import CommitStore
from src.db.channel_mode_store import ChannelModeStore
from src.db.workitem_store import WorkItemStore

logger = logging.getLogger(__name__)

# Board stores message_ts per channel - will be persisted later
_board_message_cache: dict[str, str] = {}


class ChannelWorkBoardManager:
    """Manages the Channel Work Board pinned message.

    Usage:
        manager = ChannelWorkBoardManager()
        await manager.post_or_update(client, channel_id, conn)
    """

    def __init__(self) -> None:
        """Initialize the board manager."""
        pass

    async def build_board_blocks(
        self,
        channel_id: str,
        conn: AsyncConnection,
    ) -> list[dict]:
        """Build Slack blocks for the Channel Work Board.

        Args:
            channel_id: Channel to build board for
            conn: Database connection

        Returns:
            List of Slack blocks for the board message
        """
        # Load data from stores
        mode_store = ChannelModeStore(conn)
        commit_store = CommitStore(conn)
        workitem_store = WorkItemStore(conn)

        # Ensure tables exist
        await mode_store.create_tables()
        await commit_store.create_tables()
        await workitem_store.create_tables()

        # Get channel mode
        mode_config = await mode_store.get(channel_id)

        # Get recent commits
        commits = await commit_store.list_recent(channel_id, limit=5)

        # Get active work items
        work_items = await workitem_store.list_by_channel(
            channel_id,
            status=[WorkItemStatus.DRAFT, WorkItemStatus.ACTIVE],
        )

        return self._build_blocks(mode_config, commits, work_items)

    def _build_blocks(
        self,
        mode_config: ChannelModeConfig | None,
        commits: list[CommitEntry],
        work_items: list[WorkItem],
    ) -> list[dict]:
        """Build the board blocks from data."""
        blocks = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Channel Work Board",
                "emoji": True,
            }
        })

        # Mode section
        if mode_config:
            mode_text = f"*Mode:* {mode_config.mode.value}"
            if mode_config.primary_epic:
                mode_text += f" (primary epic: {mode_config.primary_epic})"
            mode_text += f" _(set by <@{mode_config.set_by}>)_"
        else:
            mode_text = "*Mode:* project _(default)_"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": mode_text}
        })

        blocks.append({"type": "divider"})

        # Recent commits section
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Recent Commits:*"}
        })

        if commits:
            commit_lines = []
            for commit in commits[:5]:
                line = self._format_commit_line(commit)
                commit_lines.append(line)

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(commit_lines)}
            })
        else:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_No commits yet_"}]
            })

        blocks.append({"type": "divider"})

        # Active work items section
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Active Work Items:*"}
        })

        if work_items:
            item_lines = []
            for item in work_items[:10]:
                line = self._format_workitem_line(item)
                item_lines.append(line)

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(item_lines)}
            })
        else:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_No active work items_"}]
            })

        # Footer with last updated
        now = datetime.now(timezone.utc)
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_Last updated: {now.strftime('%H:%M')} UTC_"
            }]
        })

        return blocks

    def _format_commit_line(self, commit: CommitEntry) -> str:
        """Format a commit entry as a single line.

        Format: "14:32 Decision: Use background worker [thread]"
        """
        time_str = commit.committed_at.strftime("%H:%M")
        type_display = self._format_commit_type(commit.commit_type.value)

        line = f"`{time_str}` *{type_display}:* {commit.summary}"

        # Add thread link if available
        if commit.thread_ts and commit.channel_id:
            link = f"https://slack.com/archives/{commit.channel_id}/p{commit.thread_ts.replace('.', '')}"
            line += f" <{link}|[thread]>"

        return line

    def _format_commit_type(self, commit_type: str) -> str:
        """Format commit type for display."""
        type_map = {
            "decision": "Decision",
            "workitem_created": "Created",
            "workitem_updated": "Updated",
            "constraint_added": "Constraint",
            "jira_synced": "Jira Sync",
        }
        return type_map.get(commit_type, commit_type.title())

    def _format_workitem_line(self, item: WorkItem) -> str:
        """Format a work item as a single line.

        Format: "- EPIC PROJ-50 Email System (active, Jira: PROJ-50)"
        """
        type_upper = item.item_type.value.upper()
        status_str = item.status.value

        line = f"• *{type_upper}*"

        if item.jira_key:
            line += f" {item.jira_key}"
        elif status_str == "draft":
            line += " (draft)"

        line += f" {item.summary}"

        if item.jira_key:
            line += f" _({status_str})_"

        return line

    async def post_or_update(
        self,
        client: AsyncWebClient,
        channel_id: str,
        conn: AsyncConnection,
    ) -> str | None:
        """Post new board or update existing one.

        Args:
            client: Slack async client
            channel_id: Channel to post to
            conn: Database connection

        Returns:
            Message timestamp of the board, or None on failure
        """
        try:
            blocks = await self.build_board_blocks(channel_id, conn)

            # Check for existing board message
            existing_ts = _board_message_cache.get(channel_id)

            if existing_ts:
                # Update existing
                try:
                    response = await client.chat_update(
                        channel=channel_id,
                        ts=existing_ts,
                        blocks=blocks,
                        text="Channel Work Board",
                    )
                    return response.get("ts")
                except Exception as e:
                    logger.warning(f"Failed to update board, will post new: {e}")
                    # Fall through to post new

            # Post new board
            response = await client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text="Channel Work Board",
            )

            message_ts = response.get("ts")
            if message_ts:
                _board_message_cache[channel_id] = message_ts

                # Pin the board
                try:
                    await client.pins_add(channel=channel_id, timestamp=message_ts)
                except Exception as e:
                    logger.warning(f"Failed to pin board: {e}")

            return message_ts

        except Exception as e:
            logger.error(f"Failed to post/update board: {e}", exc_info=True)
            return None

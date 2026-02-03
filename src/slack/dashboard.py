"""Channel status dashboard manager.

Ref: Spec Part 9.3 - Status Dashboard (Pinned Message)
"""
import logging
from dataclasses import dataclass
from typing import Any

from src.domain.types import ChannelId
from src.slack.client import SlackClient
from src.slack.blocks.builders import build_dashboard_blocks

logger = logging.getLogger(__name__)


@dataclass
class ChannelDashboard:
    """Pinned status dashboard for channel."""
    channel_id: ChannelId
    message_ts: str


class DashboardManager:
    """Manages channel status dashboard.

    The dashboard is a pinned message showing:
    - Pending approvals
    - Committed items (in Jira)
    - Active decisions

    Ref: Spec Part 9.3
    """

    def __init__(self, client: SlackClient):
        self.client = client
        # In-memory cache of dashboard locations
        # In production, this would be persisted
        self._dashboards: dict[ChannelId, ChannelDashboard] = {}

    async def create_or_update(
        self,
        channel_id: ChannelId,
        pending_count: int = 0,
        approved_count: int = 0,
        committed_count: int = 0,
        decisions_count: int = 0,
        pending_items: list[dict[str, str]] | None = None,
        committed_items: list[dict[str, str]] | None = None,
    ) -> None:
        """Create or update channel dashboard.

        If dashboard exists, update it. Otherwise, create and pin.
        """
        blocks = build_dashboard_blocks(
            pending_count=pending_count,
            approved_count=approved_count,
            committed_count=committed_count,
            decisions_count=decisions_count,
            pending_items=pending_items,
            committed_items=committed_items,
        )

        existing = self._dashboards.get(channel_id)

        # If not in memory, search pinned messages for existing dashboard
        if not existing:
            existing = await self._find_pinned_dashboard(channel_id)

        if existing:
            # Update existing dashboard
            await self.client.update_message(
                channel_id=channel_id,
                ts=existing.message_ts,
                content=blocks,
            )
            logger.info(f"Updated dashboard in {channel_id}")
        else:
            # Create new dashboard and pin it
            message = await self.client.post_to_channel(
                channel_id=channel_id,
                content=blocks,
            )

            # Pin the message
            await self._pin_message(channel_id, message.ts)

            # Store reference
            self._dashboards[channel_id] = ChannelDashboard(
                channel_id=channel_id,
                message_ts=message.ts,
            )
            logger.info(f"Created and pinned dashboard in {channel_id}")

    async def _find_pinned_dashboard(self, channel_id: ChannelId) -> ChannelDashboard | None:
        """Search pinned messages for an existing dashboard.

        Looks for a pinned message with a header block containing
        "Channel Status" to identify the dashboard.
        """
        try:
            result = await self.client.client.pins_list(channel=channel_id)
            for item in result.get("items", []):
                message = item.get("message", {})
                blocks = message.get("blocks", [])
                for block in blocks:
                    if (
                        block.get("type") == "header"
                        and "Channel Status" in block.get("text", {}).get("text", "")
                    ):
                        ts = message.get("ts")
                        if ts:
                            dashboard = ChannelDashboard(
                                channel_id=channel_id,
                                message_ts=ts,
                            )
                            self._dashboards[channel_id] = dashboard
                            logger.info(f"Found existing pinned dashboard in {channel_id}: {ts}")
                            return dashboard
        except Exception as e:
            logger.warning(f"Failed to search pinned messages in {channel_id}: {e}")

        return None

    async def _pin_message(self, channel_id: ChannelId, ts: str) -> None:
        """Pin a message in the channel."""
        try:
            await self.client.client.pins_add(channel=channel_id, timestamp=ts)
        except Exception as e:
            # Pin might fail if bot doesn't have permission
            logger.warning(f"Failed to pin dashboard in {channel_id}: {e}")

    def get_dashboard(self, channel_id: ChannelId) -> ChannelDashboard | None:
        """Get dashboard info for a channel."""
        return self._dashboards.get(channel_id)

    def register_dashboard(
        self,
        channel_id: ChannelId,
        message_ts: str,
    ) -> None:
        """Register an existing dashboard (e.g., on startup from DB)."""
        self._dashboards[channel_id] = ChannelDashboard(
            channel_id=channel_id,
            message_ts=message_ts,
        )

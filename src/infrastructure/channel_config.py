"""Per-channel configuration storage.

Manages channel-specific settings like Jira project key.
"""

import logging
from dataclasses import dataclass

from src.infrastructure.database import get_pool

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """Channel-specific configuration."""
    channel_id: str
    jira_project: str | None = None


async def get_channel_config(channel_id: str) -> ChannelConfig:
    """Get configuration for a channel.

    Returns default config if no custom config exists.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT channel_id, jira_project FROM channel_config WHERE channel_id = $1",
            channel_id,
        )
        if row:
            return ChannelConfig(
                channel_id=row["channel_id"],
                jira_project=row["jira_project"],
            )
        return ChannelConfig(channel_id=channel_id)


async def set_jira_project(channel_id: str, jira_project: str) -> None:
    """Set the Jira project for a channel.

    Creates config entry if it doesn't exist.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO channel_config (channel_id, jira_project, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (channel_id) DO UPDATE
            SET jira_project = $2, updated_at = NOW()
            """,
            channel_id,
            jira_project,
        )
    logger.info(f"Set Jira project for {channel_id} to {jira_project}")


async def get_jira_project(channel_id: str) -> str | None:
    """Get the Jira project for a channel.

    Returns None if no channel-specific project is set.
    """
    config = await get_channel_config(channel_id)
    return config.jira_project

"""
Channel API endpoints.

Provides management of channel configurations.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.adapters.slack.config import ChannelConfig, ChannelSettings

router = APIRouter()

# In-memory config (in production, use database)
_channel_config = ChannelConfig()


class ChannelConfigRequest(BaseModel):
    """Request model for channel configuration."""

    jira_project_key: str = ""
    jira_project_id: str = ""
    enabled: bool = True


class ChannelConfigResponse(BaseModel):
    """Response model for channel configuration."""

    channel_id: str
    jira_project_key: str
    jira_project_id: str
    enabled: bool


@router.get("/")
async def list_channels() -> list[ChannelConfigResponse]:
    """
    List all configured channels.

    Returns:
        List of channel configurations.
    """
    channels = _channel_config.list_channels()
    return [
        ChannelConfigResponse(
            channel_id=c.channel_id,
            jira_project_key=c.jira_project_key,
            jira_project_id=c.jira_project_id,
            enabled=c.enabled,
        )
        for c in channels
    ]


@router.get("/{channel_id}")
async def get_channel_config(channel_id: str) -> ChannelConfigResponse:
    """
    Get configuration for a channel.

    Args:
        channel_id: Slack channel ID.

    Returns:
        Channel configuration.
    """
    config = _channel_config.get_channel(channel_id)

    if not config:
        # Return default config
        return ChannelConfigResponse(
            channel_id=channel_id,
            jira_project_key="",
            jira_project_id="",
            enabled=True,
        )

    return ChannelConfigResponse(
        channel_id=config.channel_id,
        jira_project_key=config.jira_project_key,
        jira_project_id=config.jira_project_id,
        enabled=config.enabled,
    )


@router.put("/{channel_id}")
async def update_channel_config(
    channel_id: str,
    request: ChannelConfigRequest,
) -> ChannelConfigResponse:
    """
    Update configuration for a channel.

    Args:
        channel_id: Slack channel ID.
        request: New configuration.

    Returns:
        Updated channel configuration.
    """
    config = _channel_config.set_channel(
        channel_id=channel_id,
        jira_project_key=request.jira_project_key,
        jira_project_id=request.jira_project_id,
    )

    if not request.enabled:
        _channel_config.disable_channel(channel_id)
    else:
        _channel_config.enable_channel(channel_id)

    return ChannelConfigResponse(
        channel_id=config.channel_id,
        jira_project_key=config.jira_project_key,
        jira_project_id=config.jira_project_id,
        enabled=config.enabled,
    )


@router.delete("/{channel_id}")
async def delete_channel_config(channel_id: str) -> dict:
    """
    Delete configuration for a channel.

    Args:
        channel_id: Slack channel ID.

    Returns:
        Deletion status.
    """
    _channel_config.disable_channel(channel_id)
    return {"deleted": True, "channel_id": channel_id}

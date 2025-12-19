"""
Slack Channel Configuration - Maps channels to Jira projects.

Manages per-channel settings including Jira project mapping.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelSettings:
    """Settings for a single Slack channel."""

    channel_id: str
    jira_project_key: str = ""
    jira_project_id: str = ""
    enabled: bool = True
    custom_settings: dict[str, Any] = field(default_factory=dict)


class ChannelConfig:
    """
    Manages channel-specific configuration.

    Maps Slack channels to Jira projects and stores
    per-channel settings.
    """

    def __init__(self) -> None:
        """Initialize empty channel config."""
        self._channels: dict[str, ChannelSettings] = {}

    def get_channel(self, channel_id: str) -> ChannelSettings | None:
        """
        Get settings for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Channel settings or None if not configured.
        """
        return self._channels.get(channel_id)

    def set_channel(
        self,
        channel_id: str,
        jira_project_key: str = "",
        jira_project_id: str = "",
        **custom_settings: Any,
    ) -> ChannelSettings:
        """
        Configure a channel.

        Args:
            channel_id: Slack channel ID.
            jira_project_key: Jira project key (e.g., "PROJ").
            jira_project_id: Jira project ID.
            **custom_settings: Additional settings.

        Returns:
            Updated channel settings.
        """
        settings = ChannelSettings(
            channel_id=channel_id,
            jira_project_key=jira_project_key,
            jira_project_id=jira_project_id,
            custom_settings=custom_settings,
        )
        self._channels[channel_id] = settings
        return settings

    def get_jira_project(self, channel_id: str) -> str | None:
        """
        Get Jira project key for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Jira project key or None.
        """
        settings = self.get_channel(channel_id)
        return settings.jira_project_key if settings else None

    def is_enabled(self, channel_id: str) -> bool:
        """
        Check if MARO is enabled for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            True if enabled (default True for unconfigured channels).
        """
        settings = self.get_channel(channel_id)
        return settings.enabled if settings else True

    def disable_channel(self, channel_id: str) -> None:
        """Disable MARO for a channel."""
        if channel_id in self._channels:
            self._channels[channel_id].enabled = False
        else:
            self._channels[channel_id] = ChannelSettings(
                channel_id=channel_id,
                enabled=False,
            )

    def enable_channel(self, channel_id: str) -> None:
        """Enable MARO for a channel."""
        if channel_id in self._channels:
            self._channels[channel_id].enabled = True

    def list_channels(self) -> list[ChannelSettings]:
        """Get all configured channels."""
        return list(self._channels.values())

    def to_dict(self) -> dict:
        """Serialize configuration."""
        return {
            channel_id: {
                "channel_id": settings.channel_id,
                "jira_project_key": settings.jira_project_key,
                "jira_project_id": settings.jira_project_id,
                "enabled": settings.enabled,
                "custom_settings": settings.custom_settings,
            }
            for channel_id, settings in self._channels.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelConfig":
        """Deserialize configuration."""
        config = cls()
        for channel_id, settings_data in data.items():
            config._channels[channel_id] = ChannelSettings(
                channel_id=settings_data["channel_id"],
                jira_project_key=settings_data.get("jira_project_key", ""),
                jira_project_id=settings_data.get("jira_project_id", ""),
                enabled=settings_data.get("enabled", True),
                custom_settings=settings_data.get("custom_settings", {}),
            )
        return config

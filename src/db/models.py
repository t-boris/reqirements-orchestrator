"""Pydantic models for database records.

These are data transfer objects, not ORM models. SQL operations are in session_store.py.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ThreadSession(BaseModel):
    """Represents one conversation session in a Slack thread.

    A session is keyed by (channel_id, thread_ts) and tracks the lifecycle
    of a potential Jira ticket from initial conversation to sync.
    """

    id: str = Field(description="UUID for the session")
    channel_id: str = Field(description="Slack channel ID")
    thread_ts: str = Field(description="Slack thread timestamp (unique with channel_id)")
    user_id: str = Field(description="Initiating user's Slack ID")
    status: Literal["collecting", "ready_to_sync", "synced"] = Field(
        default="collecting",
        description="Current status in the ticket lifecycle",
    )
    jira_key: Optional[str] = Field(
        default=None,
        description="Jira issue key after ticket is created (e.g., PROJ-123)",
    )
    epic_id: Optional[str] = Field(
        default=None,
        description="Linked Epic Jira key (e.g., PROJ-50)",
    )
    created_at: datetime = Field(description="When the session was created")
    updated_at: datetime = Field(description="When the session was last updated")


class ChannelConfig(BaseModel):
    """Layer 1: Manual channel configuration (highest priority for defaults)."""

    default_jira_project: Optional[str] = None
    secondary_projects: list[str] = Field(default_factory=list)
    trigger_rule: Literal["mention_only", "listen_all"] = "mention_only"
    epic_binding_behavior: Literal["suggest", "require", "skip"] = "suggest"
    config_permissions: Literal["locked", "open"] = "open"


class ChannelKnowledge(BaseModel):
    """Layer 2: Extracted from pinned content (highest priority for facts)."""

    naming_convention: Optional[str] = None
    definition_of_done: Optional[str] = None
    api_format_rules: Optional[str] = None
    custom_rules: dict[str, str] = Field(default_factory=dict)
    source_pin_ids: list[str] = Field(default_factory=list)


class ChannelActivitySnapshot(BaseModel):
    """Layer 3: Live summary of channel activity."""

    active_epics: list[str] = Field(default_factory=list)
    recent_tickets: list[str] = Field(default_factory=list)  # Last 10 ticket keys
    top_constraints: list[dict] = Field(default_factory=list)
    unresolved_conflicts: list[dict] = Field(default_factory=list)
    last_updated: Optional[datetime] = None


class ChannelContext(BaseModel):
    """Full channel context with 4 layers."""

    id: str = Field(description="UUID for the context record")
    team_id: str = Field(description="Slack team/workspace ID")
    channel_id: str = Field(description="Slack channel ID (unique)")

    # 4 layers with priority order: knowledge > jira > config > derived
    config: ChannelConfig = Field(default_factory=ChannelConfig)
    knowledge: ChannelKnowledge = Field(default_factory=ChannelKnowledge)
    activity: ChannelActivitySnapshot = Field(default_factory=ChannelActivitySnapshot)
    derived_signals: dict = Field(default_factory=dict)  # Layer 4: TTL-based

    # Version tracking
    version: int = Field(default=1)
    pinned_digest: Optional[str] = None  # Hash of pinned content
    jira_sync_cursor: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

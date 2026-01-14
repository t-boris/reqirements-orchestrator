"""Pydantic models for database records.

These are data transfer objects, not ORM models. SQL operations are in session_store.py.
"""
from datetime import datetime
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
    created_at: datetime = Field(description="When the session was created")
    updated_at: datetime = Field(description="When the session was last updated")


class ChannelContext(BaseModel):
    """Channel-level accumulated context.

    Placeholder for Phase 8 - stores accumulated knowledge per channel
    for proactive analyst behavior.
    """

    id: str = Field(description="UUID for the context record")
    channel_id: str = Field(description="Slack channel ID (unique)")
    context_data: dict = Field(
        default_factory=dict,
        description="JSON blob for flexible context storage",
    )
    updated_at: datetime = Field(description="When the context was last updated")

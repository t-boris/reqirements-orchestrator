"""Anchor message schema for Phase 33 - Anchor Message Architecture.

An anchor message is the canonical Slack representation of an object.
Every object (Decision, WorkItem, ChangeRequest, Draft) has at most one anchor
message per channel. The anchor IS the object's visual representation in Slack.
Thread under anchor = working tree for that object.

Core principles from CONTEXT.md:
- A1: Anchor = Object (any "created/approved/updated" message is an anchor)
- A2: Anchor Identity (mandatory object_id and object_type)
- A3: Context Inheritance (messages in thread inherit object_id)
- A4: Implicit Commands (commands default to anchor's object)
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AnchorType(str, Enum):
    """Entity types that can have anchor messages.

    Each entity type that can be represented in Slack as a canonical message.
    """

    DECISION = "decision"
    WORKITEM = "workitem"
    CHANGE_REQUEST = "change_request"
    DRAFT = "draft"


class AnchorMessage(BaseModel):
    """An anchor message is the canonical Slack representation of an object.

    INVARIANT: Each object has at most one anchor message per channel.
    The anchor message IS the object's visual representation in Slack.
    Thread under anchor = working tree for that object.

    This is the foundation for Rule A2: Anchor Identity.

    Attributes:
        id: UUID for this anchor record.
        anchor_type: Type of entity (decision, workitem, etc.).
        object_id: Entity ID (decision_id, workitem_id, etc.). String to support
            both UUIDs (workitem) and formatted IDs (DEC-41).
        channel_id: Slack channel where this anchor exists.
        message_ts: The anchor message timestamp in Slack.
        thread_ts: Thread for discussion (usually same as message_ts, since
            thread starts from anchor).
        created_at: When anchor was created.
        updated_at: When anchor was last modified.
        created_by: User who triggered anchor creation.
        version: Version tracking for optimistic locking on updates.
    """

    id: UUID = Field(description="UUID for this anchor record")
    anchor_type: AnchorType = Field(description="Type of entity this anchor represents")
    object_id: str = Field(
        description="Entity ID (decision_id, workitem_id, etc.). "
        "String to support both UUIDs and formatted IDs like DEC-41"
    )
    channel_id: str = Field(description="Slack channel where this anchor exists")
    message_ts: str = Field(description="The anchor message timestamp in Slack")
    thread_ts: Optional[str] = Field(
        default=None,
        description="Thread for discussion (usually same as message_ts)",
    )
    created_at: datetime = Field(description="When anchor was created")
    updated_at: datetime = Field(description="When anchor was last modified")
    created_by: str = Field(description="User who triggered anchor creation")
    version: int = Field(
        default=1,
        description="Version tracking for optimistic locking on updates",
    )

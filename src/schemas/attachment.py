"""Attachment entity schema.

Attachments are first-class entities representing files uploaded to Slack.
They have lifecycle states and can be pinned to context.

Pattern: Attachment as first-class object (not just text in history).
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AttachmentStatus(str, Enum):
    """Lifecycle states for attachments.

    pending: File detected, extraction not started
    extracting: Download/extraction in progress
    ready: Text extracted, available for use
    failed: Extraction failed (corrupted, unsupported)
    too_large: File exceeds size limit
    """
    PENDING = "pending"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"
    TOO_LARGE = "too_large"


class Attachment(BaseModel):
    """First-class attachment entity.

    Represents a file uploaded to Slack with extracted content.
    Can be pinned to context for automatic inclusion in prompts.
    """
    id: UUID
    channel_id: str
    thread_ts: Optional[str] = None

    # Slack file identity
    file_id: str = Field(description="Slack file ID (unique)")
    filename: str
    mimetype: str
    size_bytes: Optional[int] = None

    # Extracted content
    extracted_text: Optional[str] = None
    summary: Optional[str] = Field(
        default=None,
        description="1-3 line auto-summary for context preview"
    )
    token_count: Optional[int] = Field(
        default=None,
        description="Approximate token count of extracted text"
    )

    # Lifecycle
    status: AttachmentStatus = AttachmentStatus.PENDING
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if status is FAILED"
    )

    # Context control
    pinned: bool = Field(
        default=False,
        description="If True, auto-include in BUILD/THINK modes"
    )
    pinned_by: Optional[str] = None
    pinned_at: Optional[datetime] = None

    # Metadata
    uploaded_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

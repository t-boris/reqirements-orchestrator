"""ReviewArtifact entity schema for Phase 38 - Context Architecture.

ReviewArtifacts are persistent review artifacts (architecture, analysis, recommendation)
that are stored in the database. Checkpoint becomes cache, DB is source of truth.
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewArtifact(BaseModel):
    """A persistent review artifact with versioning.

    Review artifacts are produced during requirement review sessions.
    They capture architectural analysis, recommendations, and other
    review outputs that should persist across sessions.

    The checkpoint is a cache, the database is the source of truth.
    """

    model_config = ConfigDict(
        json_encoders={UUID: str, datetime: lambda v: v.isoformat()},
    )

    id: UUID = Field(description="UUID for the artifact")
    channel_id: str = Field(description="Slack channel this artifact belongs to")
    thread_ts: str = Field(description="Thread timestamp where artifact was created")
    topic: str = Field(description="Topic or subject of the review")
    summary: str = Field(description="Initial summary of the review")
    updated_summary: Optional[str] = Field(
        default=None,
        description="Updated summary after refinement",
    )
    kind: Literal["architecture", "analysis", "recommendation"] = Field(
        description="Type of review artifact",
    )
    version: int = Field(default=1, description="Version number, increments on update")
    persona: str = Field(description="Persona used for this review")
    content_hash: str = Field(
        description="Hash of content for deduplication/change detection",
    )
    created_at: datetime = Field(description="When artifact was created")
    updated_at: datetime = Field(description="When artifact was last modified")

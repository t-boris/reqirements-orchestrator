"""Pydantic models for database records.

These are data transfer objects, not ORM models. SQL operations are in session_store.py.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

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


class EpicSummary(BaseModel):
    """Summary of an epic for snapshot."""

    key: str = Field(description="Jira issue key")
    summary: str = Field(default="", description="Epic summary/title")
    status: str = Field(default="", description="Current status")
    child_count: int = Field(default=0, description="Number of child stories/tasks")


class WorkItemSummary(BaseModel):
    """Summary of a work item for snapshot."""

    key: str = Field(description="Jira issue key")
    summary: str = Field(default="", description="Item summary/title")
    item_type: str = Field(default="", description="Type (story, bug, task)")


class ChannelActivitySnapshot(BaseModel):
    """Layer 3: Live summary of channel activity.

    Enhanced for Rule 15: Includes ALL active work items, not just last 10.
    """

    # Epics with status (enhanced from just keys)
    active_epics: list[EpicSummary] = Field(default_factory=list)

    # Legacy field for backward compatibility
    recent_tickets: list[str] = Field(default_factory=list)

    # ALL active tickets, grouped by status (Rule 15 enhancement)
    work_items: dict[str, list[WorkItemSummary]] = Field(
        default_factory=dict,
        description="Work items grouped by status: {status: [items]}"
    )

    # Totals for quick reference
    item_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count by type: {epic: 5, story: 12, bug: 3}"
    )

    # Existing fields
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


class RootIndex(BaseModel):
    """Index entry for a root message (thread starter).

    Maps: channel_id + root_ts -> epic_id -> ticket_keys
    Used for channel activity snapshot and context.
    """

    id: str = Field(description="UUID")
    team_id: str
    channel_id: str
    root_ts: str = Field(description="Thread root message timestamp")
    text_summary: Optional[str] = Field(
        default=None, description="Brief summary of root topic (max 100 chars)"
    )
    entities: list[str] = Field(default_factory=list, description="Extracted entities/tags")
    epic_id: Optional[str] = None
    ticket_keys: list[str] = Field(default_factory=list)
    is_pinned: bool = Field(default=False, description="Pinned threads live beyond retention window")
    created_at: datetime
    updated_at: datetime


class ChannelListeningState(BaseModel):
    """Tracks whether MARO is actively listening in a channel.

    When enabled, MARO maintains a rolling summary of conversation context
    so it can provide better responses when mentioned.
    """

    team_id: str = Field(description="Slack team/workspace ID")
    channel_id: str = Field(description="Slack channel ID")
    enabled: bool = Field(default=False, description="Whether listening is active")
    enabled_at: datetime | None = Field(default=None, description="When listening was enabled")
    enabled_by: str | None = Field(default=None, description="User ID who enabled listening")
    summary: str | None = Field(default=None, description="Rolling conversation summary")
    raw_buffer: list[dict] = Field(default_factory=list, description="Last N messages as JSON")
    last_summary_at: datetime | None = Field(default=None, description="When summary was last updated")


class ChannelMode(str, Enum):
    """Channel operating mode that affects default behaviors.

    Modes affect:
    - Intent routing defaults (ticket vs review)
    - Scope gate options
    - Work item type preferences
    - Jira sync strictness
    """

    PROJECT = "project"  # Full work item types, all features enabled
    FEATURE = "feature"  # Focused on one epic, stories preferred
    BUGS = "bugs"  # Bug/task focused, epic suppressed
    OPS = "ops"  # Incidents, runbooks, stricter Jira writes


class ChannelModeConfig(BaseModel):
    """Channel mode configuration.

    Three-layer approach:
    1. Manual config = source of truth (/maro mode project)
    2. Suggested + confirm = one-time convenience for first setup
    3. Per-thread override = handles messy reality (bug thread in project channel)
    """

    id: str = Field(description="UUID for the config record")
    channel_id: str = Field(description="Slack channel ID (unique)")

    # Mode configuration
    mode: ChannelMode = Field(default=ChannelMode.PROJECT)
    primary_epic: str | None = Field(
        default=None, description="For FEATURE mode: the primary epic key"
    )

    # Configuration metadata
    set_by: str = Field(description="User ID who set the mode")
    set_at: datetime

    # Suggestion state (for first-time setup flow)
    suggestion_shown: bool = Field(
        default=False, description="Whether mode suggestion was shown"
    )
    suggestion_accepted: bool | None = Field(
        default=None,
        description="True if accepted, False if rejected, None if pending",
    )

    created_at: datetime
    updated_at: datetime


class ThreadModeOverride(BaseModel):
    """Per-thread mode override.

    Allows a specific thread to operate in a different mode than the channel default.
    Example: bug thread in a project channel.

    Resolution order: thread override > channel mode > PROJECT default
    """

    id: str = Field(description="UUID for the override record")
    channel_id: str = Field(description="Slack channel ID")
    thread_ts: str = Field(description="Slack thread timestamp")

    # Override configuration
    mode: ChannelMode = Field(description="Override mode for this thread")
    reason: str | None = Field(default=None, description="Why this override was set")

    # Metadata
    set_by: str = Field(description="User ID who set the override")
    set_at: datetime
    expires_at: datetime | None = Field(default=None, description="Optional expiry time")


class CommitType(str, Enum):
    """Types of commits to the channel work log.

    Commits track significant events that become channel truth.
    """

    DECISION = "decision"  # Architecture decision approved
    WORKITEM_CREATED = "workitem_created"  # New work item committed
    WORKITEM_UPDATED = "workitem_updated"  # Work item modified
    CONSTRAINT_ADDED = "constraint_added"  # Constraint/requirement captured
    JIRA_SYNCED = "jira_synced"  # Work item synced to Jira


class CommitEntry(BaseModel):
    """A commit entry in the channel work log.

    Commits are immutable records of significant events that became
    channel truth. Displayed in git-log style on the Channel Work Board.

    Format in board: "14:32 Decision: Use background worker [thread]"
    """

    id: str = Field(description="UUID for the commit entry")
    channel_id: str = Field(description="Channel this commit belongs to")

    # Commit content
    commit_type: CommitType = Field(description="Type of commit")
    summary: str = Field(description="One-line summary of what was committed")

    # Related entities
    workitem_id: str | None = Field(default=None, description="Related WorkItem UUID if any")
    thread_ts: str | None = Field(default=None, description="Source thread timestamp")

    # Metadata
    committed_by: str = Field(description="User ID who approved the commit")
    committed_at: datetime


class WorkItemType(str, Enum):
    """Types of work items in the registry."""

    EPIC = "epic"
    STORY = "story"
    BUG = "bug"
    TASK = "task"
    SPIKE = "spike"


class WorkItemStatus(str, Enum):
    """Lifecycle status of a work item."""

    DRAFT = "draft"  # Not yet committed to channel
    ACTIVE = "active"  # Committed, work in progress
    DONE = "done"  # Completed


class WorkItem(BaseModel):
    """A work item in the channel registry.

    WorkItems are the source of truth for work tracked in a channel.
    They may or may not have a corresponding Jira issue (jira_key).
    Drafts are first-class citizens that live in the registry before Jira creation.
    """

    id: str = Field(description="UUID for the work item")
    channel_id: str = Field(description="Slack channel this belongs to")
    item_type: WorkItemType = Field(description="Type of work item")
    status: WorkItemStatus = Field(default=WorkItemStatus.DRAFT)

    # Content
    summary: str = Field(description="Title/summary of the work item")
    description: str | None = Field(default=None, description="Full description")
    facts: dict[str, Any] = Field(default_factory=dict, description="Extracted facts/constraints")

    # Jira linkage (nullable - drafts don't have Jira keys)
    jira_key: str | None = Field(default=None, description="Jira issue key if synced")
    jira_sync_at: datetime | None = Field(default=None, description="Last sync timestamp")
    jira_fingerprint: dict[str, str] | None = Field(
        default=None, description="Section hashes for conflict detection"
    )

    # Hierarchy
    parent_id: str | None = Field(
        default=None, description="Parent WorkItem UUID (for stories under epics)"
    )

    # Provenance
    source_thread_ts: str | None = Field(
        default=None, description="Thread that created this item"
    )
    created_by: str = Field(description="User ID who created")
    created_at: datetime
    updated_at: datetime

    # Readiness (for drafts)
    readiness_score: float = Field(
        default=0.0, description="0.0-1.0 score for draft completeness"
    )

"""
LangGraph State Schema - Defines the state structure for the requirements workflow.

The state flows through all nodes and maintains context across the conversation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any

from langgraph.graph.message import add_messages


class RequirementStatus(str, Enum):
    """Lifecycle status of a requirement."""

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SYNCED = "SYNCED"


class IntentType(str, Enum):
    """Classified intent of user message."""

    REQUIREMENT = "requirement"  # New or updated requirement
    QUESTION = "question"  # Question about requirements
    JIRA_SYNC = "jira_sync"  # Request to sync with Jira
    JIRA_READ = "jira_read"  # Request to re-read Jira issue
    GENERAL = "general"  # General conversation
    OFF_TOPIC = "off_topic"  # Not related to requirements


class HumanDecision(str, Enum):
    """Possible decisions from human-in-the-loop."""

    APPROVE = "approve"
    APPROVE_ALWAYS = "approve_always"
    EDIT = "edit"
    REJECT = "reject"
    PENDING = "pending"


@dataclass
class Conflict:
    """Represents a conflict between requirements."""

    existing_id: str
    existing_summary: str
    conflict_type: str  # "contradiction", "duplicate", "overlap"
    description: str


@dataclass
class RequirementDraft:
    """Draft requirement ready for review."""

    title: str
    description: str
    issue_type: str  # Epic, Story, Task, Bug
    acceptance_criteria: list[str] = field(default_factory=list)
    priority: str = "medium"
    labels: list[str] = field(default_factory=list)
    parent_key: str | None = None  # For sub-tasks and stories under epics


@dataclass
class PersonaMatch:
    """Matched persona with confidence score."""

    persona_name: str
    confidence: float
    triggered: bool = False


class GraphState:
    """
    Main state schema for the LangGraph workflow.

    This TypedDict defines all fields that flow through the graph.
    Each node can read and update these fields.
    """

    # -------------------------------------------------------------------------
    # Input Context
    # -------------------------------------------------------------------------
    channel_id: str  # Slack channel ID
    thread_ts: str | None  # Slack thread timestamp (None = main channel)
    user_id: str  # Slack user ID
    message: str  # Current user message
    attachments: list[dict[str, Any]]  # Parsed attachment contents
    is_mention: bool  # Was bot @mentioned?

    # -------------------------------------------------------------------------
    # Conversation History (managed by add_messages reducer)
    # -------------------------------------------------------------------------
    messages: Annotated[list[dict], add_messages]

    # -------------------------------------------------------------------------
    # Memory Context (from Zep)
    # -------------------------------------------------------------------------
    zep_facts: list[dict[str, Any]]  # Retrieved facts from Zep
    zep_session_id: str | None  # Zep session ID for this channel
    related_jira_issues: list[dict[str, Any]]  # Found related Jira issues

    # -------------------------------------------------------------------------
    # Intent Classification
    # -------------------------------------------------------------------------
    intent: IntentType | None
    intent_confidence: float
    persona_matches: list[PersonaMatch]  # Which personas might handle this
    active_persona: str | None  # Currently active persona (None = main bot)

    # -------------------------------------------------------------------------
    # Requirement Processing
    # -------------------------------------------------------------------------
    current_goal: str | None  # Established goal for current discussion
    draft: RequirementDraft | None  # Current requirement draft
    critique_feedback: list[str]  # Feedback from critique node
    iteration_count: int  # Current draft-critique iteration
    conflicts: list[Conflict]  # Detected conflicts

    # -------------------------------------------------------------------------
    # Human-in-the-Loop
    # -------------------------------------------------------------------------
    awaiting_human: bool  # Is graph waiting for human decision?
    human_decision: HumanDecision
    human_feedback: str | None  # Edit feedback from human

    # -------------------------------------------------------------------------
    # Jira Operations
    # -------------------------------------------------------------------------
    jira_action: str | None  # create, update, link, search
    jira_issue_key: str | None  # Created/updated issue key
    jira_issue_data: dict[str, Any] | None  # Full issue data

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------
    response: str | None  # Response to send to Slack
    should_respond: bool  # Should bot respond to this message?
    error: str | None  # Error message if something failed


# Type alias for use in LangGraph
from typing import TypedDict


class RequirementState(TypedDict, total=False):
    """
    TypedDict version of GraphState for LangGraph compatibility.

    Using total=False makes all fields optional, allowing partial updates.
    """

    # Input Context
    channel_id: str
    thread_ts: str | None
    user_id: str
    message: str
    attachments: list[dict[str, Any]]
    is_mention: bool

    # Conversation History
    messages: Annotated[list[dict], add_messages]

    # Memory Context
    zep_facts: list[dict[str, Any]]
    zep_session_id: str | None
    related_jira_issues: list[dict[str, Any]]

    # Intent Classification
    intent: str | None
    intent_confidence: float
    persona_matches: list[dict[str, Any]]
    active_persona: str | None

    # Requirement Processing
    current_goal: str | None
    draft: dict[str, Any] | None
    critique_feedback: list[str]
    iteration_count: int
    conflicts: list[dict[str, Any]]

    # Human-in-the-Loop
    awaiting_human: bool
    human_decision: str
    human_feedback: str | None

    # Jira Operations
    jira_action: str | None
    jira_issue_key: str | None
    jira_issue_data: dict[str, Any] | None

    # Output
    response: str | None
    should_respond: bool
    error: str | None


def create_initial_state(
    channel_id: str,
    user_id: str,
    message: str,
    thread_ts: str | None = None,
    attachments: list[dict] | None = None,
    is_mention: bool = False,
) -> RequirementState:
    """
    Create initial state for a new graph invocation.

    Args:
        channel_id: Slack channel ID.
        user_id: Slack user ID.
        message: User message text.
        thread_ts: Slack thread timestamp.
        attachments: List of attachment data.
        is_mention: Whether bot was @mentioned.

    Returns:
        Initial RequirementState with defaults.
    """
    return RequirementState(
        # Input
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        message=message,
        attachments=attachments or [],
        is_mention=is_mention,
        # Conversation
        messages=[],
        # Memory
        zep_facts=[],
        zep_session_id=None,
        related_jira_issues=[],
        # Intent
        intent=None,
        intent_confidence=0.0,
        persona_matches=[],
        active_persona=None,
        # Processing
        current_goal=None,
        draft=None,
        critique_feedback=[],
        iteration_count=0,
        conflicts=[],
        # HITL
        awaiting_human=False,
        human_decision=HumanDecision.PENDING.value,
        human_feedback=None,
        # Jira
        jira_action=None,
        jira_issue_key=None,
        jira_issue_data=None,
        # Output
        response=None,
        should_respond=False,
        error=None,
    )

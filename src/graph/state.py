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

    PROCEED = "proceed"  # Skip questions and proceed to next phase
    REQUIREMENT = "requirement"  # New or updated requirement
    MODIFICATION = "modification"  # Change to existing requirements (needs impact analysis)
    QUESTION = "question"  # Question about requirements
    JIRA_SYNC = "jira_sync"  # Request to sync with Jira
    JIRA_READ = "jira_read"  # Request to re-read Jira issue
    JIRA_STATUS = "jira_status"  # Show status of thread items
    JIRA_ADD = "jira_add"  # Add story/task to existing epic
    JIRA_UPDATE = "jira_update"  # Update specific Jira issue
    JIRA_DELETE = "jira_delete"  # Delete a Jira issue
    GENERAL = "general"  # General conversation
    OFF_TOPIC = "off_topic"  # Not related to requirements


class HumanDecision(str, Enum):
    """Possible decisions from human-in-the-loop."""

    APPROVE = "approve"
    APPROVE_ALWAYS = "approve_always"
    EDIT = "edit"
    REJECT = "reject"
    PENDING = "pending"


class WorkflowPhase(str, Enum):
    """Workflow phase for multi-step requirements processing."""

    INTAKE = "intake"
    DISCOVERY = "discovery"
    ARCHITECTURE = "architecture"
    SCOPE = "scope"
    STORIES = "stories"
    TASKS = "tasks"
    ESTIMATION = "estimation"
    SECURITY = "security"
    VALIDATION = "validation"
    REVIEW = "review"
    JIRA_SYNC = "jira_sync"
    MONITORING = "monitoring"
    COMPLETE = "complete"


class ProgressStepStatus(str, Enum):
    """Status of a progress step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    WAITING_USER = "waiting_user"


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
    # Channel Configuration
    # -------------------------------------------------------------------------
    channel_config: dict[str, Any] | None  # Channel-specific settings

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
    all_drafts: list[dict[str, Any]] | None  # For complex requirements with multiple items
    is_complex_requirement: bool  # True if requirement was auto-split
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

    # Channel Configuration
    channel_config: dict[str, Any] | None

    # Output
    response: str | None
    should_respond: bool
    error: str | None

    # -------------------------------------------------------------------------
    # Workflow Progress (Phase 0)
    # -------------------------------------------------------------------------
    current_phase: str | None  # WorkflowPhase value
    phase_history: list[str]  # Completed phases
    progress_message_ts: str | None  # Slack message to update with progress
    progress_steps: list[dict[str, Any]]  # [{name, status, detail}]

    # -------------------------------------------------------------------------
    # Discovery Phase
    # -------------------------------------------------------------------------
    clarifying_questions: list[str]  # Questions to ask user
    user_answers: list[dict[str, Any]]  # {question, answer}
    discovered_requirements: list[dict[str, Any]]  # Gathered requirements

    # -------------------------------------------------------------------------
    # Architecture Phase
    # -------------------------------------------------------------------------
    architecture_options: list[dict[str, Any]]  # [{name, description, pros, cons, estimate}]
    chosen_architecture: str | None  # Selected option name
    selected_option: str | None  # User's selection input (e.g., "A", "Option B")
    selected_architecture: dict[str, Any] | None  # Full selected option details

    # -------------------------------------------------------------------------
    # Hierarchy (Epics → Stories → Tasks)
    # -------------------------------------------------------------------------
    epics: list[dict[str, Any]]  # Epic definitions
    stories: list[dict[str, Any]]  # Stories with epic_index
    tasks: list[dict[str, Any]]  # Tasks with story_index

    # -------------------------------------------------------------------------
    # Estimation
    # -------------------------------------------------------------------------
    total_story_points: int | None
    total_hours: int | None
    risk_buffer_percent: int | None

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------
    validation_report: dict[str, Any] | None  # {gaps, warnings, passed}

    # -------------------------------------------------------------------------
    # Jira Sync State
    # -------------------------------------------------------------------------
    jira_items: list[dict[str, Any]]  # [{type, key, title, status, last_synced}]
    pending_jira_updates: list[dict[str, Any]]  # Changes to push
    external_changes: list[dict[str, Any]]  # Changes from Jira webhooks
    last_full_sync: str | None  # ISO timestamp

    # -------------------------------------------------------------------------
    # Jira Command State (for re-read, status, add, update commands)
    # -------------------------------------------------------------------------
    jira_command_target: str | None  # Target issue key (e.g., "PROJ-123")
    jira_command_parent: str | None  # Parent for add operations (e.g., "EPIC-456")
    jira_command_type: str | None  # Type of item to add ("story", "task")
    jira_command_updates: dict[str, Any] | None  # Fields to update

    # -------------------------------------------------------------------------
    # Impact Analysis State
    # -------------------------------------------------------------------------
    impact_level: str | None  # architecture, scope, story, task, estimation, text_only
    impact_confidence: float | None
    affected_items: list[str]  # Keys or indices of affected items
    cascade_phases: list[str]  # Phases that need re-evaluation
    restart_phase: str | None  # Phase to restart from


def create_initial_state(
    channel_id: str,
    user_id: str,
    message: str,
    thread_ts: str | None = None,
    attachments: list[dict] | None = None,
    is_mention: bool = False,
    channel_config: dict[str, Any] | None = None,
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
        channel_config: Channel-specific configuration.

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
        all_drafts=None,
        is_complex_requirement=False,
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
        # Channel Config
        channel_config=channel_config,
        # Output
        response=None,
        should_respond=False,
        error=None,
        # Workflow Progress
        current_phase=None,
        phase_history=[],
        progress_message_ts=None,
        progress_steps=[],
        # Discovery
        clarifying_questions=[],
        user_answers=[],
        discovered_requirements=[],
        # Architecture
        architecture_options=[],
        chosen_architecture=None,
        # Hierarchy
        epics=[],
        stories=[],
        tasks=[],
        # Estimation
        total_story_points=None,
        total_hours=None,
        risk_buffer_percent=None,
        # Validation
        validation_report=None,
        # Jira Sync
        jira_items=[],
        pending_jira_updates=[],
        external_changes=[],
        last_full_sync=None,
        # Jira Commands
        jira_command_target=None,
        jira_command_parent=None,
        jira_command_type=None,
        jira_command_updates=None,
        # Impact Analysis
        impact_level=None,
        impact_confidence=None,
        affected_items=[],
        cascade_phases=[],
        restart_phase=None,
    )

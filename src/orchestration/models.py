"""Core orchestration models for task-based process orchestration.

Task-based orchestration replaces linear ProcessExecutor with flexible,
entity-centric workflows that support:
- Non-linear conversations
- Parallel task execution (fan-out)
- Emergent entity capture during discussion
- Multi-user collaboration

Ref: .planning/phases/05-process-orchestration/05-MODEL-PROPOSAL.md
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(str, Enum):
    """Task lifecycle status.

    Tasks progress through states based on conversation flow,
    not rigid stage sequences.
    """

    ACTIVE = "active"  # Currently being worked on
    WAITING = "waiting"  # Asked question, awaiting response
    BLOCKED = "blocked"  # Waiting on children/dependencies
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class QuestionType(str, Enum):
    """Type of question to ask the user."""

    OPEN = "open"  # Free text response
    CHOICE = "choice"  # Select one option
    CONFIRM = "confirm"  # Yes/No
    MULTI_SELECT = "multi"  # Select multiple


class Question(BaseModel):
    """A question posed to the user.

    Questions are context-gathering tools, not rigid stage prompts.
    The orchestrator generates questions dynamically based on
    what context is still needed.
    """

    model_config = ConfigDict(frozen=False)

    id: str
    text: str
    question_type: QuestionType
    options: list[str] | None = None  # For CHOICE/MULTI_SELECT
    context_key: str  # Where to store answer in task.context
    task_id: str  # Which task this belongs to


class Task(BaseModel):
    """A unit of work with a goal.

    Tasks gather context through conversation, can spawn children
    for fan-out, and complete when requirements are met. They're
    flexible containers, not rigid stage machines.

    Key design decisions:
    - context is a flat dict, not stage-indexed
    - target_entities are strings to avoid circular imports
    - contributors tracks all users who participated
    """

    model_config = ConfigDict(frozen=False)

    id: str
    goal: str  # "Create login story", "Architecture review for payments"
    flow_type: str  # Template: "create_work_item", "create_decision", etc.
    status: TaskStatus = TaskStatus.ACTIVE

    # Flexible context (not stage-indexed)
    context: dict[str, Any] = Field(default_factory=dict)
    target_entities: list[str] = Field(default_factory=list)  # EntityId strings

    # Question state
    pending_question: Question | None = None

    # Hierarchy for fan-out
    parent_task_id: str | None = None
    child_task_ids: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)

    # Multi-user tracking
    created_by: str  # UserId
    contributors: set[str] = Field(default_factory=set)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Workspace(BaseModel):
    """State container for a channel or thread.

    Workspaces track active tasks, maintain focus, and store
    draft entities being formed during conversation.
    """

    model_config = ConfigDict(frozen=False)

    channel_id: str
    thread_ts: str | None = None

    # Active work
    tasks: dict[str, Task] = Field(default_factory=dict)
    focus_task_id: str | None = None  # Currently active task (for routing)

    # Entities being formed in this workspace
    draft_entities: dict[str, Any] = Field(default_factory=dict)

    # Conversation context (LLM can use this)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)

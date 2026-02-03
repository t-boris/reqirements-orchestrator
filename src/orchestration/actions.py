"""Orchestrator action types - commands returned by Orchestrator.

These are immutable dataclasses representing commands that the Orchestrator
wants the caller to execute. The Orchestrator doesn't make direct Slack/external
calls - it returns actions that the caller interprets and executes.

This separation allows:
- Easy testing (just check returned actions)
- Flexibility in execution (caller decides how to post messages, etc.)
- Clear contract between orchestration logic and I/O
"""

from dataclasses import dataclass
from typing import Any

from src.orchestration.models import Task, Question


@dataclass(frozen=True)
class OrchestratorAction:
    """Base for actions returned by Orchestrator."""
    pass


@dataclass(frozen=True)
class AskQuestion(OrchestratorAction):
    """Post a question to the user."""
    question: Question


@dataclass(frozen=True)
class PostMessage(OrchestratorAction):
    """Post a message to the thread."""
    text: str
    blocks: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class TaskCreated(OrchestratorAction):
    """Notify that a task was created."""
    task: Task


@dataclass(frozen=True)
class TaskSpawned(OrchestratorAction):
    """Notify that a child task was spawned."""
    parent_task_id: str
    child_task: Task


@dataclass(frozen=True)
class TaskCompleted(OrchestratorAction):
    """Notify that a task completed."""
    task_id: str
    entities_created: list[str]


@dataclass(frozen=True)
class SwitchFocus(OrchestratorAction):
    """Switch workspace focus to different task."""
    from_task_id: str | None
    to_task_id: str


@dataclass(frozen=True)
class OfferCompletion(OrchestratorAction):
    """Offer user the chance to complete/continue task."""
    task: Task
    message: str


@dataclass(frozen=True)
class EntityDetected(OrchestratorAction):
    """Notify that an entity was detected in conversation."""
    entity_type: str  # "work_item" or "decision"
    content: str
    confidence: float


@dataclass(frozen=True)
class UpdateSummary(OrchestratorAction):
    """Update workspace conversation summary."""
    summary: str
    key_points: list[str]

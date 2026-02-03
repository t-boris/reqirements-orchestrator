"""Task-specific domain events for event sourcing.

This module defines events for Task and Workspace state changes.
All events extend DomainEvent which provides aggregate_id (channel_id),
actor_id, timestamp, correlation_id, causation_id, and version.

Based on 05-CONTEXT.md Task-based orchestration model.
"""

from typing import Any

from src.domain.events import DomainEvent


class TaskCreated(DomainEvent):
    """Task created in workspace.

    Emitted when a new task is created to track a goal (e.g., "create login story").
    """

    task_id: str
    goal: str
    flow_type: str
    thread_ts: str | None = None
    parent_task_id: str | None = None


class TaskCompleted(DomainEvent):
    """Task completed successfully.

    Emitted when a task has achieved its goal and all required context gathered.
    """

    task_id: str
    target_entities: list[str]  # EntityIds created/modified
    final_context: dict[str, Any]


class TaskCancelled(DomainEvent):
    """Task cancelled before completion.

    Emitted when a task is cancelled (e.g., user abandons flow).
    """

    task_id: str
    reason: str


class TaskBlocked(DomainEvent):
    """Task blocked waiting on dependencies.

    Emitted when a task is waiting on child tasks (fan-out pattern).
    """

    task_id: str
    blocked_by: list[str]  # Task IDs


class TaskUnblocked(DomainEvent):
    """Task unblocked, can continue.

    Emitted when all blocking dependencies are resolved.
    """

    task_id: str


class TaskContextUpdated(DomainEvent):
    """Task context updated with new information.

    Emitted when new context is gathered during task execution.
    """

    task_id: str
    context_key: str
    context_value: Any


class TaskFocusSwitched(DomainEvent):
    """Workspace focus switched to different task.

    Emitted when user switches focus between tasks (e.g., "let's go back to...").
    """

    from_task_id: str | None
    to_task_id: str


class WorkspaceSummaryUpdated(DomainEvent):
    """Workspace conversation summary updated.

    Emitted when the workspace summary is updated with conversation context.
    """

    summary: str
    key_points: list[str]

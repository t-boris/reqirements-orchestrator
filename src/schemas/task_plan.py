"""TaskPlan and Task schemas for multi-intent orchestration.

Phase 35: Multi-Intent Task Orchestration

TaskPlan replaces single IntentResult with a list of tasks that can be
executed independently or in dependency order. Each task has status,
safety classification, and side effects tracking.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field, model_validator

from src.schemas.intent import Intent, SuperMode


class TaskStatus(str, Enum):
    """Status of a task within a TaskPlan.

    Lifecycle: PENDING -> RUNNING -> (BLOCKED | DONE | CANCELED)
    """
    PENDING = "pending"      # Not yet started
    RUNNING = "running"      # Currently executing
    BLOCKED = "blocked"      # Waiting for user input or dependency
    DONE = "done"            # Completed successfully
    CANCELED = "canceled"    # Stopped by user or system


class SafetyLevel(str, Enum):
    """Safety classification for task execution.

    Determines whether a task can auto-execute or requires user confirmation.
    Maps to SuperMode: THINK/CHAT -> AUTO_EXECUTE, BUILD/OPERATE/DECIDE -> REQUIRES_CONFIRMATION
    """
    AUTO_EXECUTE = "auto_execute"              # Safe to run without confirmation (THINK, CHAT tasks)
    REQUIRES_CONFIRMATION = "requires_confirmation"  # Needs user approval (BUILD, OPERATE, DECIDE tasks)


class SideEffect(str, Enum):
    """Side effects a task may produce.

    Used for dependency analysis and user communication.
    """
    NONE = "none"          # Pure read/analysis
    SLACK = "slack"        # Posts messages
    JIRA = "jira"          # Creates/updates Jira
    REGISTRY = "registry"  # Modifies local registry


class Task(BaseModel):
    """A single task within a TaskPlan.

    Tasks are atomic units of work with clear status, safety classification,
    and dependency tracking. Each task operates on a specific target (anchor).
    """
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: SuperMode  # User-facing mode
    intent: Intent   # Internal routing intent
    title: str       # Human-readable title
    status: TaskStatus = TaskStatus.PENDING
    safety_level: Optional[SafetyLevel] = None  # Auto-set by validator if not provided
    side_effects: list[SideEffect] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)  # task_ids
    target: Optional[str] = None  # anchor: channel|thread|decision_id|jira_key
    params: dict[str, Any] = Field(default_factory=dict)  # Intent-specific params
    progress: Optional[dict[str, int]] = None  # {current, total} for batch ops
    requires_user_input: bool = False
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @model_validator(mode='after')
    def set_safety_level(self) -> 'Task':
        """Auto-set safety level based on mode and side effects."""
        if self.safety_level is None:
            from src.graph.safety import classify_task_safety
            # Use object.__setattr__ to bypass frozen model restriction
            object.__setattr__(self, 'safety_level', classify_task_safety(self))
        return self

    def can_auto_execute(self) -> bool:
        """Check if this task can run without user confirmation.

        Returns:
            True if safety_level is AUTO_EXECUTE, False otherwise.
        """
        return self.safety_level == SafetyLevel.AUTO_EXECUTE

    def needs_confirmation(self) -> bool:
        """Check if this task requires user approval.

        Returns:
            True if safety_level is REQUIRES_CONFIRMATION, False otherwise.
        """
        return self.safety_level == SafetyLevel.REQUIRES_CONFIRMATION


class TaskPlanStatus(str, Enum):
    """Status of the overall TaskPlan.

    Computed from aggregate task statuses.
    """
    PENDING = "pending"    # Plan created, not started
    RUNNING = "running"    # At least one task running
    BLOCKED = "blocked"    # All tasks blocked or waiting
    DONE = "done"          # All tasks complete
    CANCELED = "canceled"  # Plan canceled by user


class TaskPlan(BaseModel):
    """A plan containing multiple tasks for multi-intent orchestration.

    TaskPlan is the primary data structure for Phase 35. It replaces single-intent
    classification with a list of tasks that can be executed independently or
    in dependency order.

    Key features:
    - Tasks can have dependencies (execute in order)
    - Each task has safety classification (auto vs confirm)
    - Single editable status card in Slack (ui_message_ts)
    - Version tracking for button idempotency
    """
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel_id: str
    thread_ts: Optional[str] = None
    anchor: Optional[str] = None  # Primary object this plan operates on
    tasks: list[Task] = Field(default_factory=list)
    status: TaskPlanStatus = TaskPlanStatus.PENDING
    created_by: str  # user_id
    ui_message_ts: Optional[str] = None  # Status card message
    version: int = 1  # For button idempotency
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.

        Args:
            task_id: The task ID to look up.

        Returns:
            Task if found, None otherwise.
        """
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_next_pending_task(self) -> Optional[Task]:
        """Find the first PENDING task with all dependencies DONE.

        Returns:
            The next executable task, or None if no tasks are ready.
        """
        for task in self.tasks:
            if task.status != TaskStatus.PENDING:
                continue

            # Check if all dependencies are DONE
            deps_done = all(
                self.get_task(dep_id) is not None
                and self.get_task(dep_id).status == TaskStatus.DONE  # type: ignore
                for dep_id in task.depends_on
            )

            if deps_done:
                return task

        return None

    def get_blocked_tasks(self) -> list[Task]:
        """Get tasks that are waiting for user input.

        Returns:
            List of tasks with status BLOCKED or requires_user_input=True.
        """
        return [
            task for task in self.tasks
            if task.status == TaskStatus.BLOCKED or task.requires_user_input
        ]

    def all_done(self) -> bool:
        """Check if all tasks are DONE.

        Returns:
            True if all tasks have status DONE, False otherwise.
        """
        return all(task.status == TaskStatus.DONE for task in self.tasks)

    def has_running(self) -> bool:
        """Check if any task is currently RUNNING.

        Returns:
            True if any task has status RUNNING, False otherwise.
        """
        return any(task.status == TaskStatus.RUNNING for task in self.tasks)

    def increment_version(self) -> None:
        """Bump version and update timestamp.

        Call this before any state update that should invalidate old buttons.
        """
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)

    def compute_status(self) -> TaskPlanStatus:
        """Compute the overall plan status from task statuses.

        Returns:
            The computed TaskPlanStatus based on aggregate task states.
        """
        if not self.tasks:
            return TaskPlanStatus.PENDING

        # Check for any canceled tasks
        if any(task.status == TaskStatus.CANCELED for task in self.tasks):
            # If all non-done tasks are canceled, plan is canceled
            non_done = [t for t in self.tasks if t.status != TaskStatus.DONE]
            if all(t.status == TaskStatus.CANCELED for t in non_done):
                return TaskPlanStatus.CANCELED

        # Check if all done
        if self.all_done():
            return TaskPlanStatus.DONE

        # Check for running
        if self.has_running():
            return TaskPlanStatus.RUNNING

        # Check if all remaining are blocked
        non_done_non_canceled = [
            t for t in self.tasks
            if t.status not in (TaskStatus.DONE, TaskStatus.CANCELED)
        ]
        if non_done_non_canceled and all(
            t.status == TaskStatus.BLOCKED for t in non_done_non_canceled
        ):
            return TaskPlanStatus.BLOCKED

        # Check if we have pending tasks that can run
        if self.get_next_pending_task() is not None:
            return TaskPlanStatus.PENDING

        # Blocked on dependencies
        return TaskPlanStatus.BLOCKED

    def get_safe_tasks(self) -> list[Task]:
        """Get tasks that can auto-execute.

        Returns:
            List of tasks with safety_level AUTO_EXECUTE.
        """
        return [t for t in self.tasks if t.can_auto_execute()]

    def get_confirmation_tasks(self) -> list[Task]:
        """Get tasks requiring user confirmation.

        Returns:
            List of tasks with safety_level REQUIRES_CONFIRMATION.
        """
        return [t for t in self.tasks if t.needs_confirmation()]

    def has_dangerous_tasks(self) -> bool:
        """Check if any tasks need confirmation.

        Returns:
            True if any task has safety_level REQUIRES_CONFIRMATION.
        """
        return any(t.needs_confirmation() for t in self.tasks)


# =============================================================================
# Safety level mapping from SuperMode
# =============================================================================

SUPER_MODE_TO_SAFETY: dict[SuperMode, SafetyLevel] = {
    SuperMode.BUILD: SafetyLevel.REQUIRES_CONFIRMATION,
    SuperMode.OPERATE: SafetyLevel.REQUIRES_CONFIRMATION,
    SuperMode.DECIDE: SafetyLevel.REQUIRES_CONFIRMATION,
    SuperMode.THINK: SafetyLevel.AUTO_EXECUTE,
    SuperMode.CHAT: SafetyLevel.AUTO_EXECUTE,
}


def get_safety_level(mode: SuperMode) -> SafetyLevel:
    """Get the safety level for a super mode.

    Args:
        mode: The user-facing super mode.

    Returns:
        The corresponding safety level.
    """
    return SUPER_MODE_TO_SAFETY.get(mode, SafetyLevel.REQUIRES_CONFIRMATION)

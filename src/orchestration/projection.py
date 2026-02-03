"""Workspace projection for read model."""

import logging
from typing import Any

from src.domain.events import DomainEvent
from src.orchestration.models import Task, TaskStatus, Workspace
from src.orchestration.events import (
    TaskCreated,
    TaskCompleted,
    TaskCancelled,
    TaskBlocked,
    TaskUnblocked,
    TaskContextUpdated,
    TaskFocusSwitched,
    WorkspaceSummaryUpdated,
)

logger = logging.getLogger(__name__)


class WorkspaceProjection:
    """Maintains workspace read model from events.

    This projection tracks:
    - Active workspaces by channel/thread
    - Tasks within each workspace
    - Workspace state (focus, summary)

    Unlike ChannelAggregate (write model), this is optimized for queries.
    """

    def __init__(self):
        # channel_id -> thread_ts -> Workspace
        # If thread_ts is None, it's channel-level workspace
        self._workspaces: dict[str, dict[str | None, Workspace]] = {}

        # Quick lookup: thread_ts -> channel_id (for active thread checks)
        self._active_threads: dict[str, str] = {}

    def apply(self, event: DomainEvent) -> None:
        """Apply event to update projection."""
        channel_id = event.aggregate_id

        if isinstance(event, TaskCreated):
            self._on_task_created(channel_id, event)
        elif isinstance(event, TaskCompleted):
            self._on_task_completed(channel_id, event)
        elif isinstance(event, TaskCancelled):
            self._on_task_cancelled(channel_id, event)
        elif isinstance(event, TaskBlocked):
            self._on_task_blocked(channel_id, event)
        elif isinstance(event, TaskUnblocked):
            self._on_task_unblocked(channel_id, event)
        elif isinstance(event, TaskContextUpdated):
            self._on_context_updated(channel_id, event)
        elif isinstance(event, TaskFocusSwitched):
            self._on_focus_switched(channel_id, event)
        elif isinstance(event, WorkspaceSummaryUpdated):
            self._on_summary_updated(channel_id, event)

    def get_workspace(
        self,
        channel_id: str,
        thread_ts: str | None = None,
    ) -> Workspace | None:
        """Get workspace for channel/thread."""
        channel_workspaces = self._workspaces.get(channel_id, {})
        return channel_workspaces.get(thread_ts)

    def get_or_create_workspace(
        self,
        channel_id: str,
        thread_ts: str | None = None,
    ) -> Workspace:
        """Get existing workspace or create new one."""
        workspace = self.get_workspace(channel_id, thread_ts)
        if workspace is None:
            workspace = Workspace(channel_id=channel_id, thread_ts=thread_ts)
            if channel_id not in self._workspaces:
                self._workspaces[channel_id] = {}
            self._workspaces[channel_id][thread_ts] = workspace
            if thread_ts:
                self._active_threads[thread_ts] = channel_id
        return workspace

    def has_active_workspace(self, thread_ts: str) -> bool:
        """Check if thread has an active workspace."""
        return thread_ts in self._active_threads

    def get_active_workspace_threads(self) -> set[str]:
        """Get all thread_ts values with active workspaces."""
        return set(self._active_threads.keys())

    def get_task(
        self,
        channel_id: str,
        thread_ts: str | None,
        task_id: str,
    ) -> Task | None:
        """Get specific task from workspace."""
        workspace = self.get_workspace(channel_id, thread_ts)
        if workspace:
            return workspace.tasks.get(task_id)
        return None

    # Event handlers

    def _on_task_created(self, channel_id: str, event: TaskCreated) -> None:
        workspace = self.get_or_create_workspace(channel_id, event.thread_ts)
        task = Task(
            id=event.task_id,
            goal=event.goal,
            flow_type=event.flow_type,
            status=TaskStatus.ACTIVE,
            created_by=event.actor_id,
            contributors={event.actor_id},
            parent_task_id=event.parent_task_id,
            created_at=event.timestamp,
            updated_at=event.timestamp,
        )
        workspace.tasks[task.id] = task
        workspace.focus_task_id = task.id

    def _on_task_completed(self, channel_id: str, event: TaskCompleted) -> None:
        # Find workspace containing this task
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            task = workspace.tasks.get(event.task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                task.target_entities = event.target_entities
                task.context = event.final_context
                task.updated_at = event.timestamp
                break

    def _on_task_cancelled(self, channel_id: str, event: TaskCancelled) -> None:
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            task = workspace.tasks.get(event.task_id)
            if task:
                task.status = TaskStatus.CANCELLED
                task.updated_at = event.timestamp
                break

    def _on_task_blocked(self, channel_id: str, event: TaskBlocked) -> None:
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            task = workspace.tasks.get(event.task_id)
            if task:
                task.status = TaskStatus.BLOCKED
                task.blocked_by = event.blocked_by
                task.updated_at = event.timestamp
                break

    def _on_task_unblocked(self, channel_id: str, event: TaskUnblocked) -> None:
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            task = workspace.tasks.get(event.task_id)
            if task:
                task.status = TaskStatus.ACTIVE
                task.blocked_by = []
                task.updated_at = event.timestamp
                break

    def _on_context_updated(self, channel_id: str, event: TaskContextUpdated) -> None:
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            task = workspace.tasks.get(event.task_id)
            if task:
                task.context[event.context_key] = event.context_value
                task.updated_at = event.timestamp
                break

    def _on_focus_switched(self, channel_id: str, event: TaskFocusSwitched) -> None:
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            if event.from_task_id in workspace.tasks or event.to_task_id in workspace.tasks:
                workspace.focus_task_id = event.to_task_id
                break

    def _on_summary_updated(self, channel_id: str, event: WorkspaceSummaryUpdated) -> None:
        for thread_ts, workspace in self._workspaces.get(channel_id, {}).items():
            # Apply to first workspace in channel (simplified)
            workspace.summary = event.summary
            workspace.key_points = event.key_points
            break

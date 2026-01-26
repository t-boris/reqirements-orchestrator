"""TaskPlanStore with async CRUD operations using psycopg v3.

Phase 35: Multi-Intent Task Orchestration

Provides database persistence for TaskPlan entities with JSONB task storage.
Follows the WorkItemStore pattern for consistency.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.task_plan import (
    Task,
    TaskPlan,
    TaskPlanStatus,
    TaskStatus,
)


class TaskPlanStore:
    """Store for TaskPlan entities with CRUD operations.

    Tasks are stored as JSONB array within the task_plans table
    (not a separate table) for atomic updates.

    Usage:
        async with get_connection() as conn:
            store = TaskPlanStore(conn)
            plan = await store.create(TaskPlan(...))
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create task_plans table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS task_plans (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    plan_id TEXT UNIQUE NOT NULL,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT,
                    anchor TEXT,
                    tasks JSONB NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_by TEXT NOT NULL,
                    ui_message_ts TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Index for thread lookup (find active plan for thread)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_plans_thread
                ON task_plans(channel_id, thread_ts)
                WHERE status NOT IN ('done', 'canceled')
            """)

            # Index for channel lookup (all plans in channel)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_plans_channel
                ON task_plans(channel_id)
            """)

            await self._conn.commit()

    async def create(self, plan: TaskPlan) -> TaskPlan:
        """Insert new TaskPlan with tasks.

        Args:
            plan: TaskPlan to create.

        Returns:
            TaskPlan: The created plan with database timestamps.
        """
        # Serialize tasks to JSON
        tasks_json = json.dumps([task.model_dump(mode="json") for task in plan.tasks])

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO task_plans (
                    plan_id, channel_id, thread_ts, anchor, tasks,
                    status, created_by, ui_message_ts, version,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING plan_id, channel_id, thread_ts, anchor, tasks,
                          status, created_by, ui_message_ts, version,
                          created_at, updated_at
                """,
                (
                    plan.plan_id,
                    plan.channel_id,
                    plan.thread_ts,
                    plan.anchor,
                    tasks_json,
                    plan.status.value,
                    plan.created_by,
                    plan.ui_message_ts,
                    plan.version,
                    plan.created_at,
                    plan.updated_at,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_plan(row)

    async def get(self, plan_id: str, *, for_update: bool = False) -> Optional[TaskPlan]:
        """Get TaskPlan by ID.

        Args:
            plan_id: The plan ID to look up.
            for_update: If True, lock row for update (prevents concurrent modifications).

        Returns:
            TaskPlan if found, None otherwise.
        """
        query = """
            SELECT plan_id, channel_id, thread_ts, anchor, tasks,
                   status, created_by, ui_message_ts, version,
                   created_at, updated_at
            FROM task_plans
            WHERE plan_id = %s
        """
        if for_update:
            query += " FOR UPDATE"

        async with self._conn.cursor() as cur:
            await cur.execute(query, (plan_id,))
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_plan(row)

    async def get_by_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[TaskPlan]:
        """Get active TaskPlan for a thread (status not DONE/CANCELED).

        Args:
            channel_id: Slack channel ID.
            thread_ts: Thread timestamp.

        Returns:
            TaskPlan if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT plan_id, channel_id, thread_ts, anchor, tasks,
                       status, created_by, ui_message_ts, version,
                       created_at, updated_at
                FROM task_plans
                WHERE channel_id = %s
                  AND thread_ts = %s
                  AND status NOT IN ('done', 'canceled')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_plan(row)

    async def update(self, plan: TaskPlan) -> TaskPlan:
        """Update TaskPlan (bumps version).

        Uses optimistic locking - fails if version doesn't match.

        Args:
            plan: TaskPlan with updated fields.

        Returns:
            TaskPlan: The updated plan.

        Raises:
            ValueError: If plan not found or version mismatch (stale update).
        """
        # Serialize tasks to JSON
        tasks_json = json.dumps([task.model_dump(mode="json") for task in plan.tasks])
        now = datetime.now(timezone.utc)
        new_version = plan.version + 1

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE task_plans
                SET tasks = %s,
                    status = %s,
                    anchor = %s,
                    ui_message_ts = %s,
                    version = %s,
                    updated_at = %s
                WHERE plan_id = %s AND version = %s
                RETURNING plan_id, channel_id, thread_ts, anchor, tasks,
                          status, created_by, ui_message_ts, version,
                          created_at, updated_at
                """,
                (
                    tasks_json,
                    plan.status.value,
                    plan.anchor,
                    plan.ui_message_ts,
                    new_version,
                    now,
                    plan.plan_id,
                    plan.version,  # Optimistic lock check
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(
                f"TaskPlan {plan.plan_id} not found or version mismatch "
                f"(expected version {plan.version})"
            )

        return self._row_to_plan(row)

    async def update_task_status(
        self,
        plan_id: str,
        task_id: str,
        status: TaskStatus,
        error: Optional[str] = None,
    ) -> TaskPlan:
        """Update single task status within plan.

        Atomically updates task status and recalculates plan status.

        Args:
            plan_id: The plan ID.
            task_id: The task ID within the plan.
            status: New status for the task.
            error: Optional error message if status is BLOCKED.

        Returns:
            TaskPlan: The updated plan.

        Raises:
            ValueError: If plan or task not found.
        """
        # Get plan with lock
        plan = await self.get(plan_id, for_update=True)
        if not plan:
            raise ValueError(f"TaskPlan not found: {plan_id}")

        # Find and update task
        task = plan.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.status = status
        if error is not None:
            task.last_error = error

        # Set timestamps
        now = datetime.now(timezone.utc)
        task.state_changed_at = now  # Track state change time for visual feedback
        if status == TaskStatus.RUNNING:
            task.started_at = now
        elif status in (TaskStatus.DONE, TaskStatus.CANCELED):
            task.completed_at = now

        # Recalculate plan status
        plan.status = plan.compute_status()

        # Save
        return await self.update(plan)

    async def update_ui_message(self, plan_id: str, message_ts: str) -> None:
        """Set the status card message timestamp.

        Args:
            plan_id: The plan ID.
            message_ts: Slack message timestamp for the status card.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE task_plans
                SET ui_message_ts = %s, updated_at = %s
                WHERE plan_id = %s
                """,
                (message_ts, now, plan_id),
            )
            await self._conn.commit()

    async def cancel_plan(self, plan_id: str, user_id: str) -> TaskPlan:
        """Cancel entire plan (all non-DONE tasks -> CANCELED).

        Args:
            plan_id: The plan ID to cancel.
            user_id: User who canceled (for audit).

        Returns:
            TaskPlan: The canceled plan.

        Raises:
            ValueError: If plan not found.
        """
        # Get plan with lock
        plan = await self.get(plan_id, for_update=True)
        if not plan:
            raise ValueError(f"TaskPlan not found: {plan_id}")

        # Cancel all non-done tasks
        now = datetime.now(timezone.utc)
        for task in plan.tasks:
            if task.status != TaskStatus.DONE:
                task.status = TaskStatus.CANCELED
                task.completed_at = now

        plan.status = TaskPlanStatus.CANCELED

        # Save
        return await self.update(plan)

    async def list_by_channel(
        self,
        channel_id: str,
        *,
        status: list[TaskPlanStatus] | None = None,
        limit: int = 20,
    ) -> list[TaskPlan]:
        """List TaskPlans for a channel with optional status filter.

        Args:
            channel_id: Slack channel ID.
            status: Optional list of statuses to filter by.
            limit: Maximum plans to return.

        Returns:
            List of TaskPlan objects, ordered by created_at DESC.
        """
        query = """
            SELECT plan_id, channel_id, thread_ts, anchor, tasks,
                   status, created_by, ui_message_ts, version,
                   created_at, updated_at
            FROM task_plans
            WHERE channel_id = %s
        """
        params: list = [channel_id]

        if status is not None:
            status_values = [s.value for s in status]
            placeholders = ", ".join(["%s"] * len(status_values))
            query += f" AND status IN ({placeholders})"
            params.extend(status_values)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_plan(row) for row in rows]

    def _row_to_plan(self, row: tuple) -> TaskPlan:
        """Convert database row to TaskPlan model.

        Args:
            row: Tuple from database query.
                Expected order (11 columns):
                0: plan_id, 1: channel_id, 2: thread_ts, 3: anchor,
                4: tasks (JSONB), 5: status, 6: created_by,
                7: ui_message_ts, 8: version, 9: created_at, 10: updated_at

        Returns:
            TaskPlan model instance.
        """
        # Parse tasks from JSONB
        tasks_data = row[4] if row[4] else []
        tasks = [Task.model_validate(t) for t in tasks_data]

        return TaskPlan(
            plan_id=row[0],
            channel_id=row[1],
            thread_ts=row[2],
            anchor=row[3],
            tasks=tasks,
            status=TaskPlanStatus(row[5]),
            created_by=row[6],
            ui_message_ts=row[7],
            version=row[8],
            created_at=row[9],
            updated_at=row[10],
        )

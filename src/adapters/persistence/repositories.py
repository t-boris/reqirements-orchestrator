"""
Repository classes for database operations.

Provides a clean interface for CRUD operations on each entity type.
"""

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.persistence.models import (
    EventModel,
    GraphSnapshotModel,
    ChannelConfigModel,
    AuditLogModel,
    SyncHistoryModel,
)
from src.core.events.models import Event, EventType

logger = structlog.get_logger()


class EventRepository:
    """
    Repository for event sourcing events.

    Handles persistence and retrieval of graph mutation events.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def save(self, event: Event) -> None:
        """
        Save an event to the database.

        Args:
            event: Event to persist.
        """
        model = EventModel(
            id=event.id,
            channel_id=event.channel_id,
            user_id=event.user_id,
            event_type=event.type.value,
            sequence=event.sequence,
            payload=event.payload,
            timestamp=event.timestamp,
        )
        self._session.add(model)

    async def save_batch(self, events: list[Event]) -> None:
        """
        Save multiple events in a batch.

        Args:
            events: Events to persist.
        """
        models = [
            EventModel(
                id=e.id,
                channel_id=e.channel_id,
                user_id=e.user_id,
                event_type=e.type.value,
                sequence=e.sequence,
                payload=e.payload,
                timestamp=e.timestamp,
            )
            for e in events
        ]
        self._session.add_all(models)

    async def get_events(
        self,
        channel_id: str,
        since_sequence: int = 0,
        limit: int = 1000,
    ) -> list[Event]:
        """
        Get events for a channel.

        Args:
            channel_id: Slack channel ID.
            since_sequence: Start from this sequence number.
            limit: Maximum events to return.

        Returns:
            List of events ordered by sequence.
        """
        query = (
            select(EventModel)
            .where(
                and_(
                    EventModel.channel_id == channel_id,
                    EventModel.sequence > since_sequence,
                )
            )
            .order_by(EventModel.sequence)
            .limit(limit)
        )

        result = await self._session.execute(query)
        rows = result.scalars().all()

        return [
            Event(
                id=row.id,
                type=EventType(row.event_type),
                channel_id=row.channel_id,
                user_id=row.user_id,
                sequence=row.sequence,
                payload=row.payload,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    async def get_latest_sequence(self, channel_id: str) -> int:
        """Get the latest sequence number for a channel."""
        query = (
            select(EventModel.sequence)
            .where(EventModel.channel_id == channel_id)
            .order_by(desc(EventModel.sequence))
            .limit(1)
        )

        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        return row or 0

    async def delete_channel_events(self, channel_id: str) -> int:
        """
        Delete all events for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Number of deleted events.
        """
        query = select(EventModel).where(EventModel.channel_id == channel_id)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        count = len(rows)

        for row in rows:
            await self._session.delete(row)

        return count


class GraphRepository:
    """
    Repository for graph snapshots.

    Handles periodic snapshots for faster graph loading.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def save_snapshot(
        self,
        channel_id: str,
        sequence: int,
        graph_data: dict,
    ) -> None:
        """
        Save a graph snapshot.

        Args:
            channel_id: Slack channel ID.
            sequence: Event sequence at snapshot time.
            graph_data: Serialized graph data.
        """
        model = GraphSnapshotModel(
            channel_id=channel_id,
            sequence=sequence,
            graph_data=graph_data,
        )
        self._session.add(model)

    async def get_latest_snapshot(
        self,
        channel_id: str,
    ) -> tuple[int, dict] | None:
        """
        Get the latest snapshot for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Tuple of (sequence, graph_data) or None if no snapshot.
        """
        query = (
            select(GraphSnapshotModel)
            .where(GraphSnapshotModel.channel_id == channel_id)
            .order_by(desc(GraphSnapshotModel.sequence))
            .limit(1)
        )

        result = await self._session.execute(query)
        row = result.scalar_one_or_none()

        if row:
            return (row.sequence, row.graph_data)
        return None

    async def cleanup_old_snapshots(
        self,
        channel_id: str,
        keep_count: int = 5,
    ) -> int:
        """
        Delete old snapshots, keeping only the most recent ones.

        Args:
            channel_id: Slack channel ID.
            keep_count: Number of snapshots to keep.

        Returns:
            Number of deleted snapshots.
        """
        # Get IDs to keep
        keep_query = (
            select(GraphSnapshotModel.id)
            .where(GraphSnapshotModel.channel_id == channel_id)
            .order_by(desc(GraphSnapshotModel.sequence))
            .limit(keep_count)
        )
        keep_result = await self._session.execute(keep_query)
        keep_ids = {row for row in keep_result.scalars().all()}

        # Delete others
        query = select(GraphSnapshotModel).where(
            and_(
                GraphSnapshotModel.channel_id == channel_id,
                ~GraphSnapshotModel.id.in_(keep_ids),
            )
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        count = len(rows)

        for row in rows:
            await self._session.delete(row)

        return count


class ConfigRepository:
    """
    Repository for channel configuration.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def get(self, channel_id: str) -> ChannelConfigModel | None:
        """Get configuration for a channel."""
        query = select(ChannelConfigModel).where(
            ChannelConfigModel.channel_id == channel_id
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def save(
        self,
        channel_id: str,
        jira_project_key: str = "",
        jira_project_id: str = "",
        enabled: bool = True,
        custom_settings: dict | None = None,
    ) -> ChannelConfigModel:
        """Save or update channel configuration."""
        existing = await self.get(channel_id)

        if existing:
            existing.jira_project_key = jira_project_key
            existing.jira_project_id = jira_project_id
            existing.enabled = enabled
            existing.custom_settings = custom_settings or {}
            existing.updated_at = datetime.utcnow()
            return existing
        else:
            model = ChannelConfigModel(
                channel_id=channel_id,
                jira_project_key=jira_project_key,
                jira_project_id=jira_project_id,
                enabled=enabled,
                custom_settings=custom_settings or {},
            )
            self._session.add(model)
            return model

    async def get_all(self) -> list[ChannelConfigModel]:
        """Get all channel configurations."""
        query = select(ChannelConfigModel)
        result = await self._session.execute(query)
        return list(result.scalars().all())


class AuditRepository:
    """
    Repository for audit logs.

    Tracks all user actions for compliance and debugging.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def log(
        self,
        channel_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        """
        Log an audit entry.

        Args:
            channel_id: Slack channel ID.
            user_id: User who performed the action.
            action: Action name (e.g., "create_node", "sync_jira").
            resource_type: Type of resource affected.
            resource_id: ID of the resource.
            details: Additional details.
        """
        model = AuditLogModel(
            channel_id=channel_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
        self._session.add(model)

    async def get_logs(
        self,
        channel_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[AuditLogModel]:
        """
        Get audit logs for a channel.

        Args:
            channel_id: Slack channel ID.
            limit: Maximum logs to return.
            since: Only return logs after this time.

        Returns:
            List of audit log entries.
        """
        conditions = [AuditLogModel.channel_id == channel_id]

        if since:
            conditions.append(AuditLogModel.timestamp > since)

        query = (
            select(AuditLogModel)
            .where(and_(*conditions))
            .order_by(desc(AuditLogModel.timestamp))
            .limit(limit)
        )

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_user_activity(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[AuditLogModel]:
        """Get recent activity for a user."""
        query = (
            select(AuditLogModel)
            .where(AuditLogModel.user_id == user_id)
            .order_by(desc(AuditLogModel.timestamp))
            .limit(limit)
        )

        result = await self._session.execute(query)
        return list(result.scalars().all())

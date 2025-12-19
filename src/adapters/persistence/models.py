"""
SQLAlchemy models for database persistence.

Defines tables for events, graph snapshots, configuration, and audit logs.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Boolean,
    JSON,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class EventModel(Base):
    """
    Event store table.

    Stores all graph mutation events for event sourcing.
    """

    __tablename__ = "events"

    id = Column(String(36), primary_key=True)
    channel_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(50), nullable=False)
    event_type = Column(String(50), nullable=False)
    sequence = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_events_channel_sequence", "channel_id", "sequence"),
    )


class GraphSnapshotModel(Base):
    """
    Graph snapshot table.

    Stores periodic snapshots of graph state for faster loading.
    """

    __tablename__ = "graph_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(50), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)  # Event sequence at snapshot time
    graph_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_snapshots_channel_sequence", "channel_id", "sequence"),
    )


class ChannelConfigModel(Base):
    """
    Channel configuration table.

    Stores per-channel settings including Jira project mapping.
    """

    __tablename__ = "channel_configs"

    channel_id = Column(String(50), primary_key=True)
    jira_project_key = Column(String(20), nullable=True)
    jira_project_id = Column(String(20), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    custom_settings = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLogModel(Base):
    """
    Audit log table.

    Tracks all user actions for compliance and debugging.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)  # node, edge, graph, sync
    resource_id = Column(String(50), nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_audit_channel_timestamp", "channel_id", "timestamp"),
    )


class SyncHistoryModel(Base):
    """
    Sync history table.

    Tracks all sync operations to external trackers.
    """

    __tablename__ = "sync_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(50), nullable=False)
    target_system = Column(String(50), nullable=False)  # jira, github
    project_key = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False)  # success, partial, failed
    synced_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    details = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

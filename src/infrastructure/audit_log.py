"""Intent audit logging for debugging classification decisions.

Records every message classification chain: message -> pregate -> LLM -> mode -> action.
Fire-and-forget writes ensure zero latency impact on message processing.

Usage:
    from src.infrastructure.audit_log import IntentAuditEntry, log_intent_audit

    log_intent_audit(IntentAuditEntry(
        channel_id="C123",
        message_ts="1234567890.123456",
        user_id="U123",
        message_text="create a new work item",
        classified_mode="create",
        classified_confidence=0.95,
    ))
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.infrastructure.database import get_pool

logger = logging.getLogger(__name__)

# Strong reference set to prevent GC of background tasks
_background_tasks: set[asyncio.Task] = set()

# Path to migration SQL
_MIGRATION_SQL_PATH = Path(__file__).parent / "migrations" / "002_intent_audit_log.sql"

INSERT_SQL = """
INSERT INTO intent_audit_log (
    channel_id, thread_ts, message_ts, user_id, message_text,
    pregate_result, pregate_data,
    raw_mode, raw_confidence, classified_mode, classified_confidence,
    entity_type, target_entity_id, entities_mentioned, reasoning,
    classification_ms
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7,
    $8, $9, $10, $11,
    $12, $13, $14, $15,
    $16
)
"""

QUERY_SQL = """
SELECT
    id, created_at,
    channel_id, thread_ts, message_ts, user_id, message_text,
    pregate_result, pregate_data,
    raw_mode, raw_confidence, classified_mode, classified_confidence,
    entity_type, target_entity_id, entities_mentioned, reasoning,
    classification_ms
FROM intent_audit_log
WHERE channel_id = $1
{thread_filter}
{message_filter}
ORDER BY created_at DESC
LIMIT ${{limit_param}}
"""


class IntentAuditEntry(BaseModel):
    """Audit entry for intent classification chain."""

    # Message context
    channel_id: str
    thread_ts: str | None = None
    message_ts: str = ""
    user_id: str = ""
    message_text: str = ""

    # PreGate stage
    pregate_result: str | None = None
    pregate_data: dict[str, Any] | None = None

    # LLM classification stage
    raw_mode: str | None = None
    raw_confidence: float | None = None
    classified_mode: str = "converse"
    classified_confidence: float = 0.0
    entity_type: str | None = None
    target_entity_id: str | None = None
    entities_mentioned: list[str] | None = None
    reasoning: str | None = None

    # Performance
    classification_ms: int | None = None


def log_intent_audit(entry: IntentAuditEntry) -> None:
    """Fire-and-forget audit log write.

    Creates an asyncio.Task to write the entry in the background.
    Uses a strong reference set to prevent garbage collection of the task.
    Never raises -- audit logging must not impact message processing.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_write_audit_entry(entry))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        # No running event loop -- skip audit logging
        logger.debug("No event loop available for audit logging, skipping")


async def _write_audit_entry(entry: IntentAuditEntry) -> None:
    """Write audit entry to database. Never raises."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                INSERT_SQL,
                entry.channel_id,
                entry.thread_ts,
                entry.message_ts,
                entry.user_id,
                entry.message_text,
                entry.pregate_result,
                json.dumps(entry.pregate_data) if entry.pregate_data else None,
                entry.raw_mode,
                entry.raw_confidence,
                entry.classified_mode,
                entry.classified_confidence,
                entry.entity_type,
                entry.target_entity_id,
                json.dumps(entry.entities_mentioned) if entry.entities_mentioned else None,
                entry.reasoning,
                entry.classification_ms,
            )
    except Exception as e:
        logger.warning(f"Failed to write audit log entry: {e}")


async def ensure_audit_table() -> None:
    """Run the migration SQL to create the audit table (idempotent).

    Should be called on app startup. Uses IF NOT EXISTS so it's safe
    to run multiple times.
    """
    try:
        sql = _MIGRATION_SQL_PATH.read_text()
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql)
        logger.info("Intent audit log table ensured")
    except Exception as e:
        logger.warning(f"Failed to ensure audit log table: {e}")


async def query_audit_log(
    channel_id: str,
    thread_ts: str | None = None,
    message_ts: str | None = None,
    limit: int = 50,
) -> list[IntentAuditEntry]:
    """Query audit log entries for debugging.

    Args:
        channel_id: Required channel filter
        thread_ts: Optional thread filter
        message_ts: Optional message timestamp filter
        limit: Maximum entries to return (default 50)

    Returns:
        List of IntentAuditEntry, most recent first
    """
    try:
        pool = await get_pool()

        # Build dynamic query with filters
        params: list[Any] = [channel_id]
        param_idx = 2

        thread_filter = ""
        if thread_ts is not None:
            thread_filter = f"AND thread_ts = ${param_idx}"
            params.append(thread_ts)
            param_idx += 1

        message_filter = ""
        if message_ts is not None:
            message_filter = f"AND message_ts = ${param_idx}"
            params.append(message_ts)
            param_idx += 1

        params.append(limit)

        query = f"""
            SELECT
                channel_id, thread_ts, message_ts, user_id, message_text,
                pregate_result, pregate_data,
                raw_mode, raw_confidence, classified_mode, classified_confidence,
                entity_type, target_entity_id, entities_mentioned, reasoning,
                classification_ms
            FROM intent_audit_log
            WHERE channel_id = $1
            {thread_filter}
            {message_filter}
            ORDER BY created_at DESC
            LIMIT ${param_idx}
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        entries = []
        for row in rows:
            entries.append(IntentAuditEntry(
                channel_id=row["channel_id"],
                thread_ts=row["thread_ts"],
                message_ts=row["message_ts"],
                user_id=row["user_id"],
                message_text=row["message_text"],
                pregate_result=row["pregate_result"],
                pregate_data=json.loads(row["pregate_data"]) if row["pregate_data"] else None,
                raw_mode=row["raw_mode"],
                raw_confidence=row["raw_confidence"],
                classified_mode=row["classified_mode"],
                classified_confidence=row["classified_confidence"],
                entity_type=row["entity_type"],
                target_entity_id=row["target_entity_id"],
                entities_mentioned=json.loads(row["entities_mentioned"]) if row["entities_mentioned"] else None,
                reasoning=row["reasoning"],
                classification_ms=row["classification_ms"],
            ))

        return entries

    except Exception as e:
        logger.warning(f"Failed to query audit log: {e}")
        return []

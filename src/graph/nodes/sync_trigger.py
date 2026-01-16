"""Sync trigger node - handles SYNC_REQUEST intent.

When user says "@Maro update Jira issues" or similar sync phrases,
this node returns action="sync_request" to trigger the sync flow.
"""
import logging
from typing import Any

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def sync_trigger_node(state: AgentState) -> dict[str, Any]:
    """Handle SYNC_REQUEST intent - trigger Jira sync analysis.

    Returns partial state update with decision_result containing:
    - action: "sync_request"
    - channel_id: For the sync engine to know which channel

    The handler will then run SyncEngine.detect_changes() and
    show the sync summary UI.
    """
    channel_id = state.get("channel_id", "")
    thread_ts = state.get("thread_ts")

    logger.info(
        "Sync trigger node processing",
        extra={
            "channel_id": channel_id,
            "thread_ts": thread_ts,
        }
    )

    return {
        "decision_result": {
            "action": "sync_request",
            "channel_id": channel_id,
            "thread_ts": thread_ts,
        }
    }

"""Jira search node - handles JIRA_SEARCH intent.

When user says "check Jira for similar issues" or "do we have a ticket for X",
this node returns action="jira_search" with the search query to trigger search.
"""
import logging
from typing import Any

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def jira_search_node(state: AgentState) -> dict[str, Any]:
    """Handle JIRA_SEARCH intent - search Jira for existing issues.

    Returns partial state update with decision_result containing:
    - action: "jira_search"
    - search_query: The query to search for
    - channel_id: For context
    - thread_ts: For response location

    The handler will then run jira_search skill and display results.
    """
    channel_id = state.get("channel_id", "")
    thread_ts = state.get("thread_ts")

    # Get search query from intent_result
    intent_result = state.get("intent_result", {})
    search_query = intent_result.get("search_query")

    # If no explicit search query, try to extract from conversation context
    if not search_query:
        # Try to get topic from intent or conversation
        conversation_context = state.get("conversation_context", {})
        summary = conversation_context.get("summary", "")
        if summary:
            # Use first 100 chars of summary as fallback
            search_query = summary[:100]
        else:
            # Check recent messages for topic
            messages = conversation_context.get("messages", [])
            for msg in reversed(messages[-5:]):
                text = msg.get("text", "")
                if text and len(text) > 10:
                    search_query = text[:100]
                    break

    logger.info(
        "Jira search node processing",
        extra={
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "search_query": search_query,
        }
    )

    return {
        "decision_result": {
            "action": "jira_search",
            "search_query": search_query,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
        }
    }

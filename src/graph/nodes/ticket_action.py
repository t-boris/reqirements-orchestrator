"""Ticket action node - handles operations on existing tickets.

When user mentions an existing ticket (e.g., "create subtasks for SCRUM-1111"),
this node routes the request to the appropriate handler without going through
the full ticket creation flow.

Supports:
- create_subtask: Create subtasks for existing ticket
- update: Update ticket fields
- add_comment: Add comment to ticket
- link: Link current thread to existing ticket
"""
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def _resolve_ticket_by_name(state: dict, channel_id: str) -> str | None:
    """Resolve ticket from natural language reference in user message.

    Looks for patterns like "Content Layer epic" and matches against
    Jira Registry entries by summary.

    Args:
        state: Current agent state with messages.
        channel_id: Slack channel ID for registry lookup.

    Returns:
        Resolved ticket key or None.
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore
    import re

    # Get latest human message
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not user_message:
        return None

    user_message_lower = user_message.lower()

    # Extract potential name fragment and issue type hint
    # Patterns: "Content Layer epic", "the auth story", "for X epic"
    issue_type_filter = None
    name_fragment = None

    # Check for issue type hints
    if "epic" in user_message_lower:
        issue_type_filter = "epic"
    elif "story" in user_message_lower or "stories" in user_message_lower:
        issue_type_filter = "story"
    elif "task" in user_message_lower:
        issue_type_filter = "task"
    elif "bug" in user_message_lower:
        issue_type_filter = "bug"

    # Extract name fragment - look for phrases before "epic/story/task/bug"
    # e.g., "Content Layer epic" -> "Content Layer"
    patterns = [
        r"for\s+(?:the\s+)?(.+?)\s+(?:epic|story|task|bug)",
        r"(?:the\s+)?(.+?)\s+(?:epic|story|task|bug)",
        r"for\s+(.+?)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_message, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            # Skip generic words
            if candidate.lower() not in ("the", "this", "that", "a", "an"):
                name_fragment = candidate
                break

    if not name_fragment:
        logger.debug("Could not extract name fragment from user message")
        return None

    logger.info(
        "Attempting to resolve ticket by name",
        extra={
            "name_fragment": name_fragment,
            "issue_type_filter": issue_type_filter,
        }
    )

    try:
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)

            # First try to resolve by name if summaries exist
            link = await registry.resolve_by_name(
                channel_id=channel_id,
                name_fragment=name_fragment,
                issue_type_filter=issue_type_filter,
            )

            if link:
                logger.info(
                    "Resolved ticket by name",
                    extra={
                        "name_fragment": name_fragment,
                        "resolved_key": link.jira_key,
                        "resolved_summary": link.summary,
                    }
                )
                return link.jira_key

            # If no match found, try to sync missing summaries from Jira and retry
            issues = await registry.get_channel_issues(channel_id, limit=50)
            missing_summary = [i for i in issues if not i.summary]

            if missing_summary:
                logger.info(f"Syncing {len(missing_summary)} issues with missing summaries")
                await _sync_missing_summaries(registry, missing_summary)

                # Retry resolution after sync
                link = await registry.resolve_by_name(
                    channel_id=channel_id,
                    name_fragment=name_fragment,
                    issue_type_filter=issue_type_filter,
                )
                if link:
                    logger.info(
                        "Resolved ticket by name after sync",
                        extra={
                            "name_fragment": name_fragment,
                            "resolved_key": link.jira_key,
                            "resolved_summary": link.summary,
                        }
                    )
                    return link.jira_key

    except Exception as e:
        logger.warning(f"Failed to resolve ticket by name: {e}")

    return None


async def _sync_missing_summaries(registry: "JiraRegistryStore", issues: list) -> None:
    """Fetch missing summaries from Jira and update registry."""
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    settings = get_settings()
    jira = JiraService(settings)

    try:
        for issue_link in issues:
            try:
                jira_issue = await jira.get_issue(issue_link.jira_key)
                if jira_issue:
                    # Update registry with fetched data
                    await registry.register(
                        channel_id=issue_link.channel_id,
                        jira_key=issue_link.jira_key,
                        link_type=issue_link.link_type,
                        linked_by=issue_link.linked_by,
                        summary=jira_issue.summary,
                        issue_type=jira_issue.issue_type.lower() if jira_issue.issue_type else None,
                    )
                    logger.info(
                        "Synced issue summary from Jira",
                        extra={
                            "jira_key": issue_link.jira_key,
                            "summary": jira_issue.summary[:50] if jira_issue.summary else None,
                            "issue_type": jira_issue.issue_type,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to sync issue {issue_link.jira_key}: {e}")
    finally:
        await jira.close()


async def ticket_action_node(state: AgentState) -> dict[str, Any]:
    """Handle ticket action intent.

    Reads intent_result to get ticket_key and action_type, then sets up
    decision_result for the handler to process.

    If ticket_key is None (contextual reference like "the epic"), resolves
    from thread binding or by name search in Jira Registry.

    Returns partial state update with decision_result containing:
    - action: "ticket_action"
    - ticket_key: The referenced ticket (e.g., "SCRUM-1111")
    - action_type: The operation to perform
    """
    intent_result = state.get("intent_result", {})
    ticket_key = intent_result.get("ticket_key")
    action_type = intent_result.get("action_type")

    # Check thread binding for contextual resolution and re-linking prevention
    thread_ts = state.get("thread_ts")
    channel_id = state.get("channel_id")
    already_bound_to_same = False
    binding = None

    if thread_ts and channel_id:
        from src.slack.thread_bindings import get_binding_store

        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)

        # If ticket_key is None but thread is bound, use the bound ticket
        if not ticket_key and binding:
            ticket_key = binding.issue_key
            logger.info(
                "Resolved ticket_key from thread binding",
                extra={
                    "ticket_key": ticket_key,
                    "action_type": action_type,
                }
            )

        # If still no ticket_key, try to resolve by name from user message
        if not ticket_key and channel_id:
            ticket_key = await _resolve_ticket_by_name(state, channel_id)

        if binding and binding.issue_key == ticket_key:
            # Thread already bound to the SAME ticket - do action, don't re-link
            already_bound_to_same = True
            logger.info(
                "Thread already bound to same ticket",
                extra={
                    "ticket_key": ticket_key,
                    "bound_ticket": binding.issue_key,
                }
            )

    logger.info(
        "Ticket action node processing",
        extra={
            "ticket_key": ticket_key,
            "action_type": action_type,
            "resolved_from_binding": binding is not None and not intent_result.get("ticket_key"),
        }
    )

    # Get latest human message for content extraction
    messages = state.get("messages", [])
    latest_human_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    return {
        "decision_result": {
            "action": "ticket_action",
            "ticket_key": ticket_key,
            "action_type": action_type,
            "already_bound_to_same": already_bound_to_same,
            "user_message": latest_human_message,  # For content extraction
            "review_context": state.get("review_context"),  # Include if available
        }
    }

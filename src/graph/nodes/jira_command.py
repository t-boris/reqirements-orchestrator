"""Jira command node - handles natural language Jira management commands.

When user says something like "change the priority of SCRUM-123 to high",
this node processes the command, resolves contextual targets if needed,
and prepares a confirmation prompt for the user.

Supports:
- update: Change field values (priority, status, assignee, labels, etc.)
- delete: Delete a ticket (requires confirmation)
"""
import logging
from typing import Any, Optional, TYPE_CHECKING

from langchain_core.messages import HumanMessage

from src.schemas.state import AgentState

if TYPE_CHECKING:
    from src.jira.client import JiraService

logger = logging.getLogger(__name__)


# Priority normalization mapping
PRIORITY_NORMALIZATION = {
    "urgent": "Highest",
    "highest": "Highest",
    "high": "High",
    "medium": "Medium",
    "normal": "Medium",
    "low": "Low",
    "lowest": "Lowest",
}

# Status normalization mapping (common variations)
STATUS_NORMALIZATION = {
    "todo": "To Do",
    "to do": "To Do",
    "open": "Open",
    "in progress": "In Progress",
    "inprogress": "In Progress",
    "in-progress": "In Progress",
    "done": "Done",
    "closed": "Done",
    "complete": "Done",
    "completed": "Done",
    "resolved": "Done",
}


def normalize_priority(value: str) -> str:
    """Normalize natural language priority to Jira priority name.

    Args:
        value: User's priority value (e.g., "high", "urgent")

    Returns:
        Jira priority name (e.g., "High", "Highest")
    """
    return PRIORITY_NORMALIZATION.get(value.lower().strip(), value.title())


def normalize_status(value: str, project_statuses: list[str] | None = None) -> str:
    """Normalize natural language status to Jira status name.

    Args:
        value: User's status value (e.g., "done", "in progress")
        project_statuses: Available statuses in the project (optional)

    Returns:
        Jira status name
    """
    value_lower = value.lower().strip().replace("-", " ")

    # First try direct mapping
    if value_lower in STATUS_NORMALIZATION:
        normalized = STATUS_NORMALIZATION[value_lower]

        # If we have project statuses, validate against them
        if project_statuses:
            # Exact match
            if normalized in project_statuses:
                return normalized

            # Case-insensitive match
            for status in project_statuses:
                if status.lower() == normalized.lower():
                    return status

        return normalized

    # Try matching against project statuses directly
    if project_statuses:
        value_clean = value_lower.replace(" ", "")
        for status in project_statuses:
            if status.lower().replace(" ", "") == value_clean:
                return status

    # Return title-cased as fallback
    return value.title()


async def resolve_assignee(slack_mention: str, jira_service: "JiraService") -> Optional[str]:
    """Resolve Slack mention to Jira accountId.

    Args:
        slack_mention: Slack mention like "@john" or "<@U12345>"
        jira_service: JiraService instance

    Returns:
        Jira accountId or None if not found
    """
    # Extract username from mention
    if slack_mention.startswith("<@") and slack_mention.endswith(">"):
        # Slack user ID format: <@U12345>
        # Would need Slack API to get display name, then search Jira
        # For now, return the ID and let Jira try to match
        slack_user_id = slack_mention[2:-1]
        logger.info(f"Slack user ID extracted: {slack_user_id}")
        # TODO: Look up Slack user, get email, search Jira users
        return None

    # Plain username like "@john" or "john"
    username = slack_mention.lstrip("@").strip()

    try:
        # Search Jira users
        response = await jira_service._request(
            "GET",
            "/rest/api/3/user/search",
            params={"query": username, "maxResults": 5},
        )

        if response and len(response) > 0:
            # Return first match's accountId
            return response[0].get("accountId")

    except Exception as e:
        logger.warning(f"Failed to search Jira users for '{username}': {e}")

    return None


async def normalize_field_value(
    field: str,
    value: str,
    jira_service: "JiraService",
    issue_key: str,
) -> str:
    """Normalize natural language field value to Jira-compatible value.

    Args:
        field: Field name (priority, status, assignee, etc.)
        value: User's value
        jira_service: JiraService instance
        issue_key: Issue key for context (status transitions)

    Returns:
        Normalized value for Jira API
    """
    if field == "priority":
        return normalize_priority(value)

    elif field == "status":
        # Get available transitions for this issue
        try:
            response = await jira_service._request(
                "GET",
                f"/rest/api/3/issue/{issue_key}/transitions",
            )
            transitions = response.get("transitions", [])
            available_statuses = [t.get("to", {}).get("name") for t in transitions]
            available_statuses = [s for s in available_statuses if s]  # Filter None

            return normalize_status(value, available_statuses)

        except Exception as e:
            logger.warning(f"Failed to get transitions for {issue_key}: {e}")
            return normalize_status(value)

    elif field == "assignee":
        # Try to resolve to accountId
        account_id = await resolve_assignee(value, jira_service)
        if account_id:
            return account_id
        # Return original if not resolved - will show error in Jira
        return value

    # For other fields, return as-is
    return value


async def _resolve_contextual_target(
    state: AgentState,
    channel_id: str,
    thread_ts: Optional[str],
) -> Optional[str]:
    """Resolve contextual target like 'that ticket' to an actual issue key.

    Resolution priority:
    1. Thread binding (if in thread with linked ticket)
    2. Single tracked issue in channel
    3. Most recently mentioned issue in conversation

    Args:
        state: Current agent state
        channel_id: Slack channel ID
        thread_ts: Thread timestamp if in a thread

    Returns:
        Resolved issue key or None if ambiguous/not found
    """
    # 1. Check thread binding first
    if thread_ts:
        from src.slack.thread_bindings import get_binding_store

        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)

        if binding:
            logger.info(
                "Resolved contextual target from thread binding",
                extra={"issue_key": binding.issue_key},
            )
            return binding.issue_key

    # 2. Check channel tracker for tracked issues
    try:
        from src.db import get_connection
        from src.slack.channel_tracker import ChannelIssueTracker

        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            tracked = await tracker.get_tracked_issues(channel_id)

            if len(tracked) == 1:
                # Single tracked issue - unambiguous
                logger.info(
                    "Resolved contextual target from single tracked issue",
                    extra={"issue_key": tracked[0].issue_key},
                )
                return tracked[0].issue_key
            elif tracked:
                # Multiple tracked - use most recently tracked
                logger.info(
                    "Resolved contextual target from most recent tracked issue",
                    extra={"issue_key": tracked[0].issue_key, "total_tracked": len(tracked)},
                )
                return tracked[0].issue_key

    except Exception as e:
        logger.warning(f"Failed to check channel tracker: {e}")

    # 3. Try to find issue key in recent conversation
    conversation_context = state.get("conversation_context")
    if conversation_context:
        import re
        messages = conversation_context.get("messages", [])

        # Look for issue keys in recent messages (most recent first)
        issue_pattern = r'\b([A-Z][A-Z0-9]+-\d+)\b'
        for msg in reversed(messages[-10:]):
            text = msg.get("text", "")
            matches = re.findall(issue_pattern, text)
            if matches:
                logger.info(
                    "Resolved contextual target from conversation",
                    extra={"issue_key": matches[-1]},
                )
                return matches[-1]

    return None


async def _get_current_field_value(
    issue_key: str,
    field: str,
) -> Optional[str]:
    """Get current value of a field from Jira.

    Args:
        issue_key: Jira issue key
        field: Field name (priority, status, assignee, etc.)

    Returns:
        Current field value or None if not found
    """
    try:
        from src.jira.client import JiraService
        from src.config.settings import get_settings

        settings = get_settings()
        jira_service = JiraService(settings)

        issue = await jira_service.get_issue(issue_key)
        await jira_service.close()

        if field == "priority":
            # Priority is not stored in our JiraIssue model, would need API call
            return None
        elif field == "status":
            return issue.status
        elif field == "assignee":
            return issue.assignee
        elif field == "summary":
            return issue.summary
        elif field == "description":
            return issue.description[:100] + "..." if issue.description and len(issue.description) > 100 else issue.description

        return None

    except Exception as e:
        logger.warning(f"Failed to get current field value: {e}")
        return None


async def jira_command_node(state: AgentState) -> dict[str, Any]:
    """Handle JIRA_COMMAND intent.

    Reads intent_result to get command details, resolves contextual targets
    if needed, and sets up confirmation prompt for the handler.

    Returns partial state update with decision_result containing:
    - action: "jira_command_confirm"
    - command_details: {target, field, old_value, new_value, command_type}
    """
    intent_result = state.get("intent_result", {})
    ticket_key = intent_result.get("ticket_key")
    command_type = intent_result.get("command_type")
    command_field = intent_result.get("command_field")
    command_value = intent_result.get("command_value")
    target_type = intent_result.get("target_type")

    channel_id = state.get("channel_id", "")
    thread_ts = state.get("thread_ts")

    logger.info(
        "Jira command node processing",
        extra={
            "ticket_key": ticket_key,
            "command_type": command_type,
            "command_field": command_field,
            "command_value": command_value,
            "target_type": target_type,
        }
    )

    # Resolve contextual target if needed
    resolved_key = ticket_key
    if target_type == "contextual" or not ticket_key:
        resolved_key = await _resolve_contextual_target(state, channel_id, thread_ts)

        if not resolved_key:
            # Could not resolve - need to ask user
            # Check if we have multiple options to present
            try:
                from src.db import get_connection
                from src.slack.channel_tracker import ChannelIssueTracker

                async with get_connection() as conn:
                    tracker = ChannelIssueTracker(conn)
                    tracked = await tracker.get_tracked_issues(channel_id)

                    if tracked:
                        # Present options to user
                        options = [t.issue_key for t in tracked[:5]]
                        return {
                            "decision_result": {
                                "action": "jira_command_ambiguous",
                                "message": f"Which ticket? {', '.join(options)}",
                                "options": options,
                                "command_type": command_type,
                                "command_field": command_field,
                                "command_value": command_value,
                            }
                        }
            except Exception:
                pass

            # No tracked issues - generic message
            return {
                "decision_result": {
                    "action": "jira_command_ambiguous",
                    "message": "I couldn't determine which ticket you're referring to. Please specify a ticket key like SCRUM-123.",
                    "options": [],
                }
            }

        logger.info(
            "Resolved contextual target",
            extra={"original_key": ticket_key, "resolved_key": resolved_key},
        )

    # Get current field value for the confirmation message
    old_value = None
    if command_type == "update" and command_field:
        old_value = await _get_current_field_value(resolved_key, command_field)

    # Get latest human message for context
    messages = state.get("messages", [])
    latest_human_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    return {
        "decision_result": {
            "action": "jira_command_confirm",
            "command_details": {
                "target": resolved_key,
                "command_type": command_type,
                "field": command_field,
                "old_value": old_value,
                "new_value": command_value,
            },
            "user_message": latest_human_message,
        }
    }

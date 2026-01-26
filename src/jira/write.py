"""Jira write operations - create and update issues.

Contains create_issue, update_issue, add_comment, and create_subtask.
"""
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from src.jira.client import JiraService

from src.jira.types import (
    JiraCreateRequest,
    JiraIssue,
    PRIORITY_MAP,
)

logger = logging.getLogger(__name__)


async def create_issue(
    service: "JiraService",
    request: JiraCreateRequest,
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> JiraIssue:
    """Create a Jira issue.

    Args:
        service: JiraService instance
        request: Issue creation request with all required fields.
        progress_callback: Optional async callback for retry visibility.
            Called as progress_callback(error_type, attempt, max_attempts)

    Returns:
        Created JiraIssue with key, summary, status, and URL.

    Raises:
        JiraAPIError: On API errors.
    """
    # Build API payload
    payload = {
        "fields": {
            "project": {"key": request.project_key},
            "summary": request.summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": request.description}],
                    }
                ],
            },
            "issuetype": {"name": request.issue_type.value},
            "priority": {"name": PRIORITY_MAP[request.priority]},
        }
    }

    # Add optional fields
    if request.labels:
        payload["fields"]["labels"] = request.labels

    if request.epic_key:
        # Get Epic Link custom field (varies by Jira instance)
        epic_link_field = await service._get_epic_link_field()
        if epic_link_field:
            if epic_link_field == "parent":
                # Team-managed projects use parent field with key object
                payload["fields"]["parent"] = {"key": request.epic_key}
            else:
                # Classic projects use custom field with key string
                payload["fields"][epic_link_field] = request.epic_key
            logger.info(f"Using Epic Link field {epic_link_field} = {request.epic_key}")
        else:
            logger.warning(f"Epic Link field not found, story will not be linked to epic {request.epic_key}")

    logger.info(
        "Creating Jira issue",
        extra={
            "project_key": request.project_key,
            "issue_type": request.issue_type.value,
            "priority": request.priority.value,
            "jira_priority": PRIORITY_MAP[request.priority],
            "dry_run": service.settings.jira_dry_run,
            "jira_env": service.settings.jira_env,
        },
    )

    # Dry-run mode: log and return mock issue
    if service.settings.jira_dry_run:
        service._mock_issue_counter += 1
        mock_key = f"{request.project_key}-DRY{service._mock_issue_counter}"
        logger.info(
            "Dry-run mode: would create issue",
            extra={
                "mock_key": mock_key,
                "payload": payload,
            },
        )
        return JiraIssue(
            key=mock_key,
            summary=request.summary,
            status="Open",
            assignee=None,
            base_url=service.base_url,
        )

    # Make API call with progress callback for retry visibility
    response = await service._request(
        "POST",
        "/rest/api/3/issue",
        json_data=payload,
        progress_callback=progress_callback,
    )
    logger.info(f"Create issue response: {response}")

    # Fetch full issue to get all fields
    created_key = response.get("key", "")
    logger.info(f"Fetching created issue: {created_key}")
    issue = await service.get_issue(created_key)
    logger.info(f"Returning issue from create_issue: {issue.key}")
    return issue


async def update_issue(
    service: "JiraService",
    issue_key: str,
    updates: dict[str, Any],
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> JiraIssue:
    """Update a Jira issue with field changes.

    Uses PUT /rest/api/3/issue/{issueIdOrKey} endpoint.

    Args:
        service: JiraService instance
        issue_key: Issue key (e.g., "SCRUM-111")
        updates: Fields to update. Supports:
            - "description": Text (will be converted to ADF)
            - "summary": Plain text
            - "priority": {"name": "High"}
            - "labels": ["label1", "label2"]
        progress_callback: Optional retry visibility callback

    Returns:
        Updated JiraIssue with refreshed fields

    Raises:
        JiraAPIError: On API errors
    """
    logger.info(
        "Updating Jira issue",
        extra={
            "issue_key": issue_key,
            "update_fields": list(updates.keys()),
            "jira_env": service.settings.jira_env,
        },
    )

    # Convert description to ADF if present
    if "description" in updates and isinstance(updates["description"], str):
        updates["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": updates["description"]}],
                }
            ],
        }

    payload = {"fields": updates}

    # Dry-run mode
    if service.settings.jira_dry_run:
        logger.info(
            "Dry-run mode: would update issue",
            extra={"issue_key": issue_key, "payload": payload},
        )
        return await service.get_issue(issue_key)

    await service._request(
        "PUT",
        f"/rest/api/3/issue/{issue_key}",
        json_data=payload,
        progress_callback=progress_callback,
    )

    logger.info(
        "Jira issue updated successfully",
        extra={"issue_key": issue_key},
    )

    # Return refreshed issue
    return await service.get_issue(issue_key)


async def add_comment(
    service: "JiraService",
    issue_key: str,
    comment: str,
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> dict[str, Any]:
    """Add comment to a Jira issue.

    Uses POST /rest/api/3/issue/{issueIdOrKey}/comment endpoint.

    Args:
        service: JiraService instance
        issue_key: Issue key (e.g., "SCRUM-111")
        comment: Comment text (plain text, will be converted to ADF)
        progress_callback: Optional retry visibility callback

    Returns:
        Created comment response with id, author, body, created timestamp

    Raises:
        JiraAPIError: On API errors
    """
    logger.info(
        "Adding comment to Jira issue",
        extra={
            "issue_key": issue_key,
            "comment_length": len(comment),
            "jira_env": service.settings.jira_env,
        },
    )

    # Convert plain text to ADF
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment}],
                }
            ],
        }
    }

    # Dry-run mode
    if service.settings.jira_dry_run:
        logger.info(
            "Dry-run mode: would add comment",
            extra={"issue_key": issue_key, "comment_preview": comment[:100]},
        )
        return {"id": "dry-run", "body": payload["body"]}

    response = await service._request(
        "POST",
        f"/rest/api/3/issue/{issue_key}/comment",
        json_data=payload,
        progress_callback=progress_callback,
    )

    logger.info(
        "Comment added successfully",
        extra={
            "issue_key": issue_key,
            "comment_id": response.get("id"),
        },
    )

    return response


async def create_subtask(
    service: "JiraService",
    parent_key: str,
    summary: str,
    description: str = "",
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> JiraIssue:
    """Create a subtask under parent issue.

    Uses POST /rest/api/3/issue endpoint with parent link and "Sub-task" issue type.

    Args:
        service: JiraService instance
        parent_key: Parent issue key (e.g., "SCRUM-111")
        summary: Subtask summary/title
        description: Subtask description (optional)
        progress_callback: Optional retry visibility callback

    Returns:
        Created subtask JiraIssue

    Raises:
        JiraAPIError: On API errors (including if parent not found or subtasks not allowed)
    """
    # Extract project key from parent key
    project_key = parent_key.split("-")[0]

    logger.info(
        "Creating subtask",
        extra={
            "parent_key": parent_key,
            "project_key": project_key,
            "summary": summary,
            "jira_env": service.settings.jira_env,
        },
    )

    # Build payload
    payload: dict[str, Any] = {
        "fields": {
            "project": {"key": project_key},
            "parent": {"key": parent_key},
            "summary": summary,
            "issuetype": {"name": "Sub-task"},
        }
    }

    # Add description if provided
    if description:
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        }

    # Dry-run mode
    if service.settings.jira_dry_run:
        service._mock_issue_counter += 1
        mock_key = f"{project_key}-DRY{service._mock_issue_counter}"
        logger.info(
            "Dry-run mode: would create subtask",
            extra={"mock_key": mock_key, "parent_key": parent_key, "summary": summary},
        )
        return JiraIssue(
            key=mock_key,
            summary=summary,
            status="Open",
            assignee=None,
            base_url=service.base_url,
        )

    response = await service._request(
        "POST",
        "/rest/api/3/issue",
        json_data=payload,
        progress_callback=progress_callback,
    )

    created_key = response.get("key", "")
    logger.info(
        "Subtask created successfully",
        extra={
            "subtask_key": created_key,
            "parent_key": parent_key,
        },
    )

    return await service.get_issue(created_key)

"""Jira read operations - get issue details.

Contains get_issue and related helpers for fetching issue data.
"""
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.jira.client import JiraService

from src.jira.types import JiraIssue

logger = logging.getLogger(__name__)


async def get_issue(service: "JiraService", key: str) -> JiraIssue:
    """Get a single Jira issue by key.

    Args:
        service: JiraService instance
        key: Issue key (e.g., PROJ-123).

    Returns:
        JiraIssue with full details.

    Raises:
        JiraAPIError: On API errors (including 404 if not found).
    """
    logger.info(
        "Getting Jira issue",
        extra={
            "key": key,
            "jira_env": service.settings.jira_env,
        },
    )

    response = await service._request(
        "GET",
        f"/rest/api/3/issue/{key}",
        params={"fields": "key,summary,status,assignee,description"},
    )

    try:
        fields = response.get("fields", {})
        assignee = fields.get("assignee")
        # Handle various assignee formats
        if assignee and isinstance(assignee, dict):
            assignee_name = assignee.get("displayName")
        else:
            assignee_name = None
        status = fields.get("status", {}).get("name", "Unknown")

        # Parse description from ADF to plain text
        description_adf = fields.get("description")
        description_text = service._adf_to_text(description_adf) if description_adf else None

        issue = JiraIssue(
            key=response.get("key", key),
            summary=fields.get("summary", ""),
            status=status,
            assignee=assignee_name,
            description=description_text,
            base_url=service.base_url,
        )
        logger.info(f"Built JiraIssue: key={issue.key}, url={issue.url}")
        return issue
    except Exception as e:
        logger.error(f"Failed to parse Jira response: {e}, response={response}")
        raise

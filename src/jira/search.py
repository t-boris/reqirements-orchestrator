"""Jira search operations - search issues using JQL.

Contains search_issues and related helpers.
"""
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.jira.client import JiraService

from src.jira.types import JiraIssue
from src.jira.helpers import format_updated_time

logger = logging.getLogger(__name__)


async def search_issues(service: "JiraService", jql: str, limit: int = 5) -> list[JiraIssue]:
    """Search for Jira issues using JQL.

    Args:
        service: JiraService instance
        jql: Jira Query Language search string.
        limit: Maximum number of results (default 5).

    Returns:
        List of matching JiraIssue objects.

    Raises:
        JiraAPIError: On API errors.
    """
    start_time = time.monotonic()

    logger.info(
        "Searching Jira issues",
        extra={
            "jql": jql,
            "limit": limit,
            "jira_env": service.settings.jira_env,
        },
    )

    # Use new /search/jql endpoint (old /search was removed in 2024)
    payload = {
        "jql": jql,
        "maxResults": limit,
        "fields": ["key", "summary", "status", "assignee", "updated"],
    }

    response = await service._request("POST", "/rest/api/3/search/jql", json_data=payload)

    issues = []
    for item in response.get("issues", []):
        fields = item.get("fields", {})
        assignee = fields.get("assignee")
        assignee_name = assignee.get("displayName") if assignee else None
        status = fields.get("status", {}).get("name", "Unknown")
        updated_raw = fields.get("updated", "")
        updated = format_updated_time(updated_raw) if updated_raw else None

        issues.append(
            JiraIssue(
                key=item.get("key", ""),
                summary=fields.get("summary", ""),
                status=status,
                assignee=assignee_name,
                updated=updated,
                base_url=service.base_url,
            )
        )

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "Jira search complete",
        extra={
            "jql": jql,
            "result_count": len(issues),
            "duration_ms": round(duration_ms, 2),
        },
    )

    return issues

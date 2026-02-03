"""Jira API client wrapper with async support."""

import asyncio
import logging
from typing import Any

from atlassian import Jira
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when Jira returns 429."""
    pass


class JiraClient:
    """Async wrapper for Jira API.

    Uses atlassian-python-api with asyncio.to_thread() for async compatibility.
    Implements exponential backoff for rate limits (429 responses).
    """

    def __init__(self, url: str, email: str, token: str):
        """Initialize Jira client.

        Args:
            url: Jira instance URL (e.g., https://your-instance.atlassian.net)
            email: User email for authentication
            token: API token (not password)
        """
        self._jira = Jira(url=url, username=email, password=token)
        self._field_map: dict[str, str] | None = None

    async def _call_with_retry(self, func, *args, **kwargs) -> Any:
        """Call Jira API with retry on rate limit."""
        return await self._retry_impl(func, *args, **kwargs)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        retry=retry_if_exception_type(RateLimitError),
    )
    async def _retry_impl(self, func, *args, **kwargs) -> Any:
        """Retry implementation with exponential backoff."""
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as e:
            # Check for 429 in various ways atlassian-python-api might report it
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                logger.warning(f"Rate limited, will retry: {e}")
                raise RateLimitError(str(e))
            raise

    async def get_field_map(self) -> dict[str, str]:
        """Get field name to ID mapping (cached)."""
        if self._field_map is None:
            fields = await self._call_with_retry(self._jira.fields)
            self._field_map = {f["name"]: f["id"] for f in fields}
        return self._field_map

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str | None = None,
        **extra_fields,
    ) -> str:
        """Create Jira issue.

        Args:
            project_key: Project key (e.g., "PROJ")
            summary: Issue summary/title
            issue_type: Issue type name (Task, Story, Bug, etc.)
            description: Issue description (optional)
            **extra_fields: Additional fields to set

        Returns:
            Created issue key (e.g., "PROJ-123")
        """
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }

        if description:
            fields["description"] = description

        fields.update(extra_fields)

        result = await self._call_with_retry(
            self._jira.create_issue,
            fields=fields
        )

        key = result["key"]
        logger.info(f"Created Jira issue: {key}")
        return key

    async def get_issue(self, key: str) -> dict[str, Any]:
        """Get issue by key.

        Args:
            key: Issue key (e.g., "PROJ-123")

        Returns:
            Issue data dict with "key", "fields", etc.
        """
        return await self._call_with_retry(self._jira.issue, key)

    async def update_issue(
        self,
        key: str,
        fields: dict[str, Any],
        notify_users: bool = True,
    ) -> None:
        """Update issue fields.

        Args:
            key: Issue key
            fields: Fields to update
            notify_users: Whether to notify watchers
        """
        await self._call_with_retry(
            self._jira.update_issue_field,
            key,
            fields,
            notify_users=notify_users,
        )
        logger.info(f"Updated Jira issue: {key}")

    async def add_comment(self, key: str, comment: str) -> None:
        """Add comment to issue.

        Args:
            key: Issue key
            comment: Comment text
        """
        await self._call_with_retry(
            self._jira.issue_add_comment,
            key,
            comment,
        )
        logger.info(f"Added comment to {key}")

    async def search(
        self,
        jql: str,
        max_results: int = 50,
        fields: str = "*all",
    ) -> list[dict[str, Any]]:
        """Search issues with JQL.

        Args:
            jql: JQL query string
            max_results: Maximum results to return
            fields: Fields to include

        Returns:
            List of matching issues
        """
        result = await self._call_with_retry(
            self._jira.jql,
            jql,
            limit=max_results,
            fields=fields,
        )
        return result.get("issues", [])

    async def search_duplicates(
        self,
        project_key: str,
        summary: str,
    ) -> list[str]:
        """Search for potential duplicate issues by summary.

        Args:
            project_key: Project to search in
            summary: Summary text to match

        Returns:
            List of potentially duplicate issue keys
        """
        # Escape special JQL characters in summary
        escaped = summary.replace('"', '\\"')
        jql = f'project = {project_key} AND summary ~ "{escaped}"'

        issues = await self.search(jql, max_results=5, fields="key,summary")
        return [issue["key"] for issue in issues]

"""Jira API client service with retry, backoff, and dry-run support.

This is a thin wrapper that delegates to specialized modules:
- read.py: get_issue operations
- write.py: create_issue, update_issue, add_comment, create_subtask
- search.py: search_issues
- validation.py: validate_issue_dry_run
"""
import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from src.config.settings import Settings
from src.jira.exceptions import JiraAPIError
from src.jira.types import (
    JiraCreateRequest,
    JiraIssue,
)

# Re-export JiraAPIError for backward compatibility
__all__ = ["JiraService", "JiraAPIError"]

logger = logging.getLogger(__name__)


class JiraService:
    """Service for interacting with Jira API.

    Provides policy-level operations (not just a library wrapper):
    - Retry with exponential backoff on transient failures
    - Dry-run mode for testing without API calls
    - Structured logging for all operations
    - Environment-aware configuration

    Operations are delegated to specialized modules:
    - read.py: get_issue
    - write.py: create_issue, update_issue, add_comment, create_subtask
    - search.py: search_issues
    - validation.py: validate_issue_dry_run
    """

    def __init__(self, settings: Settings):
        """Initialize JiraService.

        Args:
            settings: Application settings containing Jira configuration.
        """
        self.settings = settings
        self.base_url = settings.jira_url.rstrip("/")
        self.auth = aiohttp.BasicAuth(settings.jira_user, settings.jira_api_token)
        self._session: Optional[aiohttp.ClientSession] = None
        self._mock_issue_counter = 0
        self._epic_link_field: Optional[str] = None  # Cached Epic Link field ID

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.jira_timeout)
            self._session = aiohttp.ClientSession(
                auth=self.auth,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get_epic_link_field(self) -> Optional[str]:
        """Get the Epic Link custom field ID.

        Jira Cloud uses different methods for linking issues to epics:
        - Classic (company-managed) projects: Epic Link custom field
        - Next-gen (team-managed) projects: parent field

        Returns:
            Custom field ID (e.g., "customfield_10014") or "parent" for next-gen projects
        """
        if self._epic_link_field is not None:
            return self._epic_link_field if self._epic_link_field else None

        try:
            fields = await self._request("GET", "/rest/api/3/field")
            for field in fields:
                # Look for Epic Link field by name or schema
                name = field.get("name", "").lower()
                schema = field.get("schema", {})

                if "epic link" in name or (
                    schema.get("type") == "any" and "epic" in name
                ):
                    self._epic_link_field = field.get("id")
                    logger.info(f"Discovered Epic Link field: {self._epic_link_field}")
                    return self._epic_link_field

            # No Epic Link field found - use parent field (team-managed projects)
            logger.info("No Epic Link custom field found, using parent field for team-managed project")
            self._epic_link_field = "parent"
            return "parent"
        except Exception as e:
            logger.warning(f"Failed to discover Epic Link field: {e}")
            self._epic_link_field = ""
            return None

    def _adf_to_text(self, adf: dict) -> str:
        """Convert Atlassian Document Format (ADF) to plain text.

        ADF is a JSON format used by Jira for rich text content.
        This extracts plain text recursively from the document tree.

        Args:
            adf: ADF document dict

        Returns:
            Plain text representation
        """
        if not adf or not isinstance(adf, dict):
            return ""

        text_parts = []

        def extract_text(node):
            if not isinstance(node, dict):
                return

            # Text node
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
                return

            # Recursively process content
            content = node.get("content", [])
            for child in content:
                extract_text(child)

            # Add newlines for block elements
            node_type = node.get("type", "")
            if node_type in ("paragraph", "heading", "bulletList", "orderedList", "listItem"):
                text_parts.append("\n")

        extract_text(adf)
        return "".join(text_parts).strip()

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """Make HTTP request with retry and exponential backoff.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /rest/api/3/issue)
            json_data: JSON body for POST/PUT requests
            params: Query parameters
            progress_callback: Optional async callback for retry visibility.
                Called as progress_callback(error_type, attempt, max_attempts)
                where error_type is one of: "timeout", "api_error", "rate_limit"

        Returns:
            Response JSON as dict

        Raises:
            JiraAPIError: On 4xx client errors (no retry)
            JiraAPIError: On 5xx server errors after all retries exhausted
        """
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()

        last_error: Optional[Exception] = None
        max_retries = self.settings.jira_max_retries

        for attempt in range(max_retries + 1):
            start_time = time.monotonic()
            try:
                logger.debug(
                    "Jira API request",
                    extra={
                        "method": method,
                        "url": url,
                        "attempt": attempt + 1,
                        "jira_env": self.settings.jira_env,
                    },
                )

                async with session.request(
                    method, url, json=json_data, params=params
                ) as response:
                    duration_ms = (time.monotonic() - start_time) * 1000
                    # Always try to parse JSON - content_length can be None with chunked encoding
                    try:
                        response_body = await response.json()
                    except Exception:
                        response_body = {}

                    logger.info(
                        "Jira API response",
                        extra={
                            "method": method,
                            "url": url,
                            "status": response.status,
                            "duration_ms": round(duration_ms, 2),
                            "jira_env": self.settings.jira_env,
                        },
                    )

                    # 2xx: Success
                    if 200 <= response.status < 300:
                        return response_body

                    # 4xx: Client error - don't retry
                    if 400 <= response.status < 500:
                        # Jira returns errors in both errorMessages (list) and errors (dict)
                        error_messages = response_body.get("errorMessages", [])
                        errors_dict = response_body.get("errors", {})
                        combined = error_messages + [f"{k}: {v}" for k, v in errors_dict.items()]
                        error_msg = combined if combined else [response.reason]
                        raise JiraAPIError(
                            status_code=response.status,
                            message=str(error_msg),
                            response_body=response_body,
                        )

                    # 429: Rate limited - notify and retry
                    if response.status == 429:
                        if progress_callback:
                            await progress_callback("rate_limit", attempt + 1, max_retries + 1)
                        last_error = JiraAPIError(
                            status_code=response.status,
                            message="Rate limited",
                            response_body=response_body,
                        )
                        if attempt < max_retries:
                            # Use Retry-After header if present, else exponential backoff
                            retry_after = response.headers.get("Retry-After")
                            backoff = int(retry_after) if retry_after else 2 ** attempt * 5
                            logger.warning(
                                f"Jira API rate limited, retrying in {backoff}s",
                                extra={
                                    "attempt": attempt + 1,
                                    "backoff_seconds": backoff,
                                },
                            )
                            await asyncio.sleep(backoff)
                            continue
                        raise last_error

                    # 5xx: Server error - retry with backoff
                    if response.status >= 500:
                        if progress_callback:
                            await progress_callback("api_error", attempt + 1, max_retries + 1)
                        last_error = JiraAPIError(
                            status_code=response.status,
                            message=response.reason or "Server error",
                            response_body=response_body,
                        )
                        if attempt < max_retries:
                            backoff = 2**attempt  # Exponential backoff: 1s, 2s, 4s...
                            logger.warning(
                                f"Jira API 5xx error, retrying in {backoff}s",
                                extra={
                                    "status": response.status,
                                    "attempt": attempt + 1,
                                    "backoff_seconds": backoff,
                                },
                            )
                            await asyncio.sleep(backoff)
                            continue
                        raise last_error

            except asyncio.TimeoutError:
                duration_ms = (time.monotonic() - start_time) * 1000
                last_error = asyncio.TimeoutError(f"Request timed out after {duration_ms}ms")
                if progress_callback:
                    await progress_callback("timeout", attempt + 1, max_retries + 1)
                logger.warning(
                    "Jira API timeout",
                    extra={
                        "method": method,
                        "url": url,
                        "attempt": attempt + 1,
                        "duration_ms": round(duration_ms, 2),
                    },
                )
                if attempt < max_retries:
                    backoff = 5 * (attempt + 1)  # Linear backoff for timeouts: 5s, 10s, 15s
                    await asyncio.sleep(backoff)
                    continue

            except aiohttp.ClientError as e:
                duration_ms = (time.monotonic() - start_time) * 1000
                last_error = e
                if progress_callback:
                    await progress_callback("api_error", attempt + 1, max_retries + 1)
                logger.warning(
                    f"Jira API connection error: {e}",
                    extra={
                        "method": method,
                        "url": url,
                        "attempt": attempt + 1,
                        "duration_ms": round(duration_ms, 2),
                        "error": str(e),
                    },
                )
                if attempt < max_retries:
                    backoff = 2**attempt
                    await asyncio.sleep(backoff)
                    continue

        # All retries exhausted
        if isinstance(last_error, JiraAPIError):
            raise last_error
        raise JiraAPIError(
            status_code=0,
            message=f"Request failed after {max_retries + 1} attempts: {last_error}",
        )

    # -------------------------------------------------------------------------
    # Delegated operations - thin wrappers that delegate to modules
    # -------------------------------------------------------------------------

    async def get_issue(self, key: str) -> JiraIssue:
        """Get a single Jira issue by key. Delegates to read module."""
        from src.jira.read import get_issue
        return await get_issue(self, key)

    async def create_issue(
        self,
        request: JiraCreateRequest,
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> JiraIssue:
        """Create a Jira issue. Delegates to write module."""
        from src.jira.write import create_issue
        return await create_issue(self, request, progress_callback)

    async def update_issue(
        self,
        issue_key: str,
        updates: dict[str, Any],
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> JiraIssue:
        """Update a Jira issue. Delegates to write module."""
        from src.jira.write import update_issue
        return await update_issue(self, issue_key, updates, progress_callback)

    async def add_comment(
        self,
        issue_key: str,
        comment: str,
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """Add comment to a Jira issue. Delegates to write module."""
        from src.jira.write import add_comment
        return await add_comment(self, issue_key, comment, progress_callback)

    async def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str = "",
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> JiraIssue:
        """Create a subtask under parent issue. Delegates to write module."""
        from src.jira.write import create_subtask
        return await create_subtask(self, parent_key, summary, description, progress_callback)

    async def search_issues(self, jql: str, limit: int = 5) -> list[JiraIssue]:
        """Search for Jira issues using JQL. Delegates to search module."""
        from src.jira.search import search_issues
        return await search_issues(self, jql, limit)

    async def validate_issue_dry_run(
        self,
        project_key: str,
        issue_type: str,
        fields: dict,
    ) -> dict:
        """Validate issue creation without actually creating. Delegates to validation module."""
        from src.jira.validation import validate_issue_dry_run
        return await validate_issue_dry_run(self, project_key, issue_type, fields)

"""Jira API client service with retry, backoff, and dry-run support."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from src.config.settings import Settings
from src.jira.types import (
    JiraCreateRequest,
    JiraIssue,
    PRIORITY_MAP,
)


def _format_updated_time(iso_timestamp: str) -> str:
    """Format Jira updated timestamp to relative time string.

    Args:
        iso_timestamp: ISO 8601 timestamp from Jira (e.g., "2026-01-15T10:30:00.000+0000")

    Returns:
        Human-readable relative time (e.g., "3 days ago", "2 hours ago")
    """
    try:
        # Parse ISO timestamp - Jira uses format like "2026-01-15T10:30:00.000+0000"
        # Remove milliseconds and normalize timezone
        ts = iso_timestamp.replace("+0000", "+00:00").replace("Z", "+00:00")
        if "." in ts:
            # Remove milliseconds
            ts = ts.split(".")[0] + ts[-6:] if "+" in ts else ts.split(".")[0]

        updated_dt = datetime.fromisoformat(ts.replace("+00:00", "")).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - updated_dt

        if delta.days > 30:
            months = delta.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "just now"
    except Exception:
        # Return raw timestamp if parsing fails
        return iso_timestamp[:10] if len(iso_timestamp) > 10 else iso_timestamp


logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class JiraAPIError(Exception):
    """Exception for Jira API errors."""

    def __init__(
        self,
        status_code: int,
        message: str,
        response_body: Optional[dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"Jira API error {status_code}: {message}")


# =============================================================================
# Jira Service
# =============================================================================


class JiraService:
    """Service for interacting with Jira API.

    Provides policy-level operations (not just a library wrapper):
    - Retry with exponential backoff on transient failures
    - Dry-run mode for testing without API calls
    - Structured logging for all operations
    - Environment-aware configuration

    Sections:
    - Core: init, session, close, _request
    - CRUD: create_issue, search_issues, get_issue
    - Operations (Phase 16): update_issue, add_comment, create_subtask
    """

    # -------------------------------------------------------------------------
    # Core: Initialization and HTTP request handling
    # -------------------------------------------------------------------------

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
                        error_msg = response_body.get("errorMessages", [response.reason])
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
    # CRUD: Create, Read, Search operations
    # -------------------------------------------------------------------------

    async def create_issue(
        self,
        request: JiraCreateRequest,
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> JiraIssue:
        """Create a Jira issue.

        Args:
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
            # Epic link field (may vary by Jira configuration)
            payload["fields"]["parent"] = {"key": request.epic_key}

        logger.info(
            "Creating Jira issue",
            extra={
                "project_key": request.project_key,
                "issue_type": request.issue_type.value,
                "priority": request.priority.value,
                "jira_priority": PRIORITY_MAP[request.priority],
                "dry_run": self.settings.jira_dry_run,
                "jira_env": self.settings.jira_env,
            },
        )

        # Dry-run mode: log and return mock issue
        if self.settings.jira_dry_run:
            self._mock_issue_counter += 1
            mock_key = f"{request.project_key}-DRY{self._mock_issue_counter}"
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
                base_url=self.base_url,
            )

        # Make API call with progress callback for retry visibility
        response = await self._request(
            "POST",
            "/rest/api/3/issue",
            json_data=payload,
            progress_callback=progress_callback,
        )
        logger.info(f"Create issue response: {response}")

        # Fetch full issue to get all fields
        created_key = response.get("key", "")
        logger.info(f"Fetching created issue: {created_key}")
        issue = await self.get_issue(created_key)
        logger.info(f"Returning issue from create_issue: {issue.key}")
        return issue

    async def search_issues(self, jql: str, limit: int = 5) -> list[JiraIssue]:
        """Search for Jira issues using JQL.

        Args:
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
                "jira_env": self.settings.jira_env,
            },
        )

        # Use new /search/jql endpoint (old /search was removed in 2024)
        payload = {
            "jql": jql,
            "maxResults": limit,
            "fields": ["key", "summary", "status", "assignee", "updated"],
        }

        response = await self._request("POST", "/rest/api/3/search/jql", json_data=payload)

        issues = []
        for item in response.get("issues", []):
            fields = item.get("fields", {})
            assignee = fields.get("assignee")
            assignee_name = assignee.get("displayName") if assignee else None
            status = fields.get("status", {}).get("name", "Unknown")
            updated_raw = fields.get("updated", "")
            updated = _format_updated_time(updated_raw) if updated_raw else None

            issues.append(
                JiraIssue(
                    key=item.get("key", ""),
                    summary=fields.get("summary", ""),
                    status=status,
                    assignee=assignee_name,
                    updated=updated,
                    base_url=self.base_url,
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

    async def get_issue(self, key: str) -> JiraIssue:
        """Get a single Jira issue by key.

        Args:
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
                "jira_env": self.settings.jira_env,
            },
        )

        response = await self._request(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={"fields": "key,summary,status,assignee"},
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

            issue = JiraIssue(
                key=response.get("key", key),
                summary=fields.get("summary", ""),
                status=status,
                assignee=assignee_name,
                base_url=self.base_url,
            )
            logger.info(f"Built JiraIssue: key={issue.key}, url={issue.url}")
            return issue
        except Exception as e:
            logger.error(f"Failed to parse Jira response: {e}, response={response}")
            raise

    # -------------------------------------------------------------------------
    # Operations (Phase 16): Update, comment, subtask
    # -------------------------------------------------------------------------

    async def update_issue(
        self,
        issue_key: str,
        updates: dict[str, Any],
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> JiraIssue:
        """Update a Jira issue with field changes.

        Uses PUT /rest/api/3/issue/{issueIdOrKey} endpoint.

        Args:
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
                "jira_env": self.settings.jira_env,
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
        if self.settings.jira_dry_run:
            logger.info(
                "Dry-run mode: would update issue",
                extra={"issue_key": issue_key, "payload": payload},
            )
            return await self.get_issue(issue_key)

        await self._request(
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
        return await self.get_issue(issue_key)

    async def add_comment(
        self,
        issue_key: str,
        comment: str,
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """Add comment to a Jira issue.

        Uses POST /rest/api/3/issue/{issueIdOrKey}/comment endpoint.

        Args:
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
                "jira_env": self.settings.jira_env,
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
        if self.settings.jira_dry_run:
            logger.info(
                "Dry-run mode: would add comment",
                extra={"issue_key": issue_key, "comment_preview": comment[:100]},
            )
            return {"id": "dry-run", "body": payload["body"]}

        response = await self._request(
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

    # -------------------------------------------------------------------------
    # Validation (Phase 20): Dry-run validation for multi-ticket batch creation
    # -------------------------------------------------------------------------

    async def _get_project(self, project_key: str) -> Optional[dict[str, Any]]:
        """Get project by key, or None if not found/no access.

        Args:
            project_key: Jira project key (e.g., "PROJ")

        Returns:
            Project dict with id, key, name, or None if not found
        """
        try:
            response = await self._request("GET", f"/rest/api/3/project/{project_key}")
            return response
        except JiraAPIError as e:
            if e.status_code == 404:
                return None
            raise

    async def _get_issue_types(self, project_key: str) -> list[dict[str, Any]]:
        """Get available issue types for a project.

        Args:
            project_key: Jira project key

        Returns:
            List of issue type dicts with id, name, subtask flag
        """
        response = await self._request(
            "GET",
            f"/rest/api/3/issue/createmeta/{project_key}/issuetypes",
        )
        return response.get("issueTypes", response.get("values", []))

    async def _get_required_fields(
        self, project_key: str, issue_type: str
    ) -> list[str]:
        """Get required fields for creating an issue type in a project.

        Args:
            project_key: Jira project key
            issue_type: Issue type name (e.g., "Epic", "Story")

        Returns:
            List of required field names
        """
        # First get issue type ID
        issue_types = await self._get_issue_types(project_key)
        issue_type_id = None
        for it in issue_types:
            if it.get("name") == issue_type:
                issue_type_id = it.get("id")
                break

        if not issue_type_id:
            return ["summary"]  # Default to just summary if type not found

        # Get fields for this issue type
        try:
            response = await self._request(
                "GET",
                f"/rest/api/3/issue/createmeta/{project_key}/issuetypes/{issue_type_id}",
            )
            fields = response.get("fields", response.get("values", []))
            required = []
            for field in fields:
                if isinstance(field, dict) and field.get("required"):
                    required.append(field.get("fieldId") or field.get("key", ""))
            return required if required else ["summary"]
        except JiraAPIError:
            return ["summary"]  # Default on error

    async def validate_issue_dry_run(
        self,
        project_key: str,
        issue_type: str,
        fields: dict,
    ) -> dict:
        """Validate issue creation without actually creating.

        Checks:
        - Project exists and user has access
        - Issue type valid for project
        - Required fields present
        - Field values valid

        Args:
            project_key: Jira project key (e.g., "PROJ")
            issue_type: Issue type name (e.g., "Epic", "Story")
            fields: Field values to validate (e.g., {"summary": "Title", "description": "..."})

        Returns:
            {"valid": True} or {"valid": False, "errors": [...]}
        """
        errors = []

        # Check project access
        project = await self._get_project(project_key)
        if not project:
            errors.append(f"Project {project_key} not found or no access")
            return {"valid": False, "errors": errors}

        # Check issue type valid
        valid_types = await self._get_issue_types(project_key)
        type_names = [t.get("name") for t in valid_types]
        if issue_type not in type_names:
            errors.append(
                f"Issue type '{issue_type}' not valid for project {project_key}. "
                f"Available types: {', '.join(type_names)}"
            )

        # Check required fields
        required = await self._get_required_fields(project_key, issue_type)
        for field in required:
            # Map common field names
            field_key = field
            if field == "summary":
                field_key = "summary"
            elif field == "description":
                field_key = "description"

            if field_key not in fields or not fields[field_key]:
                errors.append(f"Required field '{field}' is missing")

        if errors:
            return {"valid": False, "errors": errors}

        return {"valid": True}

    async def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str = "",
        progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
    ) -> JiraIssue:
        """Create a subtask under parent issue.

        Uses POST /rest/api/3/issue endpoint with parent link and "Sub-task" issue type.

        Args:
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
                "jira_env": self.settings.jira_env,
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
        if self.settings.jira_dry_run:
            self._mock_issue_counter += 1
            mock_key = f"{project_key}-DRY{self._mock_issue_counter}"
            logger.info(
                "Dry-run mode: would create subtask",
                extra={"mock_key": mock_key, "parent_key": parent_key, "summary": summary},
            )
            return JiraIssue(
                key=mock_key,
                summary=summary,
                status="Open",
                assignee=None,
                base_url=self.base_url,
            )

        response = await self._request(
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

        return await self.get_issue(created_key)

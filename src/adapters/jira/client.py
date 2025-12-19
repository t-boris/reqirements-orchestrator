"""
Jira Client - REST API implementation of IssueTrackerProtocol.

Handles all communication with Jira Cloud/Server.
"""

import structlog
from typing import Any

from atlassian import Jira

from src.adapters.jira.protocol import (
    IssueTrackerProtocol,
    ExternalIssue,
    CreateIssueRequest,
    LinkIssuesRequest,
)
from src.adapters.jira.rate_limiter import LeakyBucketRateLimiter
from src.config.settings import Settings

logger = structlog.get_logger()


# Mapping from MARO node types to Jira issue types
NODE_TYPE_TO_JIRA = {
    "goal": "Initiative",  # Or Theme, depending on Jira config
    "epic": "Epic",
    "story": "Story",
    "subtask": "Sub-task",
    "component": "Task",  # Components are tracked as Tasks
    "constraint": "Task",  # NFRs as Tasks with label
    "risk": "Bug",  # Risks as potential bugs
    "question": "Task",  # Questions as Tasks
}

# Mapping from MARO edge types to Jira link types
EDGE_TYPE_TO_JIRA_LINK = {
    "depends_on": "Blocks",  # Inverse: is blocked by
    "decomposes_to": "Epic-Story Link",
    "requires_component": "Relates",
    "constrained_by": "Relates",
    "conflicts_with": "Problem/Incident",
    "mitigates": "Relates",
    "blocks": "Blocks",
}


class JiraClient(IssueTrackerProtocol):
    """
    Jira REST API client.

    Implements IssueTrackerProtocol for Jira Cloud and Server.
    Uses atlassian-python-api for communication.
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter: LeakyBucketRateLimiter | None = None,
    ) -> None:
        """
        Initialize Jira client.

        Args:
            settings: Application settings with Jira credentials.
            rate_limiter: Optional rate limiter for API calls.
        """
        self._jira = Jira(
            url=settings.jira_url,
            username=settings.jira_user,
            password=settings.jira_api_token,
            cloud=True,  # Assume Jira Cloud
        )
        self._rate_limiter = rate_limiter or LeakyBucketRateLimiter(
            tokens_per_second=settings.rate_limit_tokens_per_second,
        )
        self._settings = settings

        logger.info("jira_client_initialized", url=settings.jira_url)

    @property
    def tracker_name(self) -> str:
        """Return tracker name."""
        return "jira"

    async def create_issue(self, request: CreateIssueRequest) -> ExternalIssue:
        """
        Create a new Jira issue.

        Args:
            request: Issue creation request.

        Returns:
            Created issue with Jira key and URL.
        """
        await self._rate_limiter.acquire()

        # Map issue type
        jira_type = NODE_TYPE_TO_JIRA.get(request.issue_type, "Task")

        # Build description with acceptance criteria
        description = request.description
        if request.acceptance_criteria:
            ac_text = "\n".join([f"* {ac}" for ac in request.acceptance_criteria])
            description += f"\n\nh3. Acceptance Criteria\n{ac_text}"

        # Build fields
        fields = {
            "project": {"key": request.project_key},
            "summary": request.title,
            "description": description,
            "issuetype": {"name": jira_type},
        }

        # Add parent for sub-tasks and epic link for stories
        if request.parent_id:
            if jira_type == "Sub-task":
                fields["parent"] = {"key": request.parent_id}
            elif jira_type == "Story":
                # Epic link field - may vary by Jira config
                fields["customfield_10014"] = request.parent_id

        # Add labels
        if request.labels:
            fields["labels"] = request.labels

        # Add custom fields
        if request.custom_fields:
            fields.update(request.custom_fields)

        logger.info(
            "creating_jira_issue",
            project=request.project_key,
            type=jira_type,
            title=request.title,
        )

        result = self._jira.create_issue(fields=fields)

        return ExternalIssue(
            id=result["key"],
            key=result["key"],
            url=f"{self._settings.jira_url}/browse/{result['key']}",
            title=request.title,
            description=request.description,
            issue_type=jira_type,
            status="To Do",
            parent_id=request.parent_id,
            labels=request.labels,
        )

    async def update_issue(
        self,
        issue_id: str,
        **updates: Any,
    ) -> ExternalIssue:
        """
        Update an existing Jira issue.

        Args:
            issue_id: Jira issue key (e.g., "PROJ-123").
            **updates: Fields to update.

        Returns:
            Updated issue.
        """
        await self._rate_limiter.acquire()

        fields = {}

        if "title" in updates:
            fields["summary"] = updates["title"]
        if "description" in updates:
            fields["description"] = updates["description"]
        if "status" in updates:
            # Status transitions require separate API call
            await self._transition_issue(issue_id, updates["status"])
        if "labels" in updates:
            fields["labels"] = updates["labels"]

        if fields:
            logger.info(
                "updating_jira_issue",
                issue_id=issue_id,
                fields=list(fields.keys()),
            )
            self._jira.update_issue_field(issue_id, fields)

        # Fetch and return updated issue
        return await self.get_issue(issue_id)

    async def get_issue(self, issue_id: str) -> ExternalIssue | None:
        """
        Get a Jira issue by key.

        Args:
            issue_id: Jira issue key.

        Returns:
            Issue if found, None otherwise.
        """
        await self._rate_limiter.acquire()

        try:
            issue = self._jira.issue(issue_id)

            if not issue:
                return None

            fields = issue.get("fields", {})

            return ExternalIssue(
                id=issue["key"],
                key=issue["key"],
                url=f"{self._settings.jira_url}/browse/{issue['key']}",
                title=fields.get("summary", ""),
                description=fields.get("description", "") or "",
                issue_type=fields.get("issuetype", {}).get("name", "Task"),
                status=fields.get("status", {}).get("name", "Unknown"),
                parent_id=fields.get("parent", {}).get("key") if fields.get("parent") else None,
                labels=fields.get("labels", []),
            )

        except Exception as e:
            logger.error("get_issue_error", issue_id=issue_id, error=str(e))
            return None

    async def link_issues(self, request: LinkIssuesRequest) -> bool:
        """
        Create a link between two Jira issues.

        Args:
            request: Link creation request.

        Returns:
            True if link created successfully.
        """
        await self._rate_limiter.acquire()

        # Map link type
        jira_link_type = EDGE_TYPE_TO_JIRA_LINK.get(request.link_type, "Relates")

        logger.info(
            "linking_jira_issues",
            source=request.source_id,
            target=request.target_id,
            link_type=jira_link_type,
        )

        try:
            self._jira.create_issue_link({
                "type": {"name": jira_link_type},
                "inwardIssue": {"key": request.source_id},
                "outwardIssue": {"key": request.target_id},
            })
            return True

        except Exception as e:
            logger.error(
                "link_issues_error",
                source=request.source_id,
                target=request.target_id,
                error=str(e),
            )
            return False

    async def delete_issue(self, issue_id: str) -> bool:
        """
        Delete a Jira issue.

        Args:
            issue_id: Jira issue key.

        Returns:
            True if deleted successfully.
        """
        await self._rate_limiter.acquire()

        logger.warning("deleting_jira_issue", issue_id=issue_id)

        try:
            self._jira.delete_issue(issue_id)
            return True
        except Exception as e:
            logger.error("delete_issue_error", issue_id=issue_id, error=str(e))
            return False

    async def search_issues(
        self,
        project_key: str,
        query: str | None = None,
        issue_type: str | None = None,
        max_results: int = 50,
    ) -> list[ExternalIssue]:
        """
        Search for Jira issues using JQL.

        Args:
            project_key: Project to search in.
            query: Optional text search query.
            issue_type: Filter by issue type.
            max_results: Maximum results.

        Returns:
            List of matching issues.
        """
        await self._rate_limiter.acquire()

        # Build JQL query
        jql_parts = [f"project = {project_key}"]

        if query:
            jql_parts.append(f"text ~ \"{query}\"")

        if issue_type:
            jira_type = NODE_TYPE_TO_JIRA.get(issue_type, issue_type)
            jql_parts.append(f"issuetype = \"{jira_type}\"")

        jql = " AND ".join(jql_parts)

        logger.info("searching_jira_issues", jql=jql)

        results = self._jira.jql(jql, limit=max_results)

        issues = []
        for issue in results.get("issues", []):
            fields = issue.get("fields", {})
            issues.append(ExternalIssue(
                id=issue["key"],
                key=issue["key"],
                url=f"{self._settings.jira_url}/browse/{issue['key']}",
                title=fields.get("summary", ""),
                description=fields.get("description", "") or "",
                issue_type=fields.get("issuetype", {}).get("name", "Task"),
                status=fields.get("status", {}).get("name", "Unknown"),
                parent_id=fields.get("parent", {}).get("key") if fields.get("parent") else None,
                labels=fields.get("labels", []),
            ))

        return issues

    async def _transition_issue(self, issue_id: str, status: str) -> bool:
        """
        Transition an issue to a new status.

        Args:
            issue_id: Jira issue key.
            status: Target status name.

        Returns:
            True if transition successful.
        """
        try:
            # Get available transitions
            transitions = self._jira.get_issue_transitions(issue_id)

            # Find matching transition
            for t in transitions.get("transitions", []):
                if t["name"].lower() == status.lower():
                    self._jira.issue_transition(issue_id, t["id"])
                    return True

            logger.warning(
                "transition_not_found",
                issue_id=issue_id,
                status=status,
            )
            return False

        except Exception as e:
            logger.error("transition_error", issue_id=issue_id, error=str(e))
            return False

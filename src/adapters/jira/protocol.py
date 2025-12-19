"""
Issue Tracker Protocol - Abstract interface for issue trackers.

Defines a common interface that Jira, GitHub Issues, Linear, etc.
can implement, keeping the core domain tracker-agnostic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ExternalIssue:
    """
    Representation of an issue in an external tracker.

    Canonical model that maps to different tracker formats.
    """

    id: str  # External ID (e.g., "PROJ-123")
    key: str  # Key/number
    url: str  # Direct URL to the issue
    title: str
    description: str
    issue_type: str  # epic, story, subtask, etc.
    status: str
    parent_id: str | None = None
    labels: list[str] | None = None
    custom_fields: dict[str, Any] | None = None


@dataclass
class CreateIssueRequest:
    """Request to create an issue in the external tracker."""

    project_key: str
    title: str
    description: str
    issue_type: str  # Will be mapped to tracker-specific type
    parent_id: str | None = None
    labels: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    custom_fields: dict[str, Any] | None = None


@dataclass
class LinkIssuesRequest:
    """Request to link two issues."""

    source_id: str  # External ID of source issue
    target_id: str  # External ID of target issue
    link_type: str  # blocks, relates_to, is_parent_of, etc.


class IssueTrackerProtocol(ABC):
    """
    Abstract protocol for issue trackers.

    All issue tracker adapters (Jira, GitHub, etc.) implement this interface,
    allowing the sync service to remain tracker-agnostic.
    """

    @abstractmethod
    async def create_issue(self, request: CreateIssueRequest) -> ExternalIssue:
        """
        Create a new issue.

        Args:
            request: Issue creation request.

        Returns:
            Created issue with external ID and URL.
        """
        ...

    @abstractmethod
    async def update_issue(
        self,
        issue_id: str,
        **updates: Any,
    ) -> ExternalIssue:
        """
        Update an existing issue.

        Args:
            issue_id: External issue ID.
            **updates: Fields to update.

        Returns:
            Updated issue.
        """
        ...

    @abstractmethod
    async def get_issue(self, issue_id: str) -> ExternalIssue | None:
        """
        Get an issue by ID.

        Args:
            issue_id: External issue ID.

        Returns:
            Issue if found, None otherwise.
        """
        ...

    @abstractmethod
    async def link_issues(self, request: LinkIssuesRequest) -> bool:
        """
        Create a link between two issues.

        Args:
            request: Link creation request.

        Returns:
            True if link created successfully.
        """
        ...

    @abstractmethod
    async def delete_issue(self, issue_id: str) -> bool:
        """
        Delete an issue.

        Args:
            issue_id: External issue ID.

        Returns:
            True if deleted successfully.
        """
        ...

    @abstractmethod
    async def search_issues(
        self,
        project_key: str,
        query: str | None = None,
        issue_type: str | None = None,
        max_results: int = 50,
    ) -> list[ExternalIssue]:
        """
        Search for issues.

        Args:
            project_key: Project to search in.
            query: Optional search query.
            issue_type: Filter by issue type.
            max_results: Maximum results to return.

        Returns:
            List of matching issues.
        """
        ...

    @property
    @abstractmethod
    def tracker_name(self) -> str:
        """Return the tracker name (e.g., 'jira', 'github')."""
        ...

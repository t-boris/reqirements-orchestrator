"""Jira types and models for API integration."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, computed_field


class JiraIssueType(str, Enum):
    """Jira issue types."""

    STORY = "Story"
    TASK = "Task"
    BUG = "Bug"
    EPIC = "Epic"


class JiraPriority(str, Enum):
    """Internal logical priority values.

    These map to Jira's priority names via PRIORITY_MAP.
    Never hardcode Jira priority strings in business logic.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Mapping from internal priority to Jira priority names
# Always use this map - never hardcode Jira priority strings
PRIORITY_MAP: dict[JiraPriority, str] = {
    JiraPriority.LOW: "Lowest",
    JiraPriority.MEDIUM: "Medium",
    JiraPriority.HIGH: "High",
    JiraPriority.CRITICAL: "Highest",
}


class JiraIssue(BaseModel):
    """Jira issue response model."""

    key: str = Field(..., description="Issue key (e.g., PROJ-123)")
    summary: str = Field(..., description="Issue summary/title")
    status: str = Field(..., description="Issue status (e.g., Open, In Progress)")
    assignee: Optional[str] = Field(None, description="Assignee display name")
    updated: Optional[str] = Field(None, description="Last updated timestamp (ISO format or relative)")
    description: Optional[str] = Field(None, description="Issue description (plain text)")
    base_url: str = Field(..., description="Jira base URL for computing issue URL")

    @computed_field
    @property
    def url(self) -> str:
        """Compute the full URL to the issue."""
        base = self.base_url.rstrip("/")
        return f"{base}/browse/{self.key}"


class JiraCreateRequest(BaseModel):
    """Request model for creating a Jira issue."""

    project_key: str = Field(..., description="Project key (e.g., PROJ)")
    summary: str = Field(..., description="Issue summary/title")
    description: str = Field(..., description="Issue description")
    issue_type: JiraIssueType = Field(..., description="Type of issue")
    priority: JiraPriority = Field(..., description="Issue priority")
    epic_key: Optional[str] = Field(None, description="Epic key to link to (e.g., PROJ-100)")
    labels: list[str] = Field(default_factory=list, description="Labels to apply")

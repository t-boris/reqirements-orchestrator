"""Type-specific schemas for Jira tickets."""
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


class JiraTicketBase(BaseModel):
    """Base schema with fields common to all Jira issue types."""

    summary: str = Field(
        default="",
        description="Clear, concise ticket title"
    )
    description: str = Field(
        default="",
        description="Detailed description"
    )
    priority: Literal["Highest", "High", "Medium", "Low"] = Field(
        default="Medium",
        description="Jira priority level"
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Labels for categorization"
    )
    components: list[str] = Field(
        default_factory=list,
        description="Jira components"
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Assignee username or email"
    )

    def _base_missing_fields(self) -> list[str]:
        """Check base fields common to all types."""
        missing = []
        if not self.summary:
            missing.append("summary")
        if not self.description:
            missing.append("description")
        return missing


class EpicSchema(JiraTicketBase):
    """Schema for Epic issues - high-level features or initiatives."""

    type: Literal["Epic"] = "Epic"

    def is_complete(self) -> bool:
        """Epics need summary and description."""
        return bool(self.summary and self.description)

    def get_missing_fields(self) -> list[str]:
        return self._base_missing_fields()


class StorySchema(JiraTicketBase):
    """Schema for User Story issues - user-facing features."""

    type: Literal["Story"] = "Story"
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Conditions for Definition of Done"
    )
    story_points: Optional[int] = Field(
        default=None,
        description="Estimation in story points"
    )
    epic_link: Optional[str] = Field(
        default=None,
        description="Parent Epic key (e.g., PROJ-123)"
    )

    def is_complete(self) -> bool:
        """Stories need summary, description, and at least one AC."""
        return bool(
            self.summary
            and self.description
            and len(self.acceptance_criteria) >= 1
        )

    def get_missing_fields(self) -> list[str]:
        missing = self._base_missing_fields()
        if not self.acceptance_criteria:
            missing.append("acceptance_criteria (at least one)")
        return missing


class TaskSchema(JiraTicketBase):
    """Schema for Task issues - technical work items."""

    type: Literal["Task"] = "Task"
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Conditions for completion"
    )
    estimated_hours: Optional[float] = Field(
        default=None,
        description="Time estimate in hours"
    )
    parent_link: Optional[str] = Field(
        default=None,
        description="Parent issue key (Story or Epic)"
    )

    def is_complete(self) -> bool:
        """Tasks need summary and description."""
        return bool(self.summary and self.description)

    def get_missing_fields(self) -> list[str]:
        return self._base_missing_fields()


class BugSchema(JiraTicketBase):
    """Schema for Bug issues - defects and issues."""

    type: Literal["Bug"] = "Bug"
    steps_to_reproduce: list[str] = Field(
        default_factory=list,
        description="Steps to reproduce the bug"
    )
    expected_behavior: str = Field(
        default="",
        description="What should happen"
    )
    actual_behavior: str = Field(
        default="",
        description="What actually happens"
    )
    environment: Optional[str] = Field(
        default=None,
        description="Environment info (browser, OS, version)"
    )

    def is_complete(self) -> bool:
        """Bugs need summary, description, steps, and expected/actual behavior."""
        return bool(
            self.summary
            and self.description
            and len(self.steps_to_reproduce) >= 1
            and self.expected_behavior
            and self.actual_behavior
        )

    def get_missing_fields(self) -> list[str]:
        missing = self._base_missing_fields()
        if not self.steps_to_reproduce:
            missing.append("steps_to_reproduce (at least one step)")
        if not self.expected_behavior:
            missing.append("expected_behavior")
        if not self.actual_behavior:
            missing.append("actual_behavior")
        return missing


# Union type for working with any ticket type
JiraTicket = Union[EpicSchema, StorySchema, TaskSchema, BugSchema]


def create_ticket(ticket_type: str) -> JiraTicketBase:
    """Factory function to create empty ticket of specified type."""
    type_map = {
        "Epic": EpicSchema,
        "Story": StorySchema,
        "Task": TaskSchema,
        "Bug": BugSchema,
    }
    schema_class = type_map.get(ticket_type, TaskSchema)
    return schema_class()

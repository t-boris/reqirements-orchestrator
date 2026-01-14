"""Schema for Jira ticket drafts."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class JiraTicketSchema(BaseModel):
    """Schema for a Jira ticket draft being built through conversation."""

    summary: str = Field(
        default="",
        description="Clear, concise ticket title"
    )
    description: str = Field(
        default="",
        description="Detailed technical description"
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="List of conditions for Definition of Done"
    )
    priority: Literal["Highest", "High", "Medium", "Low"] = Field(
        default="Medium",
        description="Jira priority level"
    )
    type: Literal["Epic", "Story", "Task", "Bug"] = Field(
        default="Task",
        description="Jira issue type"
    )

    def is_complete(self) -> bool:
        """Check if ticket has minimum required fields for creation."""
        return bool(
            self.summary
            and self.description
            and len(self.acceptance_criteria) >= 1
        )

    def get_missing_fields(self) -> list[str]:
        """Return list of fields that are missing or incomplete."""
        missing = []
        if not self.summary:
            missing.append("summary")
        if not self.description:
            missing.append("description")
        if not self.acceptance_criteria:
            missing.append("acceptance_criteria (at least one)")
        return missing

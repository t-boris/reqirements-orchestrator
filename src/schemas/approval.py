"""Approval policy schemas for multi-user support.

Defines configurable approval policies for channels:
- ANY_CONTRIBUTOR: Anyone in thread can approve
- ONLY_ADMINS: Only channel admins can approve
- TWO_PERSON: Creator cannot approve their own work
- ROLE_BASED: Specific roles can approve specific types

Phase 27.4 - State-Bound Approvals
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ApprovalPolicy(str, Enum):
    """Configurable approval policies for channels."""

    ANY_CONTRIBUTOR = "any_contributor"  # Anyone in thread can approve
    ONLY_ADMINS = "only_admins"  # Only channel admins can approve
    TWO_PERSON = "two_person"  # Creator cannot approve their own work
    ROLE_BASED = "role_based"  # Specific roles can approve specific types


class ApprovalRequirement(BaseModel):
    """Approval requirement for a specific action type.

    Allows configuring different policies for different actions
    (e.g., stricter requirements for production deployments).
    """

    action_type: str = Field(
        description="Type of action: jira_create, jira_update, etc."
    )
    policy: ApprovalPolicy = Field(default=ApprovalPolicy.ANY_CONTRIBUTOR)
    required_role: Optional[str] = Field(
        default=None, description="For ROLE_BASED policy, the required role"
    )
    min_approvers: int = Field(default=1, description="Minimum approvers needed")


class ChannelApprovalConfig(BaseModel):
    """Approval configuration for a channel.

    Stores the default policy and any action-specific requirements.
    """

    channel_id: str = Field(description="Slack channel ID")
    default_policy: ApprovalPolicy = Field(default=ApprovalPolicy.ANY_CONTRIBUTOR)
    requirements: list[ApprovalRequirement] = Field(default_factory=list)
    created_by: str = Field(description="User who configured this policy")
    updated_at: str = Field(description="ISO timestamp of last update")

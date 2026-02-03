"""Shared test fixtures."""

import pytest
from src.domain.types import ChannelId, EntityId, ThreadTs, UserId
from src.domain.content import IssueType, WorkItemContent, DecisionType, DecisionContent


@pytest.fixture
def channel_id():
    """Sample channel ID."""
    return ChannelId("C12345678")


@pytest.fixture
def thread_ts():
    """Sample thread timestamp."""
    return ThreadTs("1234567890.123456")


@pytest.fixture
def user_id():
    """Sample user ID."""
    return UserId("U12345678")


@pytest.fixture
def work_item_content():
    """Sample work item content."""
    return WorkItemContent(
        issue_type=IssueType.STORY,
        title="Test Story",
        description="Test description",
        acceptance_criteria=["AC1", "AC2"],
    )


@pytest.fixture
def decision_content():
    """Sample decision content."""
    return DecisionContent(
        decision_type=DecisionType.ARCHITECTURE,
        title="Test Decision",
        description="We decided to use PostgreSQL",
        rationale="Better for event sourcing",
    )

"""Fixtures for integration tests."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.db.workitem_store import WorkItemStore
from src.db.channel_mode_store import ChannelModeStore
from src.db.commit_store import CommitStore
from src.slack.session import SessionIdentity


@pytest_asyncio.fixture
async def mock_conn():
    """Mock database connection."""
    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=AsyncMock())
    return conn


@pytest.fixture
def identity():
    """Test session identity with user_id attribute for binding tests.

    Note: SessionIdentity doesn't have user_id, but binding.py accesses
    identity.user_id with fallback to "unknown". We use a MagicMock that
    wraps SessionIdentity to add user_id for tests.
    """
    real_identity = SessionIdentity(
        team_id="T123",
        channel_id="C456",
        thread_ts="1234567890.123456",
    )
    # Wrap with MagicMock to add user_id attribute
    mock_identity = MagicMock(wraps=real_identity)
    mock_identity.team_id = real_identity.team_id
    mock_identity.channel_id = real_identity.channel_id
    mock_identity.thread_ts = real_identity.thread_ts
    mock_identity.session_id = real_identity.session_id
    mock_identity.user_id = "U789"
    return mock_identity


@pytest.fixture
def mock_slack_client():
    """Mock Slack WebClient."""
    client = MagicMock()
    client.chat_postMessage = MagicMock()
    client.chat_update = MagicMock()
    return client


@pytest.fixture
def now():
    """Current datetime for test data."""
    return datetime.now(timezone.utc)

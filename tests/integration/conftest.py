"""Fixtures for integration tests."""
import pytest
import pytest_asyncio
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
    """Test session identity."""
    return SessionIdentity(
        team_id="T123",
        channel_id="C456",
        thread_ts="1234567890.123456",
        user_id="U789",
    )


@pytest.fixture
def mock_slack_client():
    """Mock Slack WebClient."""
    client = MagicMock()
    client.chat_postMessage = MagicMock()
    client.chat_update = MagicMock()
    return client

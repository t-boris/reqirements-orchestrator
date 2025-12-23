"""
Pytest configuration and fixtures.

Mocks external dependencies to allow testing without credentials.
"""

import sys
from unittest.mock import MagicMock, AsyncMock

import pytest


# =============================================================================
# Mock Slack SDK before any imports
# =============================================================================

# Create mock slack modules
mock_slack_bolt = MagicMock()
mock_slack_bolt.async_app = MagicMock()
mock_slack_bolt.async_app.AsyncApp = MagicMock()
mock_slack_bolt.adapter = MagicMock()
mock_slack_bolt.adapter.socket_mode = MagicMock()
mock_slack_bolt.adapter.socket_mode.async_handler = MagicMock()
mock_slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler = MagicMock()

# Register mocks
sys.modules["slack_bolt"] = mock_slack_bolt
sys.modules["slack_bolt.async_app"] = mock_slack_bolt.async_app
sys.modules["slack_bolt.adapter"] = mock_slack_bolt.adapter
sys.modules["slack_bolt.adapter.socket_mode"] = mock_slack_bolt.adapter.socket_mode
sys.modules["slack_bolt.adapter.socket_mode.async_handler"] = mock_slack_bolt.adapter.socket_mode.async_handler
sys.modules["slack_bolt.error"] = MagicMock()


# =============================================================================
# Mock LangChain/LangGraph expensive imports
# =============================================================================

# Mock MCP client
mock_mcp = MagicMock()
mock_mcp.MultiServerMCPClient = MagicMock()
sys.modules["langchain_mcp_adapters.client"] = mock_mcp


# =============================================================================
# Environment Check
# =============================================================================
# Tests require environment variables to be set.
# Run: source .env && pytest tests/

import os

required_vars = [
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "OPENAI_API_KEY",
    "DATABASE_URL",
]

missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"\nWarning: Missing environment variables for tests: {', '.join(missing)}")
    print("Run: source .env && pytest tests/\n")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_state():
    """Create a sample RequirementState for testing."""
    from src.graph.state import create_initial_state
    return create_initial_state(
        channel_id="C12345",
        user_id="U67890",
        message="Build a feature to track user metrics",
        thread_ts="1234567890.123456",
        is_mention=True,
    )


@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return MagicMock(
        content='{"intent": "requirement", "confidence": 0.95}'
    )


@pytest.fixture
def mock_jira_client():
    """Mock Jira MCP client."""
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={"key": "TEST-123"})
    return client


@pytest.fixture
def mock_zep_client():
    """Mock Zep memory client."""
    client = MagicMock()
    client.memory = MagicMock()
    client.memory.get = AsyncMock(return_value=[])
    client.memory.add = AsyncMock()
    client.facts = MagicMock()
    client.facts.get_facts = AsyncMock(return_value=[])
    return client

"""Test fixtures for sync service tests."""
import os
import pytest_asyncio
from psycopg import AsyncConnection


@pytest_asyncio.fixture
async def db_connection():
    """Create a database connection for testing.

    Uses DATABASE_URL from environment or falls back to localhost.
    Each test runs in a transaction that gets rolled back.
    """
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://maro:maro_db_k7x9Qp2mNv@localhost:5432/maro",
    )

    async with await AsyncConnection.connect(database_url) as conn:
        # Start a savepoint so we can rollback all test changes
        await conn.execute("BEGIN")

        yield conn

        # Rollback to clean up test data
        await conn.rollback()

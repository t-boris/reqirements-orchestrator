"""
Database connection and session management.

Provides async database access using SQLAlchemy 2.0.
"""

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.adapters.persistence.models import Base
from src.config.settings import Settings

logger = structlog.get_logger()


class Database:
    """
    Async database connection manager.

    Manages SQLAlchemy async engine and session factory.
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize database connection.

        Args:
            settings: Application settings with DATABASE_URL.
        """
        self._engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_size=5,
            max_overflow=10,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("database_initialized", url=settings.database_url[:30] + "...")

    async def create_tables(self) -> None:
        """Create all tables defined in models."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_created")

    async def drop_tables(self) -> None:
        """Drop all tables (use with caution!)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("database_tables_dropped")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session.

        Yields:
            AsyncSession for database operations.

        Example:
            async with database.session() as session:
                result = await session.execute(query)
        """
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        """Close the database connection."""
        await self._engine.dispose()
        logger.info("database_closed")


_database: Database | None = None


def get_database() -> Database:
    """
    Get the database singleton.

    Returns:
        Database instance.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _database is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _database


async def init_database(settings: Settings) -> Database:
    """
    Initialize the database singleton.

    Args:
        settings: Application settings.

    Returns:
        Initialized Database instance.
    """
    global _database
    _database = Database(settings)
    await _database.create_tables()
    return _database

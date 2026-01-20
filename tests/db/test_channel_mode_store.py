"""Tests for ChannelModeStore operations."""
import pytest

from src.db.models import ChannelMode, ChannelModeConfig
from src.db.channel_mode_store import ChannelModeStore


class TestChannelModeStore:
    """Test suite for ChannelModeStore."""

    @pytest.fixture
    async def store(self, db_connection):
        """Create store with test connection."""
        store = ChannelModeStore(db_connection)
        await store.create_tables()
        return store

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        """Getting config for unconfigured channel returns None."""
        result = await store.get("C_NONEXISTENT")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_create_creates_with_default_project(self, store):
        """get_or_create creates PROJECT mode by default."""
        config = await store.get_or_create("C123", "U456")

        assert config.channel_id == "C123"
        assert config.mode == ChannelMode.PROJECT
        assert config.set_by == "U456"
        assert config.primary_epic is None

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self, store):
        """get_or_create returns existing config."""
        # Create first
        await store.set_mode("C123", ChannelMode.BUGS, "U456")

        # get_or_create should return existing
        config = await store.get_or_create("C123", "U999")

        assert config.mode == ChannelMode.BUGS
        assert config.set_by == "U456"  # Original setter, not U999

    @pytest.mark.asyncio
    async def test_set_mode_creates_config(self, store):
        """set_mode creates config if not exists."""
        config = await store.set_mode("C123", ChannelMode.OPS, "U456")

        assert config.channel_id == "C123"
        assert config.mode == ChannelMode.OPS
        assert config.set_by == "U456"

    @pytest.mark.asyncio
    async def test_set_mode_updates_existing(self, store):
        """set_mode updates existing config."""
        # Create with PROJECT
        await store.set_mode("C123", ChannelMode.PROJECT, "U456")

        # Update to BUGS
        config = await store.set_mode("C123", ChannelMode.BUGS, "U789")

        assert config.mode == ChannelMode.BUGS
        assert config.set_by == "U789"

    @pytest.mark.asyncio
    async def test_set_mode_feature_with_epic(self, store):
        """set_mode in FEATURE mode stores primary_epic."""
        config = await store.set_mode(
            "C123",
            ChannelMode.FEATURE,
            "U456",
            primary_epic="PROJ-50",
        )

        assert config.mode == ChannelMode.FEATURE
        assert config.primary_epic == "PROJ-50"

    @pytest.mark.asyncio
    async def test_set_mode_clears_epic_for_non_feature(self, store):
        """set_mode clears primary_epic when not FEATURE mode."""
        # Set feature with epic
        await store.set_mode("C123", ChannelMode.FEATURE, "U456", primary_epic="PROJ-50")

        # Switch to project - epic should be cleared
        config = await store.set_mode("C123", ChannelMode.PROJECT, "U456")

        assert config.mode == ChannelMode.PROJECT
        assert config.primary_epic is None

    @pytest.mark.asyncio
    async def test_suggestion_shown(self, store):
        """mark_suggestion_shown updates flag."""
        await store.get_or_create("C123", "U456")

        result = await store.mark_suggestion_shown("C123")
        assert result is True

        config = await store.get("C123")
        assert config.suggestion_shown is True

    @pytest.mark.asyncio
    async def test_suggestion_response(self, store):
        """set_suggestion_response records user response."""
        await store.get_or_create("C123", "U456")

        await store.set_suggestion_response("C123", True)

        config = await store.get("C123")
        assert config.suggestion_accepted is True

    @pytest.mark.asyncio
    async def test_suggestion_response_rejected(self, store):
        """set_suggestion_response records rejection."""
        await store.get_or_create("C123", "U456")

        await store.set_suggestion_response("C123", False)

        config = await store.get("C123")
        assert config.suggestion_accepted is False

    @pytest.mark.asyncio
    async def test_mark_suggestion_shown_nonexistent(self, store):
        """mark_suggestion_shown returns False for nonexistent channel."""
        result = await store.mark_suggestion_shown("C_NONEXISTENT")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_suggestion_response_nonexistent(self, store):
        """set_suggestion_response returns False for nonexistent channel."""
        result = await store.set_suggestion_response("C_NONEXISTENT", True)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_returns_all_fields(self, store):
        """get returns complete ChannelModeConfig with all fields."""
        await store.set_mode("C123", ChannelMode.FEATURE, "U456", primary_epic="PROJ-100")
        await store.mark_suggestion_shown("C123")
        await store.set_suggestion_response("C123", True)

        config = await store.get("C123")

        assert config is not None
        assert config.id is not None
        assert config.channel_id == "C123"
        assert config.mode == ChannelMode.FEATURE
        assert config.primary_epic == "PROJ-100"
        assert config.set_by == "U456"
        assert config.set_at is not None
        assert config.suggestion_shown is True
        assert config.suggestion_accepted is True
        assert config.created_at is not None
        assert config.updated_at is not None

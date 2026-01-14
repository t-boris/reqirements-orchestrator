"""Channel context retrieval for agent consumption."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Literal

from psycopg import AsyncConnection

from src.db.channel_context_store import ChannelContextStore
from src.db.models import ChannelContext
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class RetrievalMode(str, Enum):
    """Context retrieval modes."""
    COMPACT = "compact"  # 10-20 bullets, production use
    DEBUG = "debug"      # Full details, troubleshooting
    RAW = "raw"          # Internal use, full model


@dataclass
class ContextSource:
    """Tracks where a piece of context came from."""
    layer: Literal["knowledge", "jira", "config", "derived"]
    source_id: str  # pin_id, jira_key, etc.
    source_type: str  # "pin", "epic", "ticket", "config"


@dataclass
class ChannelContextResult:
    """Result of context retrieval for agent consumption.

    Designed for injection into AgentState.
    """
    channel_id: str
    team_id: str

    # Version for cache invalidation
    context_version: int

    # Compact representation (bullets)
    bullets: list[str] = field(default_factory=list)

    # Key facts
    default_project: Optional[str] = None
    naming_convention: Optional[str] = None
    definition_of_done: Optional[str] = None

    # Active context
    active_epics: list[str] = field(default_factory=list)
    recent_tickets: list[str] = field(default_factory=list)

    # Source tracking (for explainability)
    sources: list[ContextSource] = field(default_factory=list)

    # Metadata
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mode: RetrievalMode = RetrievalMode.COMPACT

    def to_dict(self) -> dict:
        """Convert to dict for AgentState storage."""
        return {
            "channel_id": self.channel_id,
            "team_id": self.team_id,
            "context_version": self.context_version,
            "bullets": self.bullets,
            "default_project": self.default_project,
            "naming_convention": self.naming_convention,
            "definition_of_done": self.definition_of_done,
            "active_epics": self.active_epics,
            "recent_tickets": self.recent_tickets,
            "retrieved_at": self.retrieved_at.isoformat(),
            "mode": self.mode.value,
        }

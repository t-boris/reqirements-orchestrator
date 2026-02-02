"""SuperMode handlers module.

Four SuperModes for message handling:
- CREATE: Define new work items or decisions
- MODIFY: Change existing entities
- RECORD: Capture decisions
- CONVERSE: Casual conversation

Ref: BOT_DESIGN.md - Four SuperModes
"""

from src.modes.base import ModeHandler, ModeResult
from src.modes.dispatcher import dispatch_mode, ModeDispatcher

__all__ = [
    "ModeHandler",
    "ModeResult",
    "dispatch_mode",
    "ModeDispatcher",
]

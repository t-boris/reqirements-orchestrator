"""Slack block builders.

This package contains block builders split by purpose:
- draft: Ticket draft preview, approval, rejection
- duplicates: Duplicate ticket handling
- decisions: Architecture decision posts
- ui: Generic UI elements (hints, buttons, help)
"""

from src.slack.blocks.draft import (
    get_draft_state_badge,
    build_session_card,
    build_epic_selector,
    build_draft_preview_blocks,
    build_draft_preview_blocks_with_hash,
    build_findings_blocks,
    build_linked_confirmation_blocks,
)
from src.slack.blocks.duplicates import (
    build_duplicate_blocks,
)
from src.slack.blocks.decisions import build_decision_blocks
from src.slack.blocks.ui import (
    build_persona_indicator,
    build_hint_with_buttons,
    build_welcome_blocks,
)
from src.slack.blocks.scope_gate import (
    build_scope_gate_blocks,
    build_scope_gate_dismissed_blocks,
    build_scope_gate_remembered_blocks,
)

__all__ = [
    # Draft
    "get_draft_state_badge",
    "build_session_card",
    "build_epic_selector",
    "build_draft_preview_blocks",
    "build_draft_preview_blocks_with_hash",
    "build_findings_blocks",
    "build_linked_confirmation_blocks",
    # Duplicates
    "build_duplicate_blocks",
    # Decisions
    "build_decision_blocks",
    # UI
    "build_persona_indicator",
    "build_hint_with_buttons",
    "build_welcome_blocks",
    # Scope Gate
    "build_scope_gate_blocks",
    "build_scope_gate_dismissed_blocks",
    "build_scope_gate_remembered_blocks",
]

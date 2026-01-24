"""Slack blocks for StructuredDraft structure visualization.

Shows the draft's typed structure including kind, scope, lifecycle,
and item hierarchy after mutations (R8).

INVARIANT I5: Draft Lifecycle = 3 User-Facing States
Users see: Drafting, Ready, Published
Internal: EMPTY, SINGLE_ITEM, PLAN, PLAN_REFINED, APPROVED, COMMITTED

UI must show user_state (3 states), never lifecycle (6 states).

Phase 28.6: Structure Feedback UI
- After each Draft form change, bot must show the new form (R8)
- Buttons bound to draft version for stale detection (R9)
"""
import json
from typing import Any

from src.schemas.draft import IssueType
from src.schemas.structured_draft import (
    DraftItem,
    DraftItemStatus,
    DraftKind,
    DraftLifecycle,
    DraftScope,
    StructuredDraft,
    UserDraftState,
)


def build_structure_blocks(
    draft: StructuredDraft,
    show_actions: bool = True,
    include_version: bool = True,
) -> list[dict[str, Any]]:
    """Build Slack blocks showing StructuredDraft structure.

    R8: After each Draft form change, bot must show the new form.

    Args:
        draft: StructuredDraft to visualize
        show_actions: Whether to include approve/edit buttons
        include_version: Whether to show version info in footer

    Returns:
        List of Slack block dicts
    """
    blocks: list[dict[str, Any]] = []

    # Header with kind and scope
    blocks.append(_build_header_block(draft))

    # Divider
    blocks.append({"type": "divider"})

    # Items list with hierarchy
    if draft.items:
        # Group items: epics first, then stories under them, then orphan items
        epics = [i for i in draft.items if i.issue_type == IssueType.EPIC]
        items_by_parent: dict[str | None, list[DraftItem]] = {}

        for item in draft.items:
            if item.issue_type != IssueType.EPIC:
                parent = item.parent_id
                if parent not in items_by_parent:
                    items_by_parent[parent] = []
                items_by_parent[parent].append(item)

        # Render epics with their children
        item_index = 1
        for epic in epics:
            blocks.append(_build_item_block(epic, item_index, is_child=False))
            item_index += 1

            # Render children of this epic
            children = items_by_parent.get(epic.id, [])
            for child in children:
                blocks.append(_build_item_block(child, item_index, is_child=True))
                item_index += 1

        # Render orphan items (no parent)
        orphans = items_by_parent.get(None, [])
        for orphan in orphans:
            # Skip if it's an epic (already rendered above)
            if orphan.issue_type != IssueType.EPIC:
                blocks.append(_build_item_block(orphan, item_index, is_child=False))
                item_index += 1

        # Truncation message if too many items
        if len(draft.items) > 10:
            shown = min(10, len(draft.items))
            remaining = len(draft.items) - shown
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"_+{remaining} more items not shown_",
                }],
            })
    else:
        # No items yet
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_No items in draft yet_",
            },
        })

    # Action buttons (R9: version-bound)
    if show_actions:
        blocks.append({"type": "divider"})
        blocks.append(_build_action_buttons(draft))

    # Footer with version and item count
    if include_version:
        blocks.append(_build_version_context(draft))

    return blocks


def _build_header_block(draft: StructuredDraft) -> dict[str, Any]:
    """Build header showing user-facing state.

    INVARIANT I5: Show user_state, hide lifecycle.
    """
    kind_emoji = "📋" if draft.kind == DraftKind.PLAN else "📝"
    scope_label = {
        DraftScope.SINGLE: "Single Item",
        DraftScope.EPICS_ONLY: "Epics Only",
        DraftScope.FULL_PLAN: "Full Plan",
    }.get(draft.scope, draft.scope.value)

    # INVARIANT I5: Use user_state (3 states) instead of lifecycle (6 states)
    user_state_emoji = {
        UserDraftState.DRAFTING: "📝",   # Yellow/warning
        UserDraftState.READY: "✅",       # Green/good
        UserDraftState.PUBLISHED: "🚀",   # Blue/primary
    }.get(draft.user_state, "❓")

    return {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{kind_emoji} Draft Structure ({draft.user_state.label})",
            "emoji": True,
        },
    }


def _build_item_block(item: DraftItem, index: int, is_child: bool = False) -> dict[str, Any]:
    """Build block for a single draft item."""
    type_emoji = {
        IssueType.EPIC: "🎯",
        IssueType.STORY: "📖",
        IssueType.TASK: "✔️",
        IssueType.BUG: "🐛",
    }.get(item.issue_type, "📄")

    status_emoji = {
        DraftItemStatus.PROPOSED: "🔵",
        DraftItemStatus.APPROVED: "🟢",
        DraftItemStatus.COMMITTED: "✅",
    }.get(item.status, "⚪")

    indent = "    └─ " if is_child else ""
    title_text = item.title or "_No title_"

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{indent}{status_emoji} {type_emoji} *{item.issue_type.value.upper()}:* {title_text}",
        },
    }


def _build_action_buttons(draft: StructuredDraft) -> dict[str, Any]:
    """Build approve/edit action buttons with version binding.

    R9: Buttons include draft version in payload for stale detection.
    """
    payload = {
        "draft_id": draft.id,
        "version": draft.version,
    }

    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve Structure", "emoji": True},
                "value": json.dumps(payload),
                "action_id": "approve_structure",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit Structure", "emoji": True},
                "value": json.dumps(payload),
                "action_id": "edit_structure",
            },
        ],
    }


def _build_version_context(draft: StructuredDraft) -> dict[str, Any]:
    """Build footer context with version info.

    INVARIANT I5: Show user_state.label, not lifecycle.value.
    """
    return {
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Version {draft.version} | {len(draft.items)} items | {draft.user_state.label}",
        }],
    }

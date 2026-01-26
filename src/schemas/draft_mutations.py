"""Draft mutation operations for StructuredDraft.

Provides structural mutation operations that can be applied to StructuredDraft.
Split from structured_draft.py for modularization.
"""
from typing import TYPE_CHECKING, Any

from src.schemas.draft import IssueType

if TYPE_CHECKING:
    from src.schemas.structured_draft import StructuredDraft


def split_to_plan(
    draft: "StructuredDraft",
    user_id: str,
    item_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Transform SINGLE_ITEM draft to PLAN with multiple items.

    If current draft has a single item, it becomes the first item in the plan.
    Additional items can be provided via item_titles.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        item_titles: Optional list of titles for new items.

    Returns:
        dict with 'success', 'message', 'items_created'.
    """
    from src.schemas.structured_draft import (
        DraftItem,
        DraftItemStatus,
        DraftKind,
        DraftLifecycle,
        DraftScope,
    )

    # Validate: must be SINGLE_ITEM or EMPTY
    if draft.kind == DraftKind.PLAN:
        return {"success": False, "message": "Already a plan"}

    # If we have a primary item, keep it
    existing_items = list(draft.items)

    # Add new items from titles if provided
    if item_titles:
        for title in item_titles:
            new_item = DraftItem(
                issue_type=IssueType.EPIC,  # Default to epic for plan items
                title=title,
                status=DraftItemStatus.PROPOSED,
            )
            existing_items.append(new_item)

    # Update draft
    draft.kind = DraftKind.PLAN
    draft.scope = DraftScope.EPICS_ONLY  # Default scope for plans
    draft.items = existing_items

    # Update lifecycle
    if draft.lifecycle in (DraftLifecycle.EMPTY, DraftLifecycle.SINGLE_ITEM):
        draft.lifecycle = DraftLifecycle.PLAN

    # Log the change
    draft.log_change(
        action="split_to_plan",
        user_id=user_id,
        details={"item_count": len(draft.items), "new_titles": item_titles or []},
    )

    return {
        "success": True,
        "message": f"Transformed to plan with {len(draft.items)} items",
        "items_created": len(item_titles or []),
    }


def add_items(
    draft: "StructuredDraft",
    user_id: str,
    items_to_add: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add new items to the draft.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        items_to_add: list of dicts with 'title', 'issue_type', optional 'parent_id'

    Returns:
        dict with 'success', 'message', 'items_added'.
    """
    from src.schemas.structured_draft import (
        DraftItem,
        DraftItemStatus,
        DraftKind,
        DraftLifecycle,
    )

    if not items_to_add:
        return {"success": False, "message": "No items to add"}

    added = []
    for item_data in items_to_add:
        issue_type = IssueType.STORY  # Default
        if "issue_type" in item_data:
            try:
                issue_type = IssueType(item_data["issue_type"].lower())
            except ValueError:
                pass

        new_item = DraftItem(
            issue_type=issue_type,
            title=item_data.get("title", ""),
            goal=item_data.get("goal", ""),
            parent_id=item_data.get("parent_id"),
            status=DraftItemStatus.PROPOSED,
        )
        draft.items.append(new_item)
        added.append(new_item.id)

    # If we now have multiple items, upgrade to PLAN
    if len(draft.items) > 1 and draft.kind == DraftKind.SINGLE_ITEM:
        draft.kind = DraftKind.PLAN
        if draft.lifecycle == DraftLifecycle.SINGLE_ITEM:
            draft.lifecycle = DraftLifecycle.PLAN

    draft.log_change(
        action="add_items",
        user_id=user_id,
        details={"items_added": added, "count": len(added)},
    )

    return {
        "success": True,
        "message": f"Added {len(added)} items",
        "items_added": added,
    }


def merge_items(
    draft: "StructuredDraft",
    user_id: str,
    item_ids: list[str],
    merged_title: str | None = None,
) -> dict[str, Any]:
    """Merge multiple items into one.

    Takes the first item as base, combines content from others,
    then removes the merged items.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        item_ids: List of item IDs to merge.
        merged_title: Optional title for the merged item.

    Returns:
        dict with 'success', 'message', 'merged_item_id'.
    """
    from src.schemas.structured_draft import DraftKind, DraftLifecycle

    if len(item_ids) < 2:
        return {"success": False, "message": "Need at least 2 items to merge"}

    # Find items to merge
    items_to_merge = [i for i in draft.items if i.id in item_ids]
    if len(items_to_merge) < 2:
        return {
            "success": False,
            "message": f"Found only {len(items_to_merge)} of {len(item_ids)} items",
        }

    # Use first item as base
    base_item = items_to_merge[0]

    # Merge titles and goals
    if merged_title:
        base_item.title = merged_title
    else:
        # Combine titles
        titles = [i.title for i in items_to_merge if i.title]
        base_item.title = (
            " + ".join(titles[:2])
            if len(titles) > 1
            else (titles[0] if titles else "Merged Item")
        )

    # Combine goals
    goals = [i.goal for i in items_to_merge if i.goal]
    if goals:
        base_item.goal = "; ".join(goals)

    # Combine constraints
    for item in items_to_merge[1:]:
        base_item.constraints.extend(item.constraints)

    # Remove merged items (except base)
    merged_ids = [i.id for i in items_to_merge[1:]]
    draft.items = [i for i in draft.items if i.id not in merged_ids]

    # If we're down to 1 item, revert to SINGLE_ITEM
    if len(draft.items) == 1:
        draft.kind = DraftKind.SINGLE_ITEM
        if draft.lifecycle == DraftLifecycle.PLAN:
            draft.lifecycle = DraftLifecycle.SINGLE_ITEM

    draft.log_change(
        action="merge_items",
        user_id=user_id,
        details={"merged_ids": merged_ids, "into": base_item.id},
    )

    return {
        "success": True,
        "message": f"Merged {len(items_to_merge)} items into one",
        "merged_item_id": base_item.id,
    }


def elevate_to_epic(
    draft: "StructuredDraft",
    user_id: str,
    item_id: str | None = None,
) -> dict[str, Any]:
    """Change an item's type to EPIC.

    If item_id is None and draft is SINGLE_ITEM, elevates the primary item.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        item_id: Optional item ID to elevate.

    Returns:
        dict with 'success', 'message', 'item_id'.
    """
    from src.schemas.structured_draft import DraftKind

    # Find target item
    target = None
    if item_id:
        for item in draft.items:
            if item.id == item_id:
                target = item
                break
    elif draft.kind == DraftKind.SINGLE_ITEM and draft.items:
        target = draft.items[0]

    if not target:
        return {"success": False, "message": "Item not found"}

    if target.issue_type == IssueType.EPIC:
        return {"success": False, "message": "Item is already an epic"}

    old_type = target.issue_type
    target.issue_type = IssueType.EPIC

    draft.log_change(
        action="elevate_to_epic",
        user_id=user_id,
        details={"item_id": target.id, "from_type": old_type.value},
    )

    return {
        "success": True,
        "message": "Elevated item to Epic",
        "item_id": target.id,
    }


def decompose_to_stories(
    draft: "StructuredDraft",
    user_id: str,
    epic_id: str | None = None,
    story_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Create stories under an epic.

    If epic_id is None and draft has exactly one epic, uses that.
    Creates story items with parent_id pointing to the epic.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        epic_id: Optional epic ID to decompose.
        story_titles: List of story titles to create.

    Returns:
        dict with 'success', 'message', 'stories_created'.
    """
    from src.schemas.structured_draft import (
        DraftItem,
        DraftItemStatus,
        DraftKind,
        DraftLifecycle,
        DraftScope,
    )

    # Find target epic
    epic = None
    if epic_id:
        for item in draft.items:
            if item.id == epic_id and item.issue_type == IssueType.EPIC:
                epic = item
                break
    else:
        # Find the only epic
        epics = [i for i in draft.items if i.issue_type == IssueType.EPIC]
        if len(epics) == 1:
            epic = epics[0]

    if not epic:
        return {"success": False, "message": "No epic found to decompose"}

    if not story_titles:
        return {"success": False, "message": "No story titles provided"}

    # Create stories
    created = []
    for title in story_titles:
        story = DraftItem(
            issue_type=IssueType.STORY,
            title=title,
            parent_id=epic.id,
            status=DraftItemStatus.PROPOSED,
        )
        draft.items.append(story)
        created.append(story.id)

    # Upgrade to FULL_PLAN scope since we now have stories
    draft.scope = DraftScope.FULL_PLAN

    # Ensure we're in PLAN kind
    if draft.kind == DraftKind.SINGLE_ITEM:
        draft.kind = DraftKind.PLAN
        if draft.lifecycle == DraftLifecycle.SINGLE_ITEM:
            draft.lifecycle = DraftLifecycle.PLAN

    draft.log_change(
        action="decompose_to_stories",
        user_id=user_id,
        details={"epic_id": epic.id, "stories_created": created},
    )

    return {
        "success": True,
        "message": f"Created {len(created)} stories under epic",
        "stories_created": created,
    }


def change_scope(
    draft: "StructuredDraft",
    user_id: str,
    new_scope: "DraftScope",
) -> dict[str, Any]:
    """Change the generation scope of the draft.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        new_scope: The new scope to set.

    Returns:
        dict with 'success', 'message', 'old_scope', 'new_scope'.
    """
    from src.schemas.structured_draft import DraftScope

    old_scope = draft.scope

    if old_scope == new_scope:
        return {"success": False, "message": f"Already at scope {new_scope.value}"}

    draft.scope = new_scope

    draft.log_change(
        action="change_scope",
        user_id=user_id,
        details={"from": old_scope.value, "to": new_scope.value},
    )

    return {
        "success": True,
        "message": f"Changed scope from {old_scope.value} to {new_scope.value}",
        "old_scope": old_scope.value,
        "new_scope": new_scope.value,
    }


def remove_items(
    draft: "StructuredDraft",
    user_id: str,
    item_ids: list[str],
) -> dict[str, Any]:
    """Remove items from the draft.

    Also removes any items that have a removed item as parent_id.

    Args:
        draft: The StructuredDraft to modify.
        user_id: User ID performing the operation.
        item_ids: List of item IDs to remove.

    Returns:
        dict with 'success', 'message', 'removed_count'.
    """
    from src.schemas.structured_draft import DraftKind, DraftLifecycle

    if not item_ids:
        return {"success": False, "message": "No items to remove"}

    # First pass: mark items for removal
    to_remove = set(item_ids)

    # Second pass: also remove children of removed items
    for item in draft.items:
        if item.parent_id in to_remove:
            to_remove.add(item.id)

    # Remove items
    before_count = len(draft.items)
    draft.items = [i for i in draft.items if i.id not in to_remove]
    removed_count = before_count - len(draft.items)

    if removed_count == 0:
        return {"success": False, "message": "No items found to remove"}

    # If we're down to 0 or 1 item, adjust kind/lifecycle
    if len(draft.items) == 0:
        draft.kind = DraftKind.SINGLE_ITEM
        draft.lifecycle = DraftLifecycle.EMPTY
    elif len(draft.items) == 1:
        draft.kind = DraftKind.SINGLE_ITEM
        if draft.lifecycle in (DraftLifecycle.PLAN, DraftLifecycle.PLAN_REFINED):
            draft.lifecycle = DraftLifecycle.SINGLE_ITEM

    draft.log_change(
        action="remove_items",
        user_id=user_id,
        details={"removed_ids": list(to_remove), "count": removed_count},
    )

    return {
        "success": True,
        "message": f"Removed {removed_count} items",
        "removed_count": removed_count,
    }

"""Structured Draft schema for Phase 28 - Typed, versioned design object.

This replaces the text-based TicketDraft with a typed design object
that has lifecycle states and structural mutations.

Core shift: From "bot collects text for a ticket" to "bot manages the form
of a design object and the evolution of its structure."
"""
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.schemas.draft import IssueType

if TYPE_CHECKING:
    from src.schemas.draft import TicketDraft


class DraftKind(str, Enum):
    """The shape of the draft - what structure it represents.

    Determines whether the draft is a single item or a plan with multiple items.
    """

    SINGLE_ITEM = "single_item"  # One ticket
    PLAN = "plan"  # Multiple items with structure


class DraftScope(str, Enum):
    """What to generate from this draft.

    Controls the generation scope - whether to create a single item,
    only epics, or a full plan with epics and stories.
    """

    SINGLE = "single"  # Just this one item
    EPICS_ONLY = "epics_only"  # Only epics, no stories
    FULL_PLAN = "full_plan"  # Epics + stories


class DraftItemStatus(str, Enum):
    """Lifecycle status of an individual draft item.

    Tracks whether an item is proposed, approved by user, or committed to Jira.
    """

    PROPOSED = "proposed"  # Just suggested
    APPROVED = "approved"  # User confirmed
    COMMITTED = "committed"  # Created in Jira


class DraftLifecycle(str, Enum):
    """Draft state machine - overall lifecycle of the draft.

    INTERNAL: 6 states for routing logic. Users never see these directly.
    See UserDraftState for the 3 user-facing states.

    State transitions:
    - EMPTY -> SINGLE_ITEM (when first item added)
    - EMPTY -> PLAN (when multiple items added)
    - SINGLE_ITEM -> PLAN (transform to plan)
    - PLAN -> PLAN_REFINED (user refined items)
    - SINGLE_ITEM | PLAN | PLAN_REFINED -> APPROVED (all items approved)
    - APPROVED -> COMMITTED (all items in Jira)
    """

    EMPTY = "empty"  # No content yet
    SINGLE_ITEM = "single_item"  # Working on single item
    PLAN = "plan"  # Multiple items proposed
    PLAN_REFINED = "plan_refined"  # User refined the plan
    APPROVED = "approved"  # All items approved
    COMMITTED = "committed"  # All items in Jira


class UserDraftState(str, Enum):
    """User-facing draft states.

    INVARIANT I5: Users see 3 states only.
    Internal DraftLifecycle has 6 states for routing.
    This enum is what users see in UI.

    | User State | Internal States |
    |------------|-----------------|
    | DRAFTING   | EMPTY, SINGLE_ITEM, PLAN, PLAN_REFINED |
    | READY      | APPROVED |
    | PUBLISHED  | COMMITTED |
    """

    DRAFTING = "drafting"  # Work in progress
    READY = "ready"  # Approved, waiting to publish
    PUBLISHED = "published"  # In Jira

    @property
    def label(self) -> str:
        """User-facing label."""
        return {
            UserDraftState.DRAFTING: "Draft in progress",
            UserDraftState.READY: "Ready to commit",
            UserDraftState.PUBLISHED: "Published to Jira",
        }[self]

    @property
    def color(self) -> str:
        """UI color for state."""
        return {
            UserDraftState.DRAFTING: "warning",  # Yellow
            UserDraftState.READY: "good",  # Green
            UserDraftState.PUBLISHED: "primary",  # Blue
        }[self]


def get_user_state(lifecycle: DraftLifecycle) -> UserDraftState:
    """Map internal lifecycle to user-facing state.

    INVARIANT I5: Internal complexity hidden from UI.

    | User State | Internal States |
    |------------|-----------------|
    | DRAFTING   | EMPTY, SINGLE_ITEM, PLAN, PLAN_REFINED |
    | READY      | APPROVED |
    | PUBLISHED  | COMMITTED |
    """
    if lifecycle == DraftLifecycle.COMMITTED:
        return UserDraftState.PUBLISHED
    elif lifecycle == DraftLifecycle.APPROVED:
        return UserDraftState.READY
    else:
        return UserDraftState.DRAFTING


# Valid lifecycle transitions
_VALID_TRANSITIONS: dict[DraftLifecycle, set[DraftLifecycle]] = {
    DraftLifecycle.EMPTY: {DraftLifecycle.SINGLE_ITEM, DraftLifecycle.PLAN},
    DraftLifecycle.SINGLE_ITEM: {
        DraftLifecycle.PLAN,
        DraftLifecycle.APPROVED,
        DraftLifecycle.EMPTY,  # Clear to start over
    },
    DraftLifecycle.PLAN: {
        DraftLifecycle.PLAN_REFINED,
        DraftLifecycle.APPROVED,
        DraftLifecycle.EMPTY,  # Clear to start over
    },
    DraftLifecycle.PLAN_REFINED: {
        DraftLifecycle.APPROVED,
        DraftLifecycle.PLAN,  # User changes mind, back to plan
        DraftLifecycle.EMPTY,  # Clear to start over
    },
    DraftLifecycle.APPROVED: {
        DraftLifecycle.COMMITTED,
        DraftLifecycle.PLAN_REFINED,  # User wants to refine before commit
        DraftLifecycle.SINGLE_ITEM,  # Revert to single item
        DraftLifecycle.PLAN,  # Revert to plan
    },
    DraftLifecycle.COMMITTED: set(),  # Terminal state, no transitions allowed
}


class DraftItem(BaseModel):
    """A single item in the draft - represents a ticket to be created.

    Can be an epic, story, task, or bug. Stories can have a parent_id
    linking them to an epic within the same draft.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this item within the draft",
    )
    issue_type: IssueType = Field(
        default=IssueType.STORY,
        description="Type of Jira issue: EPIC, STORY, TASK, BUG",
    )
    title: str = Field(
        default="",
        description="Title/summary of the item",
    )
    goal: str = Field(
        default="",
        description="What this item achieves - the purpose",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Technical or business constraints for this item",
    )
    status: DraftItemStatus = Field(
        default=DraftItemStatus.PROPOSED,
        description="Lifecycle status: proposed, approved, or committed",
    )
    parent_id: Optional[str] = Field(
        default=None,
        description="For stories under epics - references the epic's item ID",
    )

    # Carry over from TicketDraft for compatibility
    problem: str = Field(
        default="",
        description="What problem this item solves",
    )
    proposed_solution: str = Field(
        default="",
        description="Proposed approach to solve the problem",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria for determining when this item is complete",
    )

    # Jira reference (set after commit)
    jira_key: Optional[str] = Field(
        default=None,
        description="Jira issue key after creation (e.g., SCRUM-123)",
    )


class DraftChange(BaseModel):
    """Audit trail entry for draft changes.

    Tracks who changed what and when, enabling history review
    and potential rollback.
    """

    version: int = Field(
        description="Draft version at time of change",
    )
    action: str = Field(
        description="Type of change: transform_to_plan, add_item, approve_item, etc.",
    )
    by_user_id: str = Field(
        description="Slack user ID who made the change",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the change was made",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific data (item_id, old_value, new_value, etc.)",
    )


class StructuredDraft(BaseModel):
    """The main draft container - a typed, versioned design object.

    Replaces text-based TicketDraft with a typed design object that has:
    - Lifecycle states (empty -> single_item/plan -> approved -> committed)
    - Structural mutations (add/remove/transform items)
    - Change history for audit trail
    - Thread binding for Slack context

    This is the foundation for Phase 28 - the design object that replaces
    text-based draft collection.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this draft",
    )
    kind: DraftKind = Field(
        default=DraftKind.SINGLE_ITEM,
        description="Shape of draft: single_item or plan",
    )
    scope: DraftScope = Field(
        default=DraftScope.SINGLE,
        description="Generation scope: single, epics_only, or full_plan",
    )
    lifecycle: DraftLifecycle = Field(
        default=DraftLifecycle.EMPTY,
        description="Current lifecycle state",
    )
    version: int = Field(
        default=1,
        description="Version number, incremented on each change",
    )
    items: list[DraftItem] = Field(
        default_factory=list,
        description="Items in this draft",
    )
    change_log: list[DraftChange] = Field(
        default_factory=list,
        description="Audit trail of changes",
    )

    # Thread binding
    thread_ts: Optional[str] = Field(
        default=None,
        description="Slack thread timestamp for binding",
    )
    channel_id: Optional[str] = Field(
        default=None,
        description="Slack channel ID",
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When draft was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When draft was last modified",
    )
    created_by: Optional[str] = Field(
        default=None,
        description="Slack user ID who created the draft",
    )

    def is_empty(self) -> bool:
        """Check if draft has no meaningful content."""
        return len(self.items) == 0 or all(
            not item.title.strip() and not item.goal.strip() and not item.problem.strip()
            for item in self.items
        )

    @property
    def user_state(self) -> UserDraftState:
        """User-facing state (3 states, not 6).

        INVARIANT I5: Users see 3 states only.
        Maps internal lifecycle to user-facing UserDraftState.
        """
        return get_user_state(self.lifecycle)

    def get_primary_item(self) -> Optional[DraftItem]:
        """Get the primary item for SINGLE_ITEM kind drafts.

        Returns the first item if kind is SINGLE_ITEM, None otherwise.
        """
        if self.kind == DraftKind.SINGLE_ITEM and self.items:
            return self.items[0]
        return None

    def get_items_by_type(self, issue_type: IssueType) -> list[DraftItem]:
        """Get all items of a specific issue type."""
        return [item for item in self.items if item.issue_type == issue_type]

    def get_items_by_status(self, status: DraftItemStatus) -> list[DraftItem]:
        """Get all items with a specific status."""
        return [item for item in self.items if item.status == status]

    def log_change(
        self,
        action: str,
        user_id: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a change to the audit trail.

        Automatically increments version and updates timestamp.
        """
        self.change_log.append(
            DraftChange(
                version=self.version,
                action=action,
                by_user_id=user_id,
                details=details or {},
            )
        )
        self.version += 1
        self.updated_at = datetime.utcnow()

    def can_transition_to(self, target_lifecycle: DraftLifecycle) -> bool:
        """Check if transition to target lifecycle is valid.

        Enforces the state machine rules defined in _VALID_TRANSITIONS.
        """
        if self.lifecycle == target_lifecycle:
            return True  # No-op transition is always valid
        valid_targets = _VALID_TRANSITIONS.get(self.lifecycle, set())
        return target_lifecycle in valid_targets

    # =========================================================================
    # Structural Mutation Methods (Phase 28.3)
    # =========================================================================

    def split_to_plan(
        self, user_id: str, item_titles: list[str] | None = None
    ) -> dict[str, Any]:
        """Transform SINGLE_ITEM to PLAN with multiple items.

        If current draft has a single item, it becomes the first item in the plan.
        Additional items can be provided via item_titles.

        Returns dict with 'success', 'message', 'items_created'.
        """
        # Validate: must be SINGLE_ITEM or EMPTY
        if self.kind == DraftKind.PLAN:
            return {"success": False, "message": "Already a plan"}

        # If we have a primary item, keep it
        existing_items = list(self.items)

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
        self.kind = DraftKind.PLAN
        self.scope = DraftScope.EPICS_ONLY  # Default scope for plans
        self.items = existing_items

        # Update lifecycle
        if self.lifecycle in (DraftLifecycle.EMPTY, DraftLifecycle.SINGLE_ITEM):
            self.lifecycle = DraftLifecycle.PLAN

        # Log the change
        self.log_change(
            action="split_to_plan",
            user_id=user_id,
            details={"item_count": len(self.items), "new_titles": item_titles or []},
        )

        return {
            "success": True,
            "message": f"Transformed to plan with {len(self.items)} items",
            "items_created": len(item_titles or []),
        }

    def add_items(
        self,
        user_id: str,
        items_to_add: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add new items to the draft.

        items_to_add: list of dicts with 'title', 'issue_type', optional 'parent_id'

        Returns dict with 'success', 'message', 'items_added'.
        """
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
            self.items.append(new_item)
            added.append(new_item.id)

        # If we now have multiple items, upgrade to PLAN
        if len(self.items) > 1 and self.kind == DraftKind.SINGLE_ITEM:
            self.kind = DraftKind.PLAN
            if self.lifecycle == DraftLifecycle.SINGLE_ITEM:
                self.lifecycle = DraftLifecycle.PLAN

        self.log_change(
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
        self,
        user_id: str,
        item_ids: list[str],
        merged_title: str | None = None,
    ) -> dict[str, Any]:
        """Merge multiple items into one.

        Takes the first item as base, combines content from others,
        then removes the merged items.

        Returns dict with 'success', 'message', 'merged_item_id'.
        """
        if len(item_ids) < 2:
            return {"success": False, "message": "Need at least 2 items to merge"}

        # Find items to merge
        items_to_merge = [i for i in self.items if i.id in item_ids]
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
        self.items = [i for i in self.items if i.id not in merged_ids]

        # If we're down to 1 item, revert to SINGLE_ITEM
        if len(self.items) == 1:
            self.kind = DraftKind.SINGLE_ITEM
            if self.lifecycle == DraftLifecycle.PLAN:
                self.lifecycle = DraftLifecycle.SINGLE_ITEM

        self.log_change(
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
        self, user_id: str, item_id: str | None = None
    ) -> dict[str, Any]:
        """Change an item's type to EPIC.

        If item_id is None and draft is SINGLE_ITEM, elevates the primary item.

        Returns dict with 'success', 'message', 'item_id'.
        """
        # Find target item
        target = None
        if item_id:
            for item in self.items:
                if item.id == item_id:
                    target = item
                    break
        elif self.kind == DraftKind.SINGLE_ITEM and self.items:
            target = self.items[0]

        if not target:
            return {"success": False, "message": "Item not found"}

        if target.issue_type == IssueType.EPIC:
            return {"success": False, "message": "Item is already an epic"}

        old_type = target.issue_type
        target.issue_type = IssueType.EPIC

        self.log_change(
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
        self,
        user_id: str,
        epic_id: str | None = None,
        story_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create stories under an epic.

        If epic_id is None and draft has exactly one epic, uses that.
        Creates story items with parent_id pointing to the epic.

        Returns dict with 'success', 'message', 'stories_created'.
        """
        # Find target epic
        epic = None
        if epic_id:
            for item in self.items:
                if item.id == epic_id and item.issue_type == IssueType.EPIC:
                    epic = item
                    break
        else:
            # Find the only epic
            epics = [i for i in self.items if i.issue_type == IssueType.EPIC]
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
            self.items.append(story)
            created.append(story.id)

        # Upgrade to FULL_PLAN scope since we now have stories
        self.scope = DraftScope.FULL_PLAN

        # Ensure we're in PLAN kind
        if self.kind == DraftKind.SINGLE_ITEM:
            self.kind = DraftKind.PLAN
            if self.lifecycle == DraftLifecycle.SINGLE_ITEM:
                self.lifecycle = DraftLifecycle.PLAN

        self.log_change(
            action="decompose_to_stories",
            user_id=user_id,
            details={"epic_id": epic.id, "stories_created": created},
        )

        return {
            "success": True,
            "message": f"Created {len(created)} stories under epic",
            "stories_created": created,
        }

    def change_scope(self, user_id: str, new_scope: DraftScope) -> dict[str, Any]:
        """Change the generation scope of the draft.

        Returns dict with 'success', 'message', 'old_scope', 'new_scope'.
        """
        old_scope = self.scope

        if old_scope == new_scope:
            return {"success": False, "message": f"Already at scope {new_scope.value}"}

        self.scope = new_scope

        self.log_change(
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

    def remove_items(self, user_id: str, item_ids: list[str]) -> dict[str, Any]:
        """Remove items from the draft.

        Also removes any items that have a removed item as parent_id.

        Returns dict with 'success', 'message', 'removed_count'.
        """
        if not item_ids:
            return {"success": False, "message": "No items to remove"}

        # First pass: mark items for removal
        to_remove = set(item_ids)

        # Second pass: also remove children of removed items
        for item in self.items:
            if item.parent_id in to_remove:
                to_remove.add(item.id)

        # Remove items
        before_count = len(self.items)
        self.items = [i for i in self.items if i.id not in to_remove]
        removed_count = before_count - len(self.items)

        if removed_count == 0:
            return {"success": False, "message": "No items found to remove"}

        # If we're down to 0 or 1 item, adjust kind/lifecycle
        if len(self.items) == 0:
            self.kind = DraftKind.SINGLE_ITEM
            self.lifecycle = DraftLifecycle.EMPTY
        elif len(self.items) == 1:
            self.kind = DraftKind.SINGLE_ITEM
            if self.lifecycle in (DraftLifecycle.PLAN, DraftLifecycle.PLAN_REFINED):
                self.lifecycle = DraftLifecycle.SINGLE_ITEM

        self.log_change(
            action="remove_items",
            user_id=user_id,
            details={"removed_ids": list(to_remove), "count": removed_count},
        )

        return {
            "success": True,
            "message": f"Removed {removed_count} items",
            "removed_count": removed_count,
        }

    @classmethod
    def from_ticket_draft(
        cls,
        ticket_draft: "TicketDraft",
        user_id: str = "system",
    ) -> "StructuredDraft":
        """Convert legacy TicketDraft to StructuredDraft.

        Creates a SINGLE_ITEM draft with one DraftItem containing
        all the fields from the original TicketDraft.
        """
        from src.schemas.draft import RequestedScope

        # Create single item from ticket draft
        item = DraftItem(
            id=ticket_draft.id,
            issue_type=ticket_draft.issue_type or IssueType.STORY,
            title=ticket_draft.title,
            goal=ticket_draft.problem,  # Map problem -> goal
            problem=ticket_draft.problem,
            proposed_solution=ticket_draft.proposed_solution,
            acceptance_criteria=ticket_draft.acceptance_criteria.copy(),
            constraints=[c.value for c in ticket_draft.constraints],
            status=DraftItemStatus.PROPOSED,
        )

        # Determine lifecycle based on content
        lifecycle = DraftLifecycle.EMPTY
        if ticket_draft.title or ticket_draft.problem:
            lifecycle = DraftLifecycle.SINGLE_ITEM

        # Map requested_scope to DraftScope
        scope = DraftScope.SINGLE
        if ticket_draft.requested_scope:
            scope_map = {
                RequestedScope.EPICS_ONLY: DraftScope.EPICS_ONLY,
                RequestedScope.FULL_PLAN: DraftScope.FULL_PLAN,
                RequestedScope.SINGLE_ITEM: DraftScope.SINGLE,
            }
            scope = scope_map.get(ticket_draft.requested_scope, DraftScope.SINGLE)

        # Determine if items list should have content
        has_content = bool(item.title.strip())
        items_list = [item] if has_content else []

        return cls(
            id=str(uuid4()),  # New ID for structured draft
            kind=DraftKind.SINGLE_ITEM,
            scope=scope,
            lifecycle=lifecycle,
            version=ticket_draft.version,
            items=items_list,
            created_by=user_id,
            change_log=[
                DraftChange(
                    version=1,
                    action="migrated_from_ticket_draft",
                    by_user_id=user_id,
                    timestamp=datetime.utcnow(),
                    details={"original_id": ticket_draft.id},
                )
            ],
        )

    def to_ticket_draft(self) -> "TicketDraft":
        """Convert back to TicketDraft for legacy code paths.

        Only works for SINGLE_ITEM kind. Raises ValueError for PLAN.
        """
        from src.schemas.draft import (
            ConstraintStatus,
            DraftConstraint,
            RequestedScope,
            TicketDraft,
        )

        if self.kind == DraftKind.PLAN:
            raise ValueError("Cannot convert PLAN draft to single TicketDraft")

        item = self.get_primary_item()
        if not item:
            return TicketDraft()

        # Map scope back
        scope_map = {
            DraftScope.SINGLE: RequestedScope.SINGLE_ITEM,
            DraftScope.EPICS_ONLY: RequestedScope.EPICS_ONLY,
            DraftScope.FULL_PLAN: RequestedScope.FULL_PLAN,
        }

        return TicketDraft(
            id=item.id,
            title=item.title,
            problem=item.problem or item.goal,
            proposed_solution=item.proposed_solution,
            acceptance_criteria=item.acceptance_criteria.copy(),
            issue_type=item.issue_type,
            requested_scope=scope_map.get(self.scope),
            version=self.version,
            constraints=[
                DraftConstraint(key=c, value=c, status=ConstraintStatus.PROPOSED)
                for c in item.constraints
            ],
        )

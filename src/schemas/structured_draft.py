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
    # Delegated to draft_mutations module for modularity
    # =========================================================================

    def split_to_plan(
        self, user_id: str, item_titles: list[str] | None = None
    ) -> dict[str, Any]:
        """Transform SINGLE_ITEM to PLAN with multiple items.

        Delegates to draft_mutations.split_to_plan.
        """
        from src.schemas.draft_mutations import split_to_plan

        return split_to_plan(self, user_id, item_titles)

    def add_items(
        self,
        user_id: str,
        items_to_add: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add new items to the draft.

        Delegates to draft_mutations.add_items.
        """
        from src.schemas.draft_mutations import add_items

        return add_items(self, user_id, items_to_add)

    def merge_items(
        self,
        user_id: str,
        item_ids: list[str],
        merged_title: str | None = None,
    ) -> dict[str, Any]:
        """Merge multiple items into one.

        Delegates to draft_mutations.merge_items.
        """
        from src.schemas.draft_mutations import merge_items

        return merge_items(self, user_id, item_ids, merged_title)

    def elevate_to_epic(
        self, user_id: str, item_id: str | None = None
    ) -> dict[str, Any]:
        """Change an item's type to EPIC.

        Delegates to draft_mutations.elevate_to_epic.
        """
        from src.schemas.draft_mutations import elevate_to_epic

        return elevate_to_epic(self, user_id, item_id)

    def decompose_to_stories(
        self,
        user_id: str,
        epic_id: str | None = None,
        story_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create stories under an epic.

        Delegates to draft_mutations.decompose_to_stories.
        """
        from src.schemas.draft_mutations import decompose_to_stories

        return decompose_to_stories(self, user_id, epic_id, story_titles)

    def change_scope(self, user_id: str, new_scope: DraftScope) -> dict[str, Any]:
        """Change the generation scope of the draft.

        Delegates to draft_mutations.change_scope.
        """
        from src.schemas.draft_mutations import change_scope

        return change_scope(self, user_id, new_scope)

    def remove_items(self, user_id: str, item_ids: list[str]) -> dict[str, Any]:
        """Remove items from the draft.

        Delegates to draft_mutations.remove_items.
        """
        from src.schemas.draft_mutations import remove_items

        return remove_items(self, user_id, item_ids)

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

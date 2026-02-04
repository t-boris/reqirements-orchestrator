"""Channel aggregate root.

The Channel is the aggregate root for entities. All mutations to entities
flow through the channel, which emits events and maintains consistency.

Ref: Spec Part 5 - Channel Aggregate
Ref: BOT_DESIGN.md - "Channel as Aggregate Root"
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .content import DecisionContent, WorkItemContent
from .entities import (
    ApprovedEntity,
    CommittedEntity,
    DeprecatedEntity,
    DraftEntity,
    Entity,
    ProposedEntity,
    get_lifecycle,
)
from .events import (
    ApprovalAdded,
    DecisionAmended,
    DecisionApproved,
    DecisionCommitted,
    DecisionDeprecated,
    DecisionProposed,
    DecisionRecorded,
    DomainEvent,
    ObjectionRaised,
    ObjectionResolved,
    ObjectionWithdrawn,
    WorkItemApproved,
    WorkItemCommitted,
    WorkItemDrafted,
    WorkItemProposed,
    WorkItemUpdated,
)
from .transitions import (
    TransitionError,
    add_approval,
    approve,
    can_modify,
    commit,
    deprecate,
    has_active_objections,
    propose,
    raise_objection,
    resolve_objection,
    withdraw_objection,
)
from .types import (
    ChannelId,
    EntityId,
    EntityType,
    JiraKey,
    ThreadTs,
    UserId,
    Version,
)


class EntityNotFoundError(Exception):
    """Entity not found in channel."""

    pass


class InvalidStateError(Exception):
    """Entity is in wrong state for operation."""

    pass


@dataclass
class ChannelAggregate:
    """Aggregate root for a Slack channel.

    Owns all entities in the channel and coordinates mutations.
    Mutations emit events and update entity state atomically.

    Attributes:
        channel_id: The Slack channel ID
        entities: Map of entity ID to current entity state
        version: Aggregate version (increments with each event)
        pending_events: Events emitted but not yet persisted
    """

    channel_id: ChannelId
    entities: dict[EntityId, Entity] = field(default_factory=dict)
    version: int = -1
    pending_events: list[DomainEvent] = field(default_factory=list)

    @property
    def next_version(self) -> int:
        """Return the version number for the next event to be emitted."""
        return self.version + 1

    def _emit(self, event: DomainEvent) -> None:
        """Record event to pending list."""
        self.pending_events.append(event)
        self.version += 1

    def clear_pending_events(self) -> list[DomainEvent]:
        """Clear and return pending events (after persistence)."""
        events = self.pending_events
        self.pending_events = []
        return events

    # =========================================================================
    # Work Item Operations
    # =========================================================================

    def draft_work_item(
        self,
        actor_id: UserId,
        thread_ts: ThreadTs,
        content: WorkItemContent,
        entity_id: EntityId | None = None,
    ) -> DraftEntity:
        """Create a draft work item.

        Args:
            actor_id: User creating the draft
            thread_ts: Thread where draft was created
            content: Work item content
            entity_id: Optional entity ID (generated if not provided)

        Returns:
            The created draft entity
        """
        from .content import Attribution

        entity_id = entity_id or EntityId.generate()

        # Create draft entity
        draft = DraftEntity(
            id=entity_id,
            entity_type=EntityType.WORK_ITEM,
            channel_id=self.channel_id,
            thread_ts=thread_ts,
            content=content,
            attribution=Attribution(
                proposed_by=actor_id,
                proposed_at=datetime.utcnow(),
            ),
            version=Version(1),
        )

        # Emit event
        self._emit(
            WorkItemDrafted(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                thread_ts=thread_ts,
                content=content.model_dump(),
            )
        )

        # Update state
        self.entities[entity_id] = draft
        return draft

    def propose_work_item(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        canonical_message_ts: str,
    ) -> ProposedEntity:
        """Propose a draft work item for approval.

        Args:
            entity_id: ID of draft to propose
            actor_id: User proposing
            canonical_message_ts: Slack message representing the proposal

        Returns:
            The proposed entity

        Raises:
            EntityNotFoundError: If entity doesn't exist
            InvalidStateError: If entity is not a draft
        """
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, DraftEntity):
            raise InvalidStateError(f"Entity must be draft, is {type(entity).__name__}")

        # Apply transition
        proposed = propose(entity, canonical_message_ts)

        # Emit event
        self._emit(
            WorkItemProposed(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                canonical_message_ts=canonical_message_ts,
            )
        )

        # Update state
        self.entities[entity_id] = proposed
        return proposed

    def approve_work_item(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        comment: str | None = None,
    ) -> ProposedEntity | ApprovedEntity:
        """Add approval to a proposed work item.

        If this approval meets the threshold, transitions to Approved.

        Args:
            entity_id: ID of proposed entity
            actor_id: User approving
            comment: Optional approval comment

        Returns:
            Updated entity (still Proposed or now Approved)

        Raises:
            EntityNotFoundError: If entity doesn't exist
            InvalidStateError: If entity is not proposed
            TransitionError: If user already approved
        """
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ProposedEntity):
            raise InvalidStateError(f"Entity must be proposed, is {type(entity).__name__}")

        # Add approval
        updated = add_approval(entity, actor_id, comment)

        # Emit approval event
        self._emit(
            ApprovalAdded(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                approved_by=actor_id,
                comment=comment,
            )
        )

        # Check if we should auto-transition to Approved
        # Default: 1 approval needed, no active objections
        if len(updated.approvals) >= 1 and not has_active_objections(updated):
            approved = approve(updated, actor_id, min_approvals=1)

            self._emit(
                WorkItemApproved(
                    aggregate_id=self.channel_id,
                    actor_id=actor_id,
                    version=self.next_version,
                    entity_id=entity_id,
                    approved_by=actor_id,
                )
            )

            self.entities[entity_id] = approved
            return approved

        self.entities[entity_id] = updated
        return updated

    def commit_work_item(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        jira_key: JiraKey,
    ) -> CommittedEntity:
        """Commit approved work item to Jira.

        Args:
            entity_id: ID of approved entity
            actor_id: User committing
            jira_key: Jira issue key

        Returns:
            Committed entity with JiraLink

        Raises:
            EntityNotFoundError: If entity doesn't exist
            InvalidStateError: If entity is not approved
        """
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ApprovedEntity):
            raise InvalidStateError(f"Entity must be approved, is {type(entity).__name__}")

        # Apply transition
        committed = commit(entity, jira_key)

        # Emit event
        self._emit(
            WorkItemCommitted(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                jira_key=jira_key,
            )
        )

        # Update state
        self.entities[entity_id] = committed
        return committed

    # =========================================================================
    # Decision Operations
    # =========================================================================

    def record_decision(
        self,
        actor_id: UserId,
        thread_ts: ThreadTs,
        content: DecisionContent,
        entity_id: EntityId | None = None,
        adr_message_ts: str | None = None,
    ) -> DraftEntity:
        """Record a decision from conversation.

        Args:
            actor_id: User recording the decision
            thread_ts: Thread where decision was made
            content: Decision content
            entity_id: Optional entity ID
            adr_message_ts: Optional timestamp of the pinned ADR message

        Returns:
            Draft decision entity
        """
        from .content import Attribution

        entity_id = entity_id or EntityId.generate()

        draft = DraftEntity(
            id=entity_id,
            entity_type=EntityType.DECISION,
            channel_id=self.channel_id,
            thread_ts=thread_ts,
            content=content,
            attribution=Attribution(
                proposed_by=actor_id,
                proposed_at=datetime.utcnow(),
            ),
            version=Version(1),
            adr_message_ts=adr_message_ts,
        )

        self._emit(
            DecisionRecorded(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                thread_ts=thread_ts,
                content=content.model_dump(),
                adr_message_ts=adr_message_ts,
            )
        )

        self.entities[entity_id] = draft
        return draft

    def amend_decision(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        new_content: DecisionContent,
        reason: str,
        new_adr_message_ts: str | None = None,
    ) -> DraftEntity | ProposedEntity:
        """Amend a decision's content in-place while preserving event history.

        Works for Draft and Proposed entities. Creates a new entity instance
        with updated content and incremented version (entities are frozen).

        Args:
            entity_id: ID of the decision to amend
            actor_id: User amending the decision
            new_content: Updated decision content
            reason: Reason for the amendment
            new_adr_message_ts: Optional new ADR message timestamp

        Returns:
            Updated entity (same type as input)

        Raises:
            EntityNotFoundError: If entity doesn't exist
            InvalidStateError: If entity is not Draft or Proposed
        """
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        modifiable, err = can_modify(entity)
        if not modifiable:
            raise InvalidStateError(err)

        previous_content = entity.content

        if isinstance(entity, DraftEntity):
            updated = DraftEntity(
                id=entity.id,
                entity_type=entity.entity_type,
                channel_id=entity.channel_id,
                thread_ts=entity.thread_ts,
                content=new_content,
                attribution=entity.attribution,
                version=Version(entity.version + 1),
                adr_message_ts=new_adr_message_ts if new_adr_message_ts else entity.adr_message_ts,
            )
        elif isinstance(entity, ProposedEntity):
            updated = ProposedEntity(
                id=entity.id,
                entity_type=entity.entity_type,
                channel_id=entity.channel_id,
                thread_ts=entity.thread_ts,
                content=new_content,
                attribution=entity.attribution,
                version=Version(entity.version + 1),
                canonical_message_ts=entity.canonical_message_ts,
                adr_message_ts=new_adr_message_ts if new_adr_message_ts else entity.adr_message_ts,
                approvals=entity.approvals,
                objections=entity.objections,
            )
        else:
            raise InvalidStateError(f"Entity is {type(entity).__name__}, only Draft/Proposed can be amended")

        self._emit(
            DecisionAmended(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                previous_content=previous_content,
                new_content=new_content,
                reason=reason,
                new_adr_message_ts=new_adr_message_ts,
            )
        )

        self.entities[entity_id] = updated
        return updated

    def propose_decision(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        canonical_message_ts: str,
    ) -> ProposedEntity:
        """Propose a draft decision for approval."""
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, DraftEntity):
            raise InvalidStateError(f"Entity must be draft, is {type(entity).__name__}")

        proposed = propose(entity, canonical_message_ts)

        self._emit(
            DecisionProposed(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                canonical_message_ts=canonical_message_ts,
            )
        )

        self.entities[entity_id] = proposed
        return proposed

    def approve_decision(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        comment: str | None = None,
    ) -> ProposedEntity | ApprovedEntity:
        """Add approval to a proposed decision."""
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ProposedEntity):
            raise InvalidStateError(f"Entity must be proposed, is {type(entity).__name__}")

        updated = add_approval(entity, actor_id, comment)

        self._emit(
            ApprovalAdded(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                approved_by=actor_id,
                comment=comment,
            )
        )

        if len(updated.approvals) >= 1 and not has_active_objections(updated):
            approved = approve(updated, actor_id, min_approvals=1)

            self._emit(
                DecisionApproved(
                    aggregate_id=self.channel_id,
                    actor_id=actor_id,
                    version=self.next_version,
                    entity_id=entity_id,
                    approved_by=actor_id,
                )
            )

            self.entities[entity_id] = approved
            return approved

        self.entities[entity_id] = updated
        return updated

    def commit_decision(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        jira_key: JiraKey,
        field_path: str,
    ) -> CommittedEntity:
        """Commit approved decision to Jira."""
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ApprovedEntity):
            raise InvalidStateError(f"Entity must be approved, is {type(entity).__name__}")

        committed = commit(entity, jira_key, field_path)

        self._emit(
            DecisionCommitted(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                jira_key=jira_key,
                field_path=field_path,
            )
        )

        self.entities[entity_id] = committed
        return committed

    def deprecate_decision(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        reason: str,
        superseded_by: EntityId | None = None,
    ) -> DeprecatedEntity:
        """Deprecate a committed decision."""
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, CommittedEntity):
            raise InvalidStateError(f"Entity must be committed, is {type(entity).__name__}")

        deprecated = deprecate(entity, superseded_by)

        self._emit(
            DecisionDeprecated(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                superseded_by=superseded_by,
                reason=reason,
            )
        )

        self.entities[entity_id] = deprecated
        return deprecated

    # =========================================================================
    # Objection Operations (work on any proposed entity)
    # =========================================================================

    def raise_entity_objection(
        self,
        entity_id: EntityId,
        actor_id: UserId,
        reason: str,
    ) -> ProposedEntity:
        """Raise an objection against a proposed entity.

        Args:
            entity_id: ID of proposed entity
            actor_id: User raising objection
            reason: Reason for objection

        Returns:
            Updated proposed entity with new objection
        """
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ProposedEntity):
            raise InvalidStateError(f"Entity must be proposed, is {type(entity).__name__}")

        updated = raise_objection(entity, actor_id, reason)

        self._emit(
            ObjectionRaised(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                objected_by=actor_id,
                reason=reason,
            )
        )

        self.entities[entity_id] = updated
        return updated

    def resolve_entity_objection(
        self,
        entity_id: EntityId,
        objection_index: int,
        actor_id: UserId,
        resolution: str,
    ) -> ProposedEntity:
        """Resolve an objection on a proposed entity."""
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ProposedEntity):
            raise InvalidStateError(f"Entity must be proposed, is {type(entity).__name__}")

        updated = resolve_objection(entity, objection_index, actor_id, resolution)

        self._emit(
            ObjectionResolved(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                objection_index=objection_index,
                resolved_by=actor_id,
                resolution=resolution,
            )
        )

        self.entities[entity_id] = updated
        return updated

    def withdraw_entity_objection(
        self,
        entity_id: EntityId,
        objection_index: int,
        actor_id: UserId,
    ) -> ProposedEntity:
        """Withdraw an objection (by the original objector)."""
        entity = self.entities.get(entity_id)
        if not entity:
            raise EntityNotFoundError(f"Entity {entity_id} not found")

        if not isinstance(entity, ProposedEntity):
            raise InvalidStateError(f"Entity must be proposed, is {type(entity).__name__}")

        updated = withdraw_objection(entity, objection_index, actor_id)

        self._emit(
            ObjectionWithdrawn(
                aggregate_id=self.channel_id,
                actor_id=actor_id,
                version=self.next_version,
                entity_id=entity_id,
                objection_index=objection_index,
                withdrawn_by=actor_id,
            )
        )

        self.entities[entity_id] = updated
        return updated

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_entity(self, entity_id: EntityId) -> Entity | None:
        """Get entity by ID."""
        return self.entities.get(entity_id)

    def get_entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        """Get all entities of a given type."""
        return [e for e in self.entities.values() if e.entity_type == entity_type]

    def get_pending_approvals(self) -> list[ProposedEntity]:
        """Get all entities pending approval."""
        return [e for e in self.entities.values() if isinstance(e, ProposedEntity)]

    def get_entities_in_thread(self, thread_ts: ThreadTs) -> list[Entity]:
        """Get all entities in a specific thread."""
        return [e for e in self.entities.values() if e.thread_ts == thread_ts]

    # =========================================================================
    # Event Replay (for rebuilding state from events)
    # =========================================================================

    @classmethod
    def from_events(cls, channel_id: ChannelId, events: list[DomainEvent]) -> "ChannelAggregate":
        """Rebuild aggregate state from events.

        Args:
            channel_id: The channel ID
            events: List of events to replay

        Returns:
            ChannelAggregate with state rebuilt from events
        """
        aggregate = cls(channel_id=channel_id)

        for event in events:
            aggregate._apply_event(event)

        return aggregate

    def _apply_event(self, event: DomainEvent) -> None:
        """Apply a single event to rebuild state.

        This is used during replay and should match the state changes
        made by the command methods.
        """
        from .content import Attribution

        match event:
            case WorkItemDrafted():
                self.entities[event.entity_id] = DraftEntity(
                    id=EntityId(event.entity_id),
                    entity_type=EntityType.WORK_ITEM,
                    channel_id=ChannelId(event.aggregate_id),
                    thread_ts=ThreadTs(event.thread_ts),
                    content=WorkItemContent(**event.content),
                    attribution=Attribution(
                        proposed_by=UserId(event.actor_id),
                        proposed_at=event.timestamp,
                    ),
                    version=Version(1),
                )

            case WorkItemProposed():
                draft = self.entities[EntityId(event.entity_id)]
                self.entities[EntityId(event.entity_id)] = propose(draft, event.canonical_message_ts)

            case ApprovalAdded():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = add_approval(
                        entity, UserId(event.approved_by), event.comment
                    )

            case WorkItemApproved():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = approve(
                        entity, UserId(event.approved_by), min_approvals=0
                    )

            case WorkItemCommitted():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ApprovedEntity):
                    self.entities[EntityId(event.entity_id)] = commit(entity, JiraKey(event.jira_key))

            case DecisionRecorded():
                self.entities[event.entity_id] = DraftEntity(
                    id=EntityId(event.entity_id),
                    entity_type=EntityType.DECISION,
                    channel_id=ChannelId(event.aggregate_id),
                    thread_ts=ThreadTs(event.thread_ts),
                    content=DecisionContent(**event.content),
                    attribution=Attribution(
                        proposed_by=UserId(event.actor_id),
                        proposed_at=event.timestamp,
                    ),
                    version=Version(1),
                    adr_message_ts=getattr(event, 'adr_message_ts', None),
                )

            case DecisionAmended():
                existing = self.entities.get(EntityId(event.entity_id))
                if isinstance(existing, DraftEntity):
                    self.entities[EntityId(event.entity_id)] = DraftEntity(
                        id=existing.id,
                        entity_type=existing.entity_type,
                        channel_id=existing.channel_id,
                        thread_ts=existing.thread_ts,
                        content=DecisionContent(**event.new_content) if isinstance(event.new_content, dict) else event.new_content,
                        attribution=existing.attribution,
                        version=Version(existing.version + 1),
                        adr_message_ts=event.new_adr_message_ts if event.new_adr_message_ts else existing.adr_message_ts,
                    )
                elif isinstance(existing, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = ProposedEntity(
                        id=existing.id,
                        entity_type=existing.entity_type,
                        channel_id=existing.channel_id,
                        thread_ts=existing.thread_ts,
                        content=DecisionContent(**event.new_content) if isinstance(event.new_content, dict) else event.new_content,
                        attribution=existing.attribution,
                        version=Version(existing.version + 1),
                        canonical_message_ts=existing.canonical_message_ts,
                        adr_message_ts=event.new_adr_message_ts if event.new_adr_message_ts else existing.adr_message_ts,
                        approvals=existing.approvals,
                        objections=existing.objections,
                    )

            case DecisionProposed():
                draft = self.entities[EntityId(event.entity_id)]
                self.entities[EntityId(event.entity_id)] = propose(draft, event.canonical_message_ts)

            case DecisionApproved():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = approve(
                        entity, UserId(event.approved_by), min_approvals=0
                    )

            case DecisionCommitted():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ApprovedEntity):
                    self.entities[EntityId(event.entity_id)] = commit(
                        entity, JiraKey(event.jira_key), event.field_path
                    )

            case DecisionDeprecated():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, CommittedEntity):
                    superseded = EntityId(event.superseded_by) if event.superseded_by else None
                    self.entities[EntityId(event.entity_id)] = deprecate(entity, superseded)

            case ObjectionRaised():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = raise_objection(
                        entity, UserId(event.objected_by), event.reason
                    )

            case ObjectionResolved():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = resolve_objection(
                        entity, event.objection_index, UserId(event.resolved_by), event.resolution
                    )

            case ObjectionWithdrawn():
                entity = self.entities[EntityId(event.entity_id)]
                if isinstance(entity, ProposedEntity):
                    self.entities[EntityId(event.entity_id)] = withdraw_objection(
                        entity, event.objection_index, UserId(event.withdrawn_by)
                    )

        self.version = event.version

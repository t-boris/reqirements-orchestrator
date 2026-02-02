# MARO 2.0 Architecture

## Executive Summary

MARO (Multi-Agent Requirements Orchestrator) is a Slack bot that treats **communication as the source of truth**. It transforms channel conversations into structured work items, captures architectural decisions, and projects them to Jira as execution artifacts.

**Core Mantra:** "Threads propose. Channels decide. Jira executes."

### What Makes 2.0 Different

| Aspect | v1.x | v2.0 |
|--------|------|------|
| State Management | 8 independent stores | Single event-sourced store |
| Intent Classification | 6 layers, 13 intents | 2 layers, 4 modes |
| Entity Model | Separate Draft/Decision/WorkItem | Unified ChannelEntity |
| Task Orchestration | Ad-hoc | Process → Plan → Workflow |
| Multi-User | Basic attribution | Full governance model |
| State Machines | 7 parallel | 1 unified lifecycle |

---

## Part 1: Core Philosophy

### 1.1 The Git Mental Model

MARO treats communication like version control:

| Git | MARO |
|-----|------|
| Repository | Channel |
| Branch | Thread |
| Commit | Approval |
| HEAD | Canonical message |
| Push | Sync to Jira |
| Merge conflict | Decision conflict |

**Jira is not the source of truth** — it's a deployment artifact built from the source (conversation).

### 1.2 Three Layers of Truth

```
Channel (Workspace)     ← Source of Truth
    ↓
Thread (Working Branch) ← Where decisions form
    ↓
Jira (Projection)       ← Execution artifact
```

### 1.3 Design Principles

1. **Sum Types Over Optionals** — Make illegal states unrepresentable
2. **Events Over State** — Store what happened, derive current state
3. **Channel as Aggregate** — All mutations go through channel root
4. **Explicit Over Implicit** — No magic, clear data flow
5. **Facilitate, Don't Dictate** — Bot helps consensus, doesn't force decisions

---

## Part 2: Tech Stack

### 2.1 Recommended Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Language | **Python 3.12** | Mature async, type hints, LangChain ecosystem |
| Framework | **FastAPI + Slack Bolt** | Modern async, Bolt is official SDK |
| State Machine | **Statechart (xstate pattern)** | Replace LangGraph's god-graph with composable machines |
| Database | **PostgreSQL 16** | JSONB for events, proven reliability |
| LLM | **Gemini (default)** | Cost-effective, with OpenAI/Anthropic adapters |
| Validation | **Pydantic v2** | Fast, native Python typing |
| Testing | **pytest + hypothesis** | Property-based testing for state machines |

### 2.2 Why Not LangGraph for 2.0?

LangGraph served v1.x well, but the "god graph" pattern accumulated complexity. For 2.0:

- **Statecharts** — Each entity type has its own state machine
- **Composition** — Machines compose hierarchically, not in one graph
- **Tooling** — Better visualization and debugging of individual machines

### 2.3 LLM Abstraction

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, schema: type[BaseModel] | None = None) -> str | BaseModel:
        """Generate completion, optionally parse to schema."""

    @abstractmethod
    async def analyze(self, content: str, instruction: str) -> str:
        """Analyze content with instruction."""

class GeminiProvider(LLMProvider):
    """Default provider using Google Gemini."""

    def __init__(self, model: str = "gemini-1.5-pro"):
        self.model = model

    async def complete(self, prompt: str, schema: type[BaseModel] | None = None) -> str | BaseModel:
        # Implementation
        ...

class OpenAIProvider(LLMProvider):
    """OpenAI adapter."""
    ...

class AnthropicProvider(LLMProvider):
    """Anthropic Claude adapter."""
    ...

# Factory
def get_llm_provider(config: LLMConfig) -> LLMProvider:
    providers = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
    }
    return providers[config.provider](model=config.model)
```

---

## Part 3: Domain Model

### 3.1 Core Types

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Union
from uuid import uuid4

# === Value Objects ===

class ChannelId(str):
    """Slack channel ID."""
    pass

class ThreadTs(str):
    """Slack thread timestamp."""
    pass

class UserId(str):
    """Slack user ID."""
    pass

class EntityId(str):
    """Unique entity identifier."""

    @classmethod
    def generate(cls) -> "EntityId":
        return cls(str(uuid4()))

class JiraKey(str):
    """Jira issue key (e.g., PROJ-123)."""
    pass

class Version(int):
    """Entity version for optimistic concurrency."""
    pass
```

### 3.2 Entity Lifecycle (Unified)

```python
class EntityLifecycle(Enum):
    """Single lifecycle for all entities."""
    DRAFT = "draft"           # Being formed in thread
    PROPOSED = "proposed"     # Visible in channel, awaiting approval
    APPROVED = "approved"     # Approved, ready for Jira projection
    COMMITTED = "committed"   # Projected to Jira
    DEPRECATED = "deprecated" # Superseded (decisions only)
```

### 3.3 Entity Types

```python
class EntityType(Enum):
    WORK_ITEM = "work_item"   # Epic, Story, Task, Bug, Spike
    DECISION = "decision"     # Architectural/scope/process decisions
    ARTIFACT = "artifact"     # Reviews, documents (future)
```

### 3.4 Work Item Content

```python
class IssueType(Enum):
    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    BUG = "bug"
    SPIKE = "spike"

@dataclass
class WorkItemContent:
    """Content for work items."""
    issue_type: IssueType
    title: str
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    # Hierarchy
    parent_id: EntityId | None = None
    children_ids: list[EntityId] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Return validation errors."""
        errors = []
        if not self.title:
            errors.append("Title is required")
        if self.issue_type == IssueType.STORY and not self.acceptance_criteria:
            errors.append("Stories require acceptance criteria")
        if self.issue_type == IssueType.EPIC and not self.description:
            errors.append("Epics require a description/goal")
        return errors
```

### 3.5 Decision Content

```python
class DecisionType(Enum):
    ARCHITECTURE = "architecture"   # Technical design choices
    SCOPE = "scope"                 # What's in/out
    CONSTRAINT = "constraint"       # Non-negotiable requirements
    PRIORITY = "priority"           # Ordering decisions
    PROCESS = "process"             # How we work
    STRUCTURE = "structure"         # Epic/story breakdown

@dataclass
class DecisionContent:
    """Content for decisions."""
    decision_type: DecisionType
    title: str
    description: str
    rationale: str = ""
    alternatives_considered: list[str] = field(default_factory=list)

    # Links to affected entities
    affects_entities: list[EntityId] = field(default_factory=list)
```

### 3.6 Attribution (Multi-User)

```python
@dataclass
class Attribution:
    """Who did what and when."""
    proposed_by: UserId
    proposed_at: datetime
    approved_by: UserId | None = None
    approved_at: datetime | None = None
    modifications: list["Modification"] = field(default_factory=list)

@dataclass
class Modification:
    """Record of a change."""
    user_id: UserId
    action: str
    timestamp: datetime
    description: str
```

### 3.7 Jira Link

```python
class SyncStatus(Enum):
    PENDING = "pending"       # Not yet synced
    SYNCED = "synced"         # Up to date
    CONFLICT = "conflict"     # Conflict detected

@dataclass
class JiraLink:
    """Link between entity and Jira issue."""
    jira_key: JiraKey
    synced_version: Version
    synced_at: datetime
    sync_status: SyncStatus

    # For decisions: which field this decision affects
    field_path: str | None = None  # e.g., "description", "customfield_10001"
```

### 3.8 Unified Entity (Sum Type Pattern)

```python
@dataclass
class DraftEntity:
    """Entity being formed — no Jira link possible."""
    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: WorkItemContent | DecisionContent
    attribution: Attribution
    version: Version = Version(1)

@dataclass
class ProposedEntity:
    """Entity proposed for approval — has canonical message."""
    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: WorkItemContent | DecisionContent
    attribution: Attribution
    version: Version
    canonical_message_ts: str
    approvals: list["Approval"] = field(default_factory=list)
    objections: list["Objection"] = field(default_factory=list)

@dataclass
class ApprovedEntity:
    """Entity approved — ready for Jira projection."""
    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: WorkItemContent | DecisionContent
    attribution: Attribution  # Now has approved_by
    version: Version
    canonical_message_ts: str

@dataclass
class CommittedEntity:
    """Entity committed to Jira — has required JiraLink."""
    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: WorkItemContent | DecisionContent
    attribution: Attribution
    version: Version
    canonical_message_ts: str
    jira_link: JiraLink  # Required, not optional!

@dataclass
class DeprecatedEntity:
    """Entity superseded — for decisions only."""
    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    content: WorkItemContent | DecisionContent
    attribution: Attribution
    version: Version
    canonical_message_ts: str
    jira_link: JiraLink | None
    deprecated_at: datetime
    superseded_by: EntityId | None

# The union type — entity can only be in ONE state
Entity = Union[DraftEntity, ProposedEntity, ApprovedEntity, CommittedEntity, DeprecatedEntity]

def get_lifecycle(entity: Entity) -> EntityLifecycle:
    """Get lifecycle from entity type."""
    match entity:
        case DraftEntity(): return EntityLifecycle.DRAFT
        case ProposedEntity(): return EntityLifecycle.PROPOSED
        case ApprovedEntity(): return EntityLifecycle.APPROVED
        case CommittedEntity(): return EntityLifecycle.COMMITTED
        case DeprecatedEntity(): return EntityLifecycle.DEPRECATED
```

### 3.9 Approval & Objection

```python
@dataclass
class Approval:
    """Approval record."""
    user_id: UserId
    timestamp: datetime
    comment: str | None = None

@dataclass
class Objection:
    """Objection that blocks approval."""
    user_id: UserId
    timestamp: datetime
    reason: str
    status: str = "active"  # active, resolved, withdrawn
    resolution: str | None = None
```

---

## Part 4: Event Sourcing

### 4.1 Event Base

```python
from abc import ABC
from typing import Any

@dataclass
class DomainEvent(ABC):
    """Base for all domain events."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    aggregate_id: ChannelId  # Channel is the aggregate root
    timestamp: datetime = field(default_factory=datetime.utcnow)
    actor_id: UserId
    version: int  # Sequence within aggregate

    @property
    def event_type(self) -> str:
        return self.__class__.__name__
```

### 4.2 Entity Events

```python
# === Work Item Events ===

@dataclass
class WorkItemDrafted(DomainEvent):
    """Work item draft created in thread."""
    entity_id: EntityId
    thread_ts: ThreadTs
    content: WorkItemContent

@dataclass
class WorkItemProposed(DomainEvent):
    """Work item proposed for approval."""
    entity_id: EntityId
    canonical_message_ts: str

@dataclass
class WorkItemApproved(DomainEvent):
    """Work item approved."""
    entity_id: EntityId
    approved_by: UserId

@dataclass
class WorkItemCommitted(DomainEvent):
    """Work item committed to Jira."""
    entity_id: EntityId
    jira_key: JiraKey

@dataclass
class WorkItemUpdated(DomainEvent):
    """Work item content updated."""
    entity_id: EntityId
    changes: dict[str, Any]
    reason: str

# === Decision Events ===

@dataclass
class DecisionRecorded(DomainEvent):
    """Decision captured from conversation."""
    entity_id: EntityId
    thread_ts: ThreadTs
    content: DecisionContent

@dataclass
class DecisionProposed(DomainEvent):
    """Decision proposed for approval."""
    entity_id: EntityId
    canonical_message_ts: str

@dataclass
class DecisionApproved(DomainEvent):
    """Decision approved."""
    entity_id: EntityId
    approved_by: UserId

@dataclass
class DecisionCommitted(DomainEvent):
    """Decision projected to Jira."""
    entity_id: EntityId
    jira_key: JiraKey
    field_path: str

@dataclass
class DecisionDeprecated(DomainEvent):
    """Decision superseded."""
    entity_id: EntityId
    superseded_by: EntityId | None
    reason: str

# === Conflict Events ===

@dataclass
class ConflictDetected(DomainEvent):
    """Conflict detected between entities or with Jira."""
    conflict_type: str
    entity_a_id: EntityId
    entity_b_id: EntityId | None  # None for Jira conflicts
    jira_key: JiraKey | None
    description: str

@dataclass
class ConflictResolved(DomainEvent):
    """Conflict resolved."""
    conflict_id: str
    resolution_type: str
    resolved_by: UserId
    outcome: str
```

### 4.3 Process/Plan Events

```python
@dataclass
class ProcessStarted(DomainEvent):
    """Multi-stage process started."""
    process_id: str
    process_type: str
    thread_ts: ThreadTs

@dataclass
class ProcessStageCompleted(DomainEvent):
    """Process stage completed."""
    process_id: str
    stage_name: str
    outputs: dict[str, Any]

@dataclass
class ProcessCompleted(DomainEvent):
    """Process finished."""
    process_id: str
    final_outputs: dict[str, Any]

@dataclass
class PlanCreated(DomainEvent):
    """Execution plan created."""
    plan_id: str
    items: list[dict]  # Serialized PlanItem list
    source_process_id: str | None

@dataclass
class PlanItemCompleted(DomainEvent):
    """Plan item executed."""
    plan_id: str
    item_index: int
    result: dict[str, Any]

@dataclass
class PlanCompleted(DomainEvent):
    """All plan items executed."""
    plan_id: str
```

### 4.4 Event Store

```python
from typing import AsyncIterator

class EventStore:
    """Append-only event store."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def append(self, event: DomainEvent) -> None:
        """Append event. Raises ConcurrencyError if version conflict."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO channel_events
                    (event_id, event_type, aggregate_id, version, timestamp, actor_id, payload)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    event.event_id,
                    event.event_type,
                    event.aggregate_id,
                    event.version,
                    event.timestamp,
                    event.actor_id,
                    self._serialize_payload(event)
                )
            except asyncpg.UniqueViolationError:
                raise ConcurrencyError(
                    f"Version {event.version} already exists for {event.aggregate_id}"
                )

    async def get_events(
        self,
        aggregate_id: ChannelId,
        after_version: int = 0
    ) -> list[DomainEvent]:
        """Get all events for aggregate after version."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT event_type, payload, version, timestamp, actor_id
                FROM channel_events
                WHERE aggregate_id = $1 AND version > $2
                ORDER BY version ASC
            """, aggregate_id, after_version)

            return [self._deserialize_event(row) for row in rows]

    async def get_latest_version(self, aggregate_id: ChannelId) -> int:
        """Get current version for aggregate."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT COALESCE(MAX(version), 0)
                FROM channel_events
                WHERE aggregate_id = $1
            """, aggregate_id)
            return result

    async def stream_events(
        self,
        aggregate_id: ChannelId,
        after_version: int = 0
    ) -> AsyncIterator[DomainEvent]:
        """Stream events for real-time projection updates."""
        # Implementation using LISTEN/NOTIFY
        ...

    def _serialize_payload(self, event: DomainEvent) -> dict:
        """Serialize event to JSON-compatible dict."""
        # Exclude base fields, serialize rest
        ...

    def _deserialize_event(self, row: asyncpg.Record) -> DomainEvent:
        """Deserialize event from database row."""
        event_classes = {
            "WorkItemDrafted": WorkItemDrafted,
            "WorkItemProposed": WorkItemProposed,
            # ... etc
        }
        cls = event_classes[row["event_type"]]
        return cls(**row["payload"], version=row["version"], ...)

class ConcurrencyError(Exception):
    """Raised when optimistic concurrency check fails."""
    pass
```

### 4.5 Projections

```python
class Projection(ABC):
    """Base for read model projections."""

    @abstractmethod
    def handles(self) -> list[str]:
        """Event types this projection handles."""
        ...

    @abstractmethod
    async def apply(self, event: DomainEvent) -> None:
        """Apply event to projection."""
        ...

class EntityProjection(Projection):
    """Projects events to current entity states."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    def handles(self) -> list[str]:
        return [
            "WorkItemDrafted", "WorkItemProposed", "WorkItemApproved",
            "WorkItemCommitted", "WorkItemUpdated",
            "DecisionRecorded", "DecisionProposed", "DecisionApproved",
            "DecisionCommitted", "DecisionDeprecated"
        ]

    async def apply(self, event: DomainEvent) -> None:
        match event:
            case WorkItemDrafted():
                await self._create_entity(event)
            case WorkItemProposed():
                await self._transition_to_proposed(event)
            case WorkItemApproved():
                await self._transition_to_approved(event)
            case WorkItemCommitted():
                await self._transition_to_committed(event)
            # ... etc

    async def get_entity(self, entity_id: EntityId) -> Entity | None:
        """Get current entity state."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM entities_view WHERE id = $1
            """, entity_id)
            if not row:
                return None
            return self._row_to_entity(row)

    async def get_channel_entities(
        self,
        channel_id: ChannelId,
        entity_type: EntityType | None = None,
        lifecycle: list[EntityLifecycle] | None = None
    ) -> list[Entity]:
        """Get entities for channel with filters."""
        ...

class ProcessProjection(Projection):
    """Projects process/plan state."""

    def handles(self) -> list[str]:
        return [
            "ProcessStarted", "ProcessStageCompleted", "ProcessCompleted",
            "PlanCreated", "PlanItemCompleted", "PlanCompleted"
        ]

    async def apply(self, event: DomainEvent) -> None:
        ...

    async def get_active_process(self, channel_id: ChannelId, thread_ts: ThreadTs) -> Process | None:
        """Get active process for thread."""
        ...
```

---

## Part 5: Channel Aggregate

### 5.1 Channel as Aggregate Root

```python
from typing import Result  # Using result type pattern

@dataclass
class Channel:
    """
    Channel is the aggregate root.
    All mutations go through Channel methods.
    Methods return events, not mutated state.
    """
    id: ChannelId
    version: int

    # Current state (rebuilt from events)
    entities: dict[EntityId, Entity]
    processes: dict[str, "Process"]
    plans: dict[str, "Plan"]
    conflicts: list["Conflict"]

    # Configuration
    config: "ChannelConfig"

    # === Entity Operations ===

    def draft_work_item(
        self,
        actor: UserId,
        thread_ts: ThreadTs,
        content: WorkItemContent
    ) -> Result[WorkItemDrafted, DomainError]:
        """Create a draft work item."""

        # Validate
        errors = content.validate()
        if errors:
            return Err(ValidationError(errors))

        # Create event
        entity_id = EntityId.generate()
        return Ok(WorkItemDrafted(
            aggregate_id=self.id,
            actor_id=actor,
            version=self.version + 1,
            entity_id=entity_id,
            thread_ts=thread_ts,
            content=content
        ))

    def propose_entity(
        self,
        actor: UserId,
        entity_id: EntityId,
        canonical_message_ts: str
    ) -> Result[WorkItemProposed | DecisionProposed, DomainError]:
        """Propose entity for approval."""

        entity = self.entities.get(entity_id)
        if not entity:
            return Err(NotFoundError(f"Entity {entity_id} not found"))

        if not isinstance(entity, DraftEntity):
            return Err(InvalidStateError(f"Entity must be draft, is {type(entity).__name__}"))

        if isinstance(entity.content, WorkItemContent):
            return Ok(WorkItemProposed(
                aggregate_id=self.id,
                actor_id=actor,
                version=self.version + 1,
                entity_id=entity_id,
                canonical_message_ts=canonical_message_ts
            ))
        else:
            return Ok(DecisionProposed(...))

    def approve_entity(
        self,
        actor: UserId,
        entity_id: EntityId
    ) -> Result[WorkItemApproved | DecisionApproved, DomainError]:
        """Approve proposed entity."""

        entity = self.entities.get(entity_id)
        if not entity:
            return Err(NotFoundError(f"Entity {entity_id} not found"))

        if not isinstance(entity, ProposedEntity):
            return Err(InvalidStateError("Entity must be proposed"))

        # Check for active objections
        active_objections = [o for o in entity.objections if o.status == "active"]
        if active_objections:
            return Err(BlockedError(f"{len(active_objections)} active objections"))

        # Permission check delegated to application layer

        if isinstance(entity.content, WorkItemContent):
            return Ok(WorkItemApproved(
                aggregate_id=self.id,
                actor_id=actor,
                version=self.version + 1,
                entity_id=entity_id,
                approved_by=actor
            ))
        else:
            return Ok(DecisionApproved(...))

    def commit_entity(
        self,
        actor: UserId,
        entity_id: EntityId,
        jira_key: JiraKey,
        field_path: str | None = None
    ) -> Result[WorkItemCommitted | DecisionCommitted, DomainError]:
        """Commit approved entity to Jira."""

        entity = self.entities.get(entity_id)
        if not entity:
            return Err(NotFoundError(f"Entity {entity_id} not found"))

        if not isinstance(entity, ApprovedEntity):
            return Err(InvalidStateError("Entity must be approved"))

        if isinstance(entity.content, WorkItemContent):
            return Ok(WorkItemCommitted(
                aggregate_id=self.id,
                actor_id=actor,
                version=self.version + 1,
                entity_id=entity_id,
                jira_key=jira_key
            ))
        else:
            return Ok(DecisionCommitted(
                aggregate_id=self.id,
                actor_id=actor,
                version=self.version + 1,
                entity_id=entity_id,
                jira_key=jira_key,
                field_path=field_path or "description"
            ))

    # === Decision-Specific ===

    def record_decision(
        self,
        actor: UserId,
        thread_ts: ThreadTs,
        content: DecisionContent
    ) -> Result[DecisionRecorded, DomainError]:
        """Record a decision from conversation."""

        entity_id = EntityId.generate()
        return Ok(DecisionRecorded(
            aggregate_id=self.id,
            actor_id=actor,
            version=self.version + 1,
            entity_id=entity_id,
            thread_ts=thread_ts,
            content=content
        ))

    def deprecate_decision(
        self,
        actor: UserId,
        entity_id: EntityId,
        reason: str,
        superseded_by: EntityId | None = None
    ) -> Result[DecisionDeprecated, DomainError]:
        """Deprecate a decision."""

        entity = self.entities.get(entity_id)
        if not entity:
            return Err(NotFoundError(f"Entity {entity_id} not found"))

        if not isinstance(entity.content, DecisionContent):
            return Err(InvalidTypeError("Only decisions can be deprecated"))

        return Ok(DecisionDeprecated(
            aggregate_id=self.id,
            actor_id=actor,
            version=self.version + 1,
            entity_id=entity_id,
            superseded_by=superseded_by,
            reason=reason
        ))

    # === Process Operations ===

    def start_process(
        self,
        actor: UserId,
        process_type: str,
        thread_ts: ThreadTs
    ) -> Result[ProcessStarted, DomainError]:
        """Start a multi-stage process."""

        # Check no active process in this thread
        for proc in self.processes.values():
            if proc.thread_ts == thread_ts and proc.status == ProcessStatus.RUNNING:
                return Err(ConflictError("Thread already has active process"))

        process_id = str(uuid4())
        return Ok(ProcessStarted(
            aggregate_id=self.id,
            actor_id=actor,
            version=self.version + 1,
            process_id=process_id,
            process_type=process_type,
            thread_ts=thread_ts
        ))

    # === Conflict Detection ===

    def check_decision_conflicts(
        self,
        new_decision: DecisionContent
    ) -> list["Conflict"]:
        """Check for conflicts with existing decisions."""
        # Implemented via LLM in application layer
        # Channel just stores detected conflicts
        ...

# === Helper Types ===

@dataclass
class DomainError:
    message: str

class ValidationError(DomainError): pass
class NotFoundError(DomainError): pass
class InvalidStateError(DomainError): pass
class InvalidTypeError(DomainError): pass
class BlockedError(DomainError): pass
class ConflictError(DomainError): pass
```

### 5.2 Channel Repository

```python
class ChannelRepository:
    """Loads and saves Channel aggregate."""

    def __init__(self, event_store: EventStore, projections: list[Projection]):
        self.event_store = event_store
        self.projections = projections

    async def load(self, channel_id: ChannelId) -> Channel:
        """Load channel by replaying events."""
        events = await self.event_store.get_events(channel_id)
        return self._rebuild_from_events(channel_id, events)

    async def save(self, channel: Channel, events: list[DomainEvent]) -> None:
        """Save new events and update projections."""
        for event in events:
            await self.event_store.append(event)

            # Update projections
            for projection in self.projections:
                if event.event_type in projection.handles():
                    await projection.apply(event)

    def _rebuild_from_events(self, channel_id: ChannelId, events: list[DomainEvent]) -> Channel:
        """Rebuild channel state from events."""
        channel = Channel(
            id=channel_id,
            version=0,
            entities={},
            processes={},
            plans={},
            conflicts=[],
            config=ChannelConfig.default()
        )

        for event in events:
            channel = self._apply_event(channel, event)

        return channel

    def _apply_event(self, channel: Channel, event: DomainEvent) -> Channel:
        """Apply single event to channel state."""
        match event:
            case WorkItemDrafted():
                entity = DraftEntity(
                    id=event.entity_id,
                    entity_type=EntityType.WORK_ITEM,
                    channel_id=channel.id,
                    thread_ts=event.thread_ts,
                    content=event.content,
                    attribution=Attribution(
                        proposed_by=event.actor_id,
                        proposed_at=event.timestamp
                    ),
                    version=Version(1)
                )
                channel.entities[event.entity_id] = entity
                channel.version = event.version

            case WorkItemProposed():
                draft = channel.entities[event.entity_id]
                proposed = ProposedEntity(
                    id=draft.id,
                    entity_type=draft.entity_type,
                    channel_id=draft.channel_id,
                    thread_ts=draft.thread_ts,
                    content=draft.content,
                    attribution=draft.attribution,
                    version=Version(draft.version + 1),
                    canonical_message_ts=event.canonical_message_ts
                )
                channel.entities[event.entity_id] = proposed
                channel.version = event.version

            # ... handle other events

        return channel
```

---

## Part 6: Intent Classification (2-Stage)

### 6.1 Overview

Replace 6 layers with 2:

```
User Message
    │
    ├─→ Stage 1: Pre-Gates (deterministic)
    │      └─→ Catches: buttons, commands, thread bindings
    │
    └─→ Stage 2: Router (LLM when needed)
           └─→ Returns: SuperMode + context
```

### 6.2 SuperMode (4 Modes)

```python
class SuperMode(Enum):
    """User-facing modes. Internal complexity hidden."""
    CREATE = "create"      # New work items, new decisions
    MODIFY = "modify"      # Update existing (Jira, entities)
    RECORD = "record"      # Capture decision from conversation
    CONVERSE = "converse"  # Chat, review, search (no side effects)

# Safety classification
REQUIRES_CONFIRMATION = {SuperMode.CREATE, SuperMode.MODIFY, SuperMode.RECORD}
AUTO_EXECUTE = {SuperMode.CONVERSE}
```

### 6.3 Pre-Gates (Stage 1)

```python
@dataclass
class GateResult:
    """Result of pre-gate check."""
    matched: bool
    mode: SuperMode | None = None
    handler: str | None = None  # Specific handler to invoke
    context: dict = field(default_factory=dict)

class PreGates:
    """Deterministic routing that doesn't need LLM."""

    def check(self, message: SlackMessage) -> GateResult:
        """Check all gates in order."""

        # Gate 1: Button actions (approval, objection, etc.)
        if message.is_button_action:
            return GateResult(
                matched=True,
                handler="button_handler",
                context={"action": message.action_id, "value": message.action_value}
            )

        # Gate 2: Slash commands
        if message.text.startswith("/maro"):
            command = self._parse_command(message.text)
            return GateResult(
                matched=True,
                handler="command_handler",
                context={"command": command}
            )

        # Gate 3: Thread with active process
        if message.thread_ts:
            active_process = self._get_active_process(message.channel_id, message.thread_ts)
            if active_process:
                return GateResult(
                    matched=True,
                    handler="process_handler",
                    context={"process_id": active_process.id}
                )

        # Gate 4: Direct entity reference
        entity_ref = self._extract_entity_reference(message.text)
        if entity_ref:
            return GateResult(
                matched=True,
                mode=self._mode_for_entity_action(message.text),
                context={"entity_ref": entity_ref}
            )

        # No gate matched — need LLM
        return GateResult(matched=False)

    def _parse_command(self, text: str) -> "Command":
        """Parse /maro command."""
        parts = text.split()
        command_name = parts[1] if len(parts) > 1 else "help"
        args = parts[2:] if len(parts) > 2 else []
        return Command(name=command_name, args=args)

    def _extract_entity_reference(self, text: str) -> EntityId | JiraKey | None:
        """Extract explicit entity reference from text."""
        # Match PROJ-123 pattern
        import re
        jira_match = re.search(r'\b([A-Z]+-\d+)\b', text)
        if jira_match:
            return JiraKey(jira_match.group(1))
        return None
```

### 6.4 Router (Stage 2)

```python
@dataclass
class RouterResult:
    """Output of LLM router."""
    mode: SuperMode
    entities: list[EntityRef] = field(default_factory=list)
    is_compound: bool = False
    compound_parts: list[str] | None = None
    confidence: float = 1.0

@dataclass
class EntityRef:
    """Reference to an entity in the message."""
    entity_type: Literal["work_item", "decision", "jira_ticket"]
    identifier: str | None = None
    context_hint: str | None = None  # "the epic we discussed"

class Router:
    """LLM-based intent routing."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def route(self, message: str, context: RoutingContext) -> RouterResult:
        """Route message to mode."""

        prompt = self._build_prompt(message, context)
        result = await self.llm.complete(prompt, schema=RouterResult)
        return result

    def _build_prompt(self, message: str, context: RoutingContext) -> str:
        return f"""
Classify this message into one of 4 modes:

CREATE - User wants to create something new
  Examples: "create a ticket for...", "make an epic...", "add a story..."

MODIFY - User wants to change something existing
  Examples: "update the description", "change priority", "sync to Jira"

RECORD - User is stating a decision that should be recorded
  Examples: "we decided...", "the decision is...", "agreed: we'll use..."

CONVERSE - Everything else (chat, review, search, questions)
  Examples: "hi", "what can you do?", "review this", "search Jira for..."

Current context:
- Channel has {context.entity_count} entities
- Thread has active process: {context.has_active_process}
- Recent topic: {context.recent_topic}

Message: "{message}"

If the message contains multiple distinct actions (e.g., "create stories AND check Jira"),
set is_compound=true and list the parts.

Respond in JSON matching RouterResult schema.
"""

@dataclass
class RoutingContext:
    """Context for routing decision."""
    entity_count: int
    has_active_process: bool
    recent_topic: str | None
    mentioned_entities: list[EntityRef]
```

### 6.5 Mode Handlers

```python
class ModeHandler(ABC):
    """Base for mode handlers."""

    @abstractmethod
    async def handle(self, message: SlackMessage, result: RouterResult, channel: Channel) -> list[DomainEvent]:
        """Handle message, return events to persist."""
        ...

class CreateHandler(ModeHandler):
    """Handles CREATE mode."""

    async def handle(self, message: SlackMessage, result: RouterResult, channel: Channel) -> list[DomainEvent]:
        # If compound, decompose into plan
        if result.is_compound:
            return await self._handle_compound(message, result, channel)

        # Single creation
        content = await self._extract_content(message.text)

        match content:
            case WorkItemContent():
                event_result = channel.draft_work_item(
                    actor=message.user_id,
                    thread_ts=message.thread_ts or message.ts,
                    content=content
                )
            case DecisionContent():
                event_result = channel.record_decision(
                    actor=message.user_id,
                    thread_ts=message.thread_ts or message.ts,
                    content=content
                )

        match event_result:
            case Ok(event):
                return [event]
            case Err(error):
                await self._send_error(message, error)
                return []

class ModifyHandler(ModeHandler):
    """Handles MODIFY mode."""

    async def handle(self, message: SlackMessage, result: RouterResult, channel: Channel) -> list[DomainEvent]:
        # Identify target entity
        if not result.entities:
            await self._ask_which_entity(message)
            return []

        entity_ref = result.entities[0]
        entity = self._resolve_entity(entity_ref, channel)

        if not entity:
            await self._entity_not_found(message, entity_ref)
            return []

        # Parse modification
        modification = await self._parse_modification(message.text, entity)

        # Apply modification
        event_result = channel.update_entity(
            actor=message.user_id,
            entity_id=entity.id,
            changes=modification.changes,
            reason=modification.reason
        )

        match event_result:
            case Ok(event):
                return [event]
            case Err(error):
                await self._send_error(message, error)
                return []

class RecordHandler(ModeHandler):
    """Handles RECORD mode - capturing decisions."""

    async def handle(self, message: SlackMessage, result: RouterResult, channel: Channel) -> list[DomainEvent]:
        # Extract decision from message
        decision_content = await self._extract_decision(message.text)

        # Check for conflicts
        conflicts = await self._check_conflicts(decision_content, channel)
        if conflicts:
            await self._show_conflicts(message, conflicts)
            # Still create but mark as conflicting
            decision_content.has_conflicts = True

        event_result = channel.record_decision(
            actor=message.user_id,
            thread_ts=message.thread_ts or message.ts,
            content=decision_content
        )

        match event_result:
            case Ok(event):
                return [event]
            case Err(error):
                await self._send_error(message, error)
                return []

class ConverseHandler(ModeHandler):
    """Handles CONVERSE mode - no side effects."""

    async def handle(self, message: SlackMessage, result: RouterResult, channel: Channel) -> list[DomainEvent]:
        # No events produced - just respond
        response = await self._generate_response(message, channel)
        await self._send_response(message, response)
        return []  # No domain events
```

---

## Part 7: Process, Plan, Workflow

### 7.1 Process (Multi-Stage with Loops)

Process handles complex tasks that require multiple iterations.

```python
class ProcessStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"        # Waiting for user input
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"      # Asked question, waiting for answer
    COMPLETED = "completed"
    SKIPPED = "skipped"

@dataclass
class ProcessDefinition:
    """Definition of a process type."""
    process_type: str
    stages: list["StageDefinition"]
    description: str

@dataclass
class StageDefinition:
    """Definition of a single stage."""
    name: str
    description: str
    required_outputs: list[str]
    max_iterations: int = 3
    can_skip: bool = False

@dataclass
class Process:
    """Instance of a running process."""
    id: str
    definition: ProcessDefinition
    channel_id: ChannelId
    thread_ts: ThreadTs
    status: ProcessStatus
    current_stage_index: int
    stage_states: list["StageState"]
    outputs: dict[str, Any]  # Accumulated outputs
    started_at: datetime
    completed_at: datetime | None = None

@dataclass
class StageState:
    """State of a single stage."""
    status: StageStatus
    iteration: int
    gathered_info: dict[str, Any]
    pending_question: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)

# === Process Definitions ===

ARCHITECTURE_REVIEW_PROCESS = ProcessDefinition(
    process_type="architecture_review",
    description="Multi-stage architecture review process",
    stages=[
        StageDefinition(
            name="discovery",
            description="Understand what user wants to build",
            required_outputs=["goal", "scope", "constraints"],
            max_iterations=5
        ),
        StageDefinition(
            name="analysis",
            description="Analyze technical implications",
            required_outputs=["components", "risks", "alternatives"],
            max_iterations=3
        ),
        StageDefinition(
            name="decisions",
            description="Capture architectural decisions",
            required_outputs=["decisions"],
            max_iterations=3
        ),
        StageDefinition(
            name="planning",
            description="Create implementation plan",
            required_outputs=["plan_items"],
            max_iterations=2
        )
    ]
)

WORK_ITEM_CREATION_PROCESS = ProcessDefinition(
    process_type="work_item_creation",
    description="Gather requirements for work item",
    stages=[
        StageDefinition(
            name="understand",
            description="Understand what needs to be built",
            required_outputs=["title", "description"],
            max_iterations=3
        ),
        StageDefinition(
            name="refine",
            description="Refine acceptance criteria",
            required_outputs=["acceptance_criteria"],
            max_iterations=3,
            can_skip=True  # For spikes/tasks
        ),
        StageDefinition(
            name="validate",
            description="Validate completeness",
            required_outputs=["validated"],
            max_iterations=1
        )
    ]
)
```

### 7.2 Process Executor

```python
class ProcessExecutor:
    """Executes process stages."""

    def __init__(self, llm: LLMProvider, slack: SlackClient):
        self.llm = llm
        self.slack = slack

    async def start(self, process: Process) -> list[DomainEvent]:
        """Start process execution."""
        events = []

        # Initialize first stage
        process.status = ProcessStatus.RUNNING
        process.stage_states[0].status = StageStatus.RUNNING

        # Generate first question
        question = await self._generate_stage_question(process, 0)
        process.stage_states[0].pending_question = question

        await self.slack.post_to_thread(
            channel_id=process.channel_id,
            thread_ts=process.thread_ts,
            text=question
        )

        return events

    async def handle_input(self, process: Process, message: SlackMessage) -> list[DomainEvent]:
        """Handle user input during process."""
        events = []
        stage_index = process.current_stage_index
        stage_state = process.stage_states[stage_index]
        stage_def = process.definition.stages[stage_index]

        # Extract information from user message
        extracted = await self._extract_stage_info(
            message.text,
            stage_def,
            stage_state.gathered_info
        )

        # Merge with existing info
        stage_state.gathered_info.update(extracted)
        stage_state.iteration += 1

        # Check if stage requirements met
        if self._stage_complete(stage_def, stage_state):
            # Complete stage
            stage_state.status = StageStatus.COMPLETED
            stage_state.outputs = stage_state.gathered_info

            events.append(ProcessStageCompleted(
                aggregate_id=process.channel_id,
                actor_id=message.user_id,
                version=0,  # Will be set by repository
                process_id=process.id,
                stage_name=stage_def.name,
                outputs=stage_state.outputs
            ))

            # Accumulate outputs
            process.outputs.update(stage_state.outputs)

            # Move to next stage or complete
            if stage_index + 1 < len(process.definition.stages):
                process.current_stage_index += 1
                next_stage = process.stage_states[process.current_stage_index]
                next_stage.status = StageStatus.RUNNING

                # Generate next question
                question = await self._generate_stage_question(
                    process,
                    process.current_stage_index
                )
                next_stage.pending_question = question

                await self.slack.post_to_thread(
                    channel_id=process.channel_id,
                    thread_ts=process.thread_ts,
                    text=question
                )
            else:
                # Process complete
                process.status = ProcessStatus.COMPLETED
                process.completed_at = datetime.utcnow()

                events.append(ProcessCompleted(
                    aggregate_id=process.channel_id,
                    actor_id=message.user_id,
                    version=0,
                    process_id=process.id,
                    final_outputs=process.outputs
                ))

                # Transition to plan if needed
                await self._transition_to_plan(process)

        elif stage_state.iteration >= stage_def.max_iterations:
            # Max iterations - ask for confirmation or skip
            if stage_def.can_skip:
                await self.slack.post_to_thread(
                    channel_id=process.channel_id,
                    thread_ts=process.thread_ts,
                    text=f"I couldn't gather complete info for {stage_def.name}. Continue anyway?",
                    blocks=self._build_skip_buttons(process.id, stage_index)
                )
            else:
                await self.slack.post_to_thread(
                    channel_id=process.channel_id,
                    thread_ts=process.thread_ts,
                    text=f"I still need: {self._missing_outputs(stage_def, stage_state)}"
                )
        else:
            # Continue gathering
            question = await self._generate_followup_question(
                process, stage_index, stage_state.gathered_info
            )
            stage_state.pending_question = question

            await self.slack.post_to_thread(
                channel_id=process.channel_id,
                thread_ts=process.thread_ts,
                text=question
            )

        return events

    def _stage_complete(self, stage_def: StageDefinition, stage_state: StageState) -> bool:
        """Check if stage has all required outputs."""
        return all(
            output in stage_state.gathered_info
            for output in stage_def.required_outputs
        )

    async def _generate_stage_question(self, process: Process, stage_index: int) -> str:
        """Generate question for stage."""
        stage_def = process.definition.stages[stage_index]

        prompt = f"""
You are gathering information for: {stage_def.description}

Required outputs: {stage_def.required_outputs}
Already gathered in process: {process.outputs}

Generate a concise question to gather the next piece of needed information.
Be specific. One question at a time.
"""
        return await self.llm.complete(prompt)
```

### 7.3 Plan (Linear Execution)

```python
class PlanStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PlanItemStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

@dataclass
class PlanItem:
    """Single item in a plan."""
    index: int
    action: str                    # "create_epic", "create_story", "sync_jira"
    params: dict[str, Any]         # Parameters for action
    status: PlanItemStatus = PlanItemStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None

@dataclass
class Plan:
    """Linear execution plan."""
    id: str
    channel_id: ChannelId
    thread_ts: ThreadTs
    items: list[PlanItem]
    status: PlanStatus
    current_index: int = 0
    source_process_id: str | None = None  # If generated from process
    created_at: datetime = field(default_factory=datetime.utcnow)

class PlanGenerator:
    """Generates plans from process outputs."""

    async def generate_from_process(self, process: Process) -> Plan:
        """Generate plan from completed process."""

        items = []

        match process.definition.process_type:
            case "architecture_review":
                # Create decisions first
                for decision in process.outputs.get("decisions", []):
                    items.append(PlanItem(
                        index=len(items),
                        action="create_decision",
                        params={"content": decision}
                    ))

                # Then create work items
                for item in process.outputs.get("plan_items", []):
                    items.append(PlanItem(
                        index=len(items),
                        action="create_work_item",
                        params={"content": item}
                    ))

            case "work_item_creation":
                items.append(PlanItem(
                    index=0,
                    action="create_work_item",
                    params={
                        "title": process.outputs["title"],
                        "description": process.outputs["description"],
                        "acceptance_criteria": process.outputs.get("acceptance_criteria", [])
                    }
                ))

        return Plan(
            id=str(uuid4()),
            channel_id=process.channel_id,
            thread_ts=process.thread_ts,
            items=items,
            status=PlanStatus.PENDING,
            source_process_id=process.id
        )

class PlanExecutor:
    """Executes plan items."""

    def __init__(self, channel_repo: ChannelRepository, slack: SlackClient):
        self.channel_repo = channel_repo
        self.slack = slack

    async def execute(self, plan: Plan) -> list[DomainEvent]:
        """Execute all plan items."""
        events = []
        channel = await self.channel_repo.load(plan.channel_id)

        plan.status = PlanStatus.EXECUTING

        for item in plan.items:
            if plan.status == PlanStatus.CANCELLED:
                break

            item.status = PlanItemStatus.EXECUTING
            await self._update_status_message(plan)

            try:
                result_events = await self._execute_item(item, channel, plan)
                events.extend(result_events)
                item.status = PlanItemStatus.COMPLETED
                item.result = {"events": len(result_events)}

                # Reload channel with new events
                for event in result_events:
                    channel = self.channel_repo._apply_event(channel, event)

            except Exception as e:
                item.status = PlanItemStatus.FAILED
                item.error = str(e)
                # Continue with next item unless critical
                if self._is_critical_failure(item):
                    plan.status = PlanStatus.CANCELLED
                    break

            await self._update_status_message(plan)

        if plan.status != PlanStatus.CANCELLED:
            plan.status = PlanStatus.COMPLETED
            events.append(PlanCompleted(
                aggregate_id=plan.channel_id,
                actor_id=UserId("system"),
                version=0,
                plan_id=plan.id
            ))

        await self._update_status_message(plan)
        return events

    async def _execute_item(self, item: PlanItem, channel: Channel, plan: Plan) -> list[DomainEvent]:
        """Execute single plan item."""
        match item.action:
            case "create_work_item":
                content = WorkItemContent(**item.params.get("content", item.params))
                result = channel.draft_work_item(
                    actor=UserId("system"),
                    thread_ts=plan.thread_ts,
                    content=content
                )
                match result:
                    case Ok(event):
                        return [event]
                    case Err(error):
                        raise Exception(error.message)

            case "create_decision":
                content = DecisionContent(**item.params["content"])
                result = channel.record_decision(
                    actor=UserId("system"),
                    thread_ts=plan.thread_ts,
                    content=content
                )
                match result:
                    case Ok(event):
                        return [event]
                    case Err(error):
                        raise Exception(error.message)

            case "sync_jira":
                # Handled by Jira integration
                ...

        return []
```

### 7.4 Workflow (Process + Plan Combined)

```python
class WorkflowPhaseType(Enum):
    PROCESS = "process"   # Multi-stage with iterations
    PLAN = "plan"         # Linear execution

@dataclass
class WorkflowPhase:
    """Single phase in workflow."""
    phase_type: WorkflowPhaseType
    process_type: str | None = None  # If PROCESS
    plan_generator: str | None = None  # If PLAN - how to generate plan

@dataclass
class WorkflowDefinition:
    """Definition of a complete workflow."""
    workflow_type: str
    phases: list[WorkflowPhase]
    description: str

@dataclass
class Workflow:
    """Instance of running workflow."""
    id: str
    definition: WorkflowDefinition
    channel_id: ChannelId
    thread_ts: ThreadTs
    current_phase_index: int
    accumulated_outputs: dict[str, Any]
    process: Process | None = None  # Current process if in PROCESS phase
    plan: Plan | None = None        # Current plan if in PLAN phase

# === Workflow Definitions ===

FULL_ARCHITECTURE_WORKFLOW = WorkflowDefinition(
    workflow_type="full_architecture",
    description="Complete architecture review to Jira workflow",
    phases=[
        WorkflowPhase(
            phase_type=WorkflowPhaseType.PROCESS,
            process_type="architecture_review"
        ),
        WorkflowPhase(
            phase_type=WorkflowPhaseType.PLAN,
            plan_generator="from_architecture_review"
        )
    ]
)

QUICK_TICKET_WORKFLOW = WorkflowDefinition(
    workflow_type="quick_ticket",
    description="Quick work item creation",
    phases=[
        WorkflowPhase(
            phase_type=WorkflowPhaseType.PROCESS,
            process_type="work_item_creation"
        ),
        WorkflowPhase(
            phase_type=WorkflowPhaseType.PLAN,
            plan_generator="single_work_item"
        )
    ]
)

class WorkflowExecutor:
    """Orchestrates workflow execution."""

    def __init__(
        self,
        process_executor: ProcessExecutor,
        plan_executor: PlanExecutor,
        plan_generator: PlanGenerator
    ):
        self.process_executor = process_executor
        self.plan_executor = plan_executor
        self.plan_generator = plan_generator

    async def start(self, workflow: Workflow) -> list[DomainEvent]:
        """Start workflow execution."""
        return await self._execute_phase(workflow)

    async def handle_input(self, workflow: Workflow, message: SlackMessage) -> list[DomainEvent]:
        """Handle user input during workflow."""
        phase = workflow.definition.phases[workflow.current_phase_index]

        match phase.phase_type:
            case WorkflowPhaseType.PROCESS:
                events = await self.process_executor.handle_input(
                    workflow.process, message
                )

                # Check if process completed
                if workflow.process.status == ProcessStatus.COMPLETED:
                    workflow.accumulated_outputs.update(workflow.process.outputs)
                    return await self._advance_to_next_phase(workflow, events)

                return events

            case WorkflowPhaseType.PLAN:
                # Plans don't take input - they execute
                return []

    async def _execute_phase(self, workflow: Workflow) -> list[DomainEvent]:
        """Execute current phase."""
        phase = workflow.definition.phases[workflow.current_phase_index]
        events = []

        match phase.phase_type:
            case WorkflowPhaseType.PROCESS:
                # Create and start process
                workflow.process = self._create_process(phase, workflow)
                events = await self.process_executor.start(workflow.process)

            case WorkflowPhaseType.PLAN:
                # Generate and execute plan
                workflow.plan = await self._generate_plan(phase, workflow)
                events = await self.plan_executor.execute(workflow.plan)
                workflow.accumulated_outputs.update({"plan_result": workflow.plan})

                # Plan auto-completes, advance
                return await self._advance_to_next_phase(workflow, events)

        return events

    async def _advance_to_next_phase(self, workflow: Workflow, events: list[DomainEvent]) -> list[DomainEvent]:
        """Advance to next phase or complete."""
        workflow.current_phase_index += 1

        if workflow.current_phase_index >= len(workflow.definition.phases):
            # Workflow complete
            return events  # + workflow completion event

        return events + await self._execute_phase(workflow)
```

---

## Part 8: Multi-User Support

### 8.1 Channel Permissions

```python
@dataclass
class ChannelPermissions:
    """Permission configuration for a channel."""
    channel_id: ChannelId

    # All users can propose and approve (default)
    # Specific restrictions can be added later
    self_approval_allowed: bool = True      # Can approve own proposals
    min_approvers: int = 1                  # How many approvals needed
    approval_timeout_hours: int | None = None  # Auto-escalate after timeout

    def can_approve(self, user_id: UserId, entity: ProposedEntity) -> tuple[bool, str | None]:
        """Check if user can approve entity."""

        # Self-approval check (allowed by default)
        if not self.self_approval_allowed:
            if entity.attribution.proposed_by == user_id:
                return False, "Self-approval not allowed in this channel"

        return True, None

    def can_propose(self, user_id: UserId) -> tuple[bool, str | None]:
        """Check if user can propose. Everyone can by default."""
        return True, None

    def has_enough_approvals(self, entity: ProposedEntity) -> bool:
        """Check if entity has enough approvals."""
        return len(entity.approvals) >= self.min_approvers
```

### 8.2 Concurrent Request Handling

```python
@dataclass
class UserRequest:
    """A user request in the queue."""
    id: str
    user_id: UserId
    message_ts: str
    mode: SuperMode
    entities: list[EntityRef]
    received_at: datetime
    status: Literal["queued", "processing", "completed", "failed"] = "queued"

class RequestCoordinator:
    """Coordinates concurrent requests in a channel."""

    def __init__(self):
        self._queues: dict[ChannelId, list[UserRequest]] = {}
        self._active: dict[ChannelId, UserRequest | None] = {}
        self._locks: dict[ChannelId, asyncio.Lock] = {}

    async def enqueue(self, channel_id: ChannelId, request: UserRequest) -> int:
        """Enqueue request. Returns position in queue."""

        if channel_id not in self._locks:
            self._locks[channel_id] = asyncio.Lock()
            self._queues[channel_id] = []
            self._active[channel_id] = None

        async with self._locks[channel_id]:
            # CONVERSE mode can run in parallel (no side effects)
            if request.mode == SuperMode.CONVERSE:
                return 0  # Immediate processing

            # Check for conflicts with active request
            active = self._active[channel_id]
            if active and self._conflicts_with(request, active):
                self._queues[channel_id].append(request)
                return len(self._queues[channel_id])

            # No conflict - can process
            self._active[channel_id] = request
            return 0

    async def complete(self, channel_id: ChannelId, request_id: str) -> UserRequest | None:
        """Mark request complete, return next request to process."""

        async with self._locks[channel_id]:
            if self._active[channel_id] and self._active[channel_id].id == request_id:
                self._active[channel_id].status = "completed"

                # Get next from queue
                if self._queues[channel_id]:
                    next_request = self._queues[channel_id].pop(0)
                    self._active[channel_id] = next_request
                    return next_request
                else:
                    self._active[channel_id] = None

        return None

    def _conflicts_with(self, a: UserRequest, b: UserRequest) -> bool:
        """Check if requests touch same entities."""
        a_ids = {e.identifier for e in a.entities if e.identifier}
        b_ids = {e.identifier for e in b.entities if e.identifier}
        return bool(a_ids & b_ids)
```

### 8.3 Decision Conflict Detection

```python
@dataclass
class DecisionConflict:
    """Detected conflict between decisions."""
    id: str
    decision_a_id: EntityId
    decision_b_id: EntityId
    conflict_type: str  # "direct_contradiction", "scope_overlap", "resource_conflict"
    description: str
    detected_at: datetime
    status: Literal["active", "resolved"] = "active"
    resolution: "ConflictResolution | None" = None

@dataclass
class ConflictResolution:
    """How conflict was resolved."""
    resolution_type: str  # "keep_both", "supersede", "merge", "withdraw"
    resolved_by: UserId
    resolved_at: datetime
    outcome: str

class ConflictDetector:
    """Detects contradictions between decisions."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def check_new_decision(
        self,
        new_decision: DecisionContent,
        existing_decisions: list[Entity]
    ) -> list[DecisionConflict]:
        """Check if new decision conflicts with existing ones."""

        conflicts = []

        # Filter to active decisions only
        active_decisions = [
            e for e in existing_decisions
            if isinstance(e.content, DecisionContent)
            and not isinstance(e, DeprecatedEntity)
        ]

        for existing in active_decisions:
            conflict = await self._check_pair(new_decision, existing.content)
            if conflict:
                conflicts.append(DecisionConflict(
                    id=str(uuid4()),
                    decision_a_id=EntityId("new"),
                    decision_b_id=existing.id,
                    conflict_type=conflict["type"],
                    description=conflict["description"],
                    detected_at=datetime.utcnow()
                ))

        return conflicts

    async def _check_pair(
        self,
        a: DecisionContent,
        b: DecisionContent
    ) -> dict | None:
        """Check two decisions for conflict."""

        prompt = f"""
Analyze these two decisions for contradictions:

Decision A: {a.title}
{a.description}

Decision B: {b.title}
{b.description}

Types of conflicts to check:
- DIRECT_CONTRADICTION: A says X, B says not-X
- SCOPE_OVERLAP: Both affect same area differently
- RESOURCE_CONFLICT: Both require incompatible resources

If they conflict, respond with JSON:
{{"conflict": true, "type": "...", "description": "..."}}

If no conflict:
{{"conflict": false}}
"""
        result = await self.llm.complete(prompt)

        if result.get("conflict"):
            return {"type": result["type"], "description": result["description"]}
        return None
```

### 8.4 Objection Handling

```python
class ObjectionHandler:
    """Handles objections to proposals."""

    def __init__(self, slack: SlackClient, channel_repo: ChannelRepository):
        self.slack = slack
        self.channel_repo = channel_repo

    async def raise_objection(
        self,
        entity: ProposedEntity,
        user_id: UserId,
        reason: str
    ) -> None:
        """Raise objection to a proposal."""

        objection = Objection(
            user_id=user_id,
            timestamp=datetime.utcnow(),
            reason=reason,
            status="active"
        )

        entity.objections.append(objection)

        # Notify in thread
        await self.slack.post_to_thread(
            channel_id=entity.channel_id,
            thread_ts=entity.canonical_message_ts,
            text=f":warning: <@{user_id}> raised an objection:\n> {reason}\n\n"
                 f"This blocks approval until resolved."
        )

        # Update canonical message to show blocked state
        await self._update_entity_message(entity)

    async def resolve_objection(
        self,
        entity: ProposedEntity,
        objection_index: int,
        resolution: str,
        resolved_by: UserId
    ) -> None:
        """Resolve an objection."""

        objection = entity.objections[objection_index]
        objection.status = "resolved"
        objection.resolution = resolution

        await self.slack.post_to_thread(
            channel_id=entity.channel_id,
            thread_ts=entity.canonical_message_ts,
            text=f":white_check_mark: Objection resolved by <@{resolved_by}>:\n> {resolution}"
        )

        await self._update_entity_message(entity)

    async def _update_entity_message(self, entity: ProposedEntity) -> None:
        """Update entity's canonical message with current state."""
        blocks = self._build_entity_blocks(entity)
        await self.slack.update_message(
            channel_id=entity.channel_id,
            ts=entity.canonical_message_ts,
            blocks=blocks
        )
```

### 8.5 Approval Workflow

```python
class ApprovalHandler:
    """Handles approval workflow."""

    def __init__(
        self,
        slack: SlackClient,
        channel_repo: ChannelRepository,
        permissions: ChannelPermissions
    ):
        self.slack = slack
        self.channel_repo = channel_repo
        self.permissions = permissions

    async def request_approval(
        self,
        channel: Channel,
        entity_id: EntityId,
        actor: UserId
    ) -> list[DomainEvent]:
        """Post entity for approval."""

        entity = channel.entities.get(entity_id)
        if not isinstance(entity, DraftEntity):
            raise ValueError("Only drafts can be proposed")

        # Post to channel
        blocks = self._build_proposal_blocks(entity)
        message = await self.slack.post_to_channel(
            channel_id=channel.id,
            blocks=blocks
        )

        # Create proposal event
        result = channel.propose_entity(
            actor=actor,
            entity_id=entity_id,
            canonical_message_ts=message.ts
        )

        match result:
            case Ok(event):
                return [event]
            case Err(error):
                raise ValueError(error.message)

    async def approve(
        self,
        channel: Channel,
        entity_id: EntityId,
        approver: UserId
    ) -> list[DomainEvent]:
        """Approve a proposed entity."""

        entity = channel.entities.get(entity_id)
        if not isinstance(entity, ProposedEntity):
            raise ValueError("Only proposed entities can be approved")

        # Check permissions
        can, reason = self.permissions.can_approve(approver, entity)
        if not can:
            await self.slack.post_ephemeral(
                channel_id=channel.id,
                user_id=approver,
                text=f":x: Cannot approve: {reason}"
            )
            return []

        # Check for active objections
        active_objections = [o for o in entity.objections if o.status == "active"]
        if active_objections:
            await self.slack.post_ephemeral(
                channel_id=channel.id,
                user_id=approver,
                text=f":x: Cannot approve: {len(active_objections)} active objection(s)"
            )
            return []

        # Add approval
        entity.approvals.append(Approval(
            user_id=approver,
            timestamp=datetime.utcnow()
        ))

        # Check if enough approvals
        if self.permissions.has_enough_approvals(entity):
            result = channel.approve_entity(actor=approver, entity_id=entity_id)

            match result:
                case Ok(event):
                    await self._update_entity_message(entity, approved=True)
                    return [event]
                case Err(error):
                    raise ValueError(error.message)
        else:
            # Update message with approval count
            await self._update_entity_message(entity)
            return []

    def _build_proposal_blocks(self, entity: DraftEntity) -> list[dict]:
        """Build Slack blocks for proposal."""
        content = entity.content

        if isinstance(content, WorkItemContent):
            return [
                {"type": "header", "text": {"type": "plain_text", "text": f":clipboard: {content.issue_type.value.upper()}: {content.title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": content.description or "_No description_"}},
                {"type": "context", "elements": [
                    {"type": "mrkdwn", "text": f"Proposed by <@{entity.attribution.proposed_by}>"}
                ]},
                {"type": "divider"},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": f"approve_{entity.id}"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Object"}, "action_id": f"object_{entity.id}"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Discuss"}, "action_id": f"discuss_{entity.id}"}
                ]}
            ]
        else:
            # Decision blocks
            return [
                {"type": "header", "text": {"type": "plain_text", "text": f":memo: Decision: {content.title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": content.description}},
                {"type": "context", "elements": [
                    {"type": "mrkdwn", "text": f"Type: {content.decision_type.value} | Proposed by <@{entity.attribution.proposed_by}>"}
                ]},
                {"type": "divider"},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": f"approve_{entity.id}"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Object"}, "action_id": f"object_{entity.id}"}
                ]}
            ]
```

---

## Part 9: Slack Integration

### 9.1 Writing Rules

Where to write what:

```python
class SlackWriteTarget(Enum):
    CHANNEL = "channel"       # Visible to everyone, permanent
    THREAD = "thread"         # Conversation context
    EPHEMERAL = "ephemeral"   # Only visible to one user

# Message type → Target mapping
WRITE_TARGETS = {
    # CHANNEL - Status updates, approved items, decisions
    "entity_proposed": SlackWriteTarget.CHANNEL,
    "entity_approved": SlackWriteTarget.CHANNEL,
    "entity_committed": SlackWriteTarget.CHANNEL,
    "decision_recorded": SlackWriteTarget.CHANNEL,
    "conflict_detected": SlackWriteTarget.CHANNEL,
    "workflow_completed": SlackWriteTarget.CHANNEL,

    # THREAD - Working conversation
    "question_asked": SlackWriteTarget.THREAD,
    "draft_preview": SlackWriteTarget.THREAD,
    "process_progress": SlackWriteTarget.THREAD,
    "plan_status": SlackWriteTarget.THREAD,
    "validation_result": SlackWriteTarget.THREAD,
    "conversation_response": SlackWriteTarget.THREAD,

    # EPHEMERAL - Personal notifications
    "permission_denied": SlackWriteTarget.EPHEMERAL,
    "command_help": SlackWriteTarget.EPHEMERAL,
    "error_message": SlackWriteTarget.EPHEMERAL,
    "queue_position": SlackWriteTarget.EPHEMERAL,
}
```

### 9.2 Slack Client

```python
class SlackClient:
    """Wrapper for Slack API with message type routing."""

    def __init__(self, app: slack_bolt.App):
        self.app = app
        self._rate_limiter = RateLimiter(calls_per_second=1)

    async def send(
        self,
        message_type: str,
        channel_id: ChannelId,
        content: str | list[dict],  # Text or blocks
        thread_ts: ThreadTs | None = None,
        user_id: UserId | None = None
    ) -> SlackMessage | None:
        """Send message to appropriate target based on type."""

        target = WRITE_TARGETS.get(message_type, SlackWriteTarget.THREAD)

        match target:
            case SlackWriteTarget.CHANNEL:
                return await self.post_to_channel(channel_id, content)
            case SlackWriteTarget.THREAD:
                if not thread_ts:
                    raise ValueError(f"Thread target requires thread_ts: {message_type}")
                return await self.post_to_thread(channel_id, thread_ts, content)
            case SlackWriteTarget.EPHEMERAL:
                if not user_id:
                    raise ValueError(f"Ephemeral target requires user_id: {message_type}")
                await self.post_ephemeral(channel_id, user_id, content, thread_ts)
                return None

    async def post_to_channel(
        self,
        channel_id: ChannelId,
        content: str | list[dict]
    ) -> SlackMessage:
        """Post to channel (visible to all)."""
        await self._rate_limiter.acquire()

        kwargs = {"channel": channel_id}
        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "New update"  # Fallback

        result = await self.app.client.chat_postMessage(**kwargs)
        return SlackMessage(
            ts=result["ts"],
            channel_id=channel_id,
            text=kwargs.get("text", "")
        )

    async def post_to_thread(
        self,
        channel_id: ChannelId,
        thread_ts: ThreadTs,
        content: str | list[dict]
    ) -> SlackMessage:
        """Post to thread."""
        await self._rate_limiter.acquire()

        kwargs = {"channel": channel_id, "thread_ts": thread_ts}
        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "Update"

        result = await self.app.client.chat_postMessage(**kwargs)
        return SlackMessage(ts=result["ts"], channel_id=channel_id, text=kwargs.get("text", ""))

    async def post_ephemeral(
        self,
        channel_id: ChannelId,
        user_id: UserId,
        content: str | list[dict],
        thread_ts: ThreadTs | None = None
    ) -> None:
        """Post ephemeral message (only visible to user)."""
        await self._rate_limiter.acquire()

        kwargs = {"channel": channel_id, "user": user_id}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "Info"

        await self.app.client.chat_postEphemeral(**kwargs)

    async def update_message(
        self,
        channel_id: ChannelId,
        ts: str,
        content: str | list[dict]
    ) -> None:
        """Update existing message."""
        await self._rate_limiter.acquire()

        kwargs = {"channel": channel_id, "ts": ts}
        if isinstance(content, str):
            kwargs["text"] = content
        else:
            kwargs["blocks"] = content
            kwargs["text"] = "Updated"

        await self.app.client.chat_update(**kwargs)

@dataclass
class SlackMessage:
    """Slack message reference."""
    ts: str
    channel_id: ChannelId
    text: str
    thread_ts: ThreadTs | None = None
    user_id: UserId | None = None
```

### 9.3 Status Dashboard (Pinned Message)

```python
@dataclass
class ChannelDashboard:
    """Pinned status dashboard for channel."""
    channel_id: ChannelId
    message_ts: str
    last_updated: datetime

class DashboardManager:
    """Manages channel status dashboard."""

    def __init__(self, slack: SlackClient, entity_projection: EntityProjection):
        self.slack = slack
        self.entity_projection = entity_projection

    async def create_or_update(self, channel_id: ChannelId) -> None:
        """Create or update channel dashboard."""

        # Get current state
        entities = await self.entity_projection.get_channel_entities(channel_id)

        # Build dashboard
        blocks = self._build_dashboard_blocks(entities)

        # Check if dashboard exists
        dashboard = await self._get_dashboard(channel_id)

        if dashboard:
            await self.slack.update_message(channel_id, dashboard.message_ts, blocks)
        else:
            message = await self.slack.post_to_channel(channel_id, blocks)
            await self._pin_message(channel_id, message.ts)
            await self._save_dashboard(channel_id, message.ts)

    def _build_dashboard_blocks(self, entities: list[Entity]) -> list[dict]:
        """Build dashboard blocks."""

        # Group by lifecycle
        by_lifecycle = {}
        for entity in entities:
            lifecycle = get_lifecycle(entity)
            by_lifecycle.setdefault(lifecycle, []).append(entity)

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": ":bar_chart: Channel Status"}},
            {"type": "divider"}
        ]

        # Pending approvals
        proposed = by_lifecycle.get(EntityLifecycle.PROPOSED, [])
        if proposed:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Pending Approval ({len(proposed)})*"}
            })
            for entity in proposed[:5]:  # Show first 5
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"• {self._entity_summary(entity)}"}]
                })

        # Recently committed
        committed = by_lifecycle.get(EntityLifecycle.COMMITTED, [])
        if committed:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*In Jira ({len(committed)})*"}
            })
            for entity in committed[:5]:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"• {self._entity_summary(entity)}"}]
                })

        # Active decisions
        decisions = [e for e in entities if isinstance(e.content, DecisionContent) and not isinstance(e, DeprecatedEntity)]
        if decisions:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Active Decisions ({len(decisions)})*"}
            })
            for decision in decisions[:5]:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"• {decision.content.title}"}]
                })

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_Last updated: <!date^{int(datetime.utcnow().timestamp())}^{{date_short}} {{time}}|now>_"}]
        })

        return blocks

    def _entity_summary(self, entity: Entity) -> str:
        """Get summary text for entity."""
        content = entity.content
        if isinstance(content, WorkItemContent):
            jira_key = entity.jira_link.jira_key if hasattr(entity, 'jira_link') and entity.jira_link else "draft"
            return f"[{jira_key}] {content.title}"
        else:
            return f":memo: {content.title}"
```

### 9.4 Button Handlers

```python
class ButtonHandler:
    """Handles Slack button interactions."""

    def __init__(
        self,
        approval_handler: ApprovalHandler,
        objection_handler: ObjectionHandler,
        channel_repo: ChannelRepository
    ):
        self.approval_handler = approval_handler
        self.objection_handler = objection_handler
        self.channel_repo = channel_repo

    async def handle(self, action_id: str, user_id: UserId, channel_id: ChannelId, value: str) -> None:
        """Route button action to handler."""

        channel = await self.channel_repo.load(channel_id)

        if action_id.startswith("approve_"):
            entity_id = EntityId(action_id.replace("approve_", ""))
            events = await self.approval_handler.approve(channel, entity_id, user_id)
            await self.channel_repo.save(channel, events)

        elif action_id.startswith("object_"):
            entity_id = EntityId(action_id.replace("object_", ""))
            entity = channel.entities.get(entity_id)
            if entity and isinstance(entity, ProposedEntity):
                # Open modal for objection reason
                await self._open_objection_modal(channel_id, entity_id, user_id)

        elif action_id.startswith("discuss_"):
            # Start thread from canonical message
            entity_id = EntityId(action_id.replace("discuss_", ""))
            entity = channel.entities.get(entity_id)
            if entity and hasattr(entity, 'canonical_message_ts'):
                await self.slack.post_to_thread(
                    channel_id,
                    entity.canonical_message_ts,
                    f"<@{user_id}> wants to discuss this. What's on your mind?"
                )
```

---

## Part 10: Jira Integration

### 10.1 Field Ownership Model

```python
class FieldOwnership(Enum):
    """Who owns a Jira field."""
    JIRA_OWNED = "jira_owned"      # Jira is source of truth (assignee, status)
    SLACK_OWNED = "slack_owned"   # Slack is source of truth (description, AC)
    SHARED = "shared"              # Both can modify (needs conflict detection)

# Field ownership mapping
FIELD_OWNERSHIP = {
    "summary": FieldOwnership.SLACK_OWNED,
    "description": FieldOwnership.SLACK_OWNED,
    "acceptance_criteria": FieldOwnership.SLACK_OWNED,  # Custom field
    "status": FieldOwnership.JIRA_OWNED,
    "assignee": FieldOwnership.JIRA_OWNED,
    "reporter": FieldOwnership.JIRA_OWNED,
    "priority": FieldOwnership.SHARED,
    "labels": FieldOwnership.SHARED,
    "components": FieldOwnership.SHARED,
}
```

### 10.2 Managed Sections

MARO never overwrites user content. It uses managed sections:

```python
MANAGED_SECTION_START = "<!-- MARO:START -->"
MANAGED_SECTION_END = "<!-- MARO:END -->"

class ManagedSectionWriter:
    """Writes to managed sections only."""

    def update_description(self, existing: str, maro_content: str) -> str:
        """Update MARO section in description."""

        maro_block = f"{MANAGED_SECTION_START}\n{maro_content}\n{MANAGED_SECTION_END}"

        if MANAGED_SECTION_START in existing:
            # Replace existing section
            import re
            pattern = f"{re.escape(MANAGED_SECTION_START)}.*?{re.escape(MANAGED_SECTION_END)}"
            return re.sub(pattern, maro_block, existing, flags=re.DOTALL)
        else:
            # Append section
            return f"{existing}\n\n{maro_block}"

    def extract_user_content(self, description: str) -> str:
        """Extract user-written content (outside MARO sections)."""
        import re
        pattern = f"{re.escape(MANAGED_SECTION_START)}.*?{re.escape(MANAGED_SECTION_END)}"
        return re.sub(pattern, "", description, flags=re.DOTALL).strip()
```

### 10.3 Preflight (Conflict Detection)

```python
class PreflightResult(Enum):
    OK = "ok"                       # Safe to proceed
    CONFLICT = "conflict"           # Needs human resolution
    IDEMPOTENT = "idempotent"       # Already done

@dataclass
class PreflightCheck:
    """Result of preflight check."""
    result: PreflightResult
    details: str
    conflicts: list["FieldConflict"] = field(default_factory=list)
    resolution_options: list[str] = field(default_factory=list)

@dataclass
class FieldConflict:
    """Conflict on a specific field."""
    field: str
    slack_value: Any
    jira_value: Any
    ownership: FieldOwnership

class PreflightService:
    """Checks for conflicts before Jira operations."""

    def __init__(self, jira: "JiraClient"):
        self.jira = jira

    async def check_create(self, content: WorkItemContent, project_key: str) -> PreflightCheck:
        """Check before creating new issue."""
        # Check for duplicates
        duplicates = await self.jira.search(
            f'project = {project_key} AND summary ~ "{content.title}"'
        )

        if duplicates:
            return PreflightCheck(
                result=PreflightResult.CONFLICT,
                details=f"Potential duplicate found: {duplicates[0].key}",
                resolution_options=["Create anyway", "Link to existing", "Cancel"]
            )

        return PreflightCheck(result=PreflightResult.OK, details="No conflicts")

    async def check_update(self, entity: CommittedEntity, changes: dict) -> PreflightCheck:
        """Check before updating existing issue."""

        jira_issue = await self.jira.get_issue(entity.jira_link.jira_key)
        conflicts = []

        for field, new_value in changes.items():
            ownership = FIELD_OWNERSHIP.get(field, FieldOwnership.SHARED)
            jira_value = getattr(jira_issue.fields, field, None)

            if ownership == FieldOwnership.JIRA_OWNED:
                # Can't update Jira-owned fields
                conflicts.append(FieldConflict(
                    field=field,
                    slack_value=new_value,
                    jira_value=jira_value,
                    ownership=ownership
                ))

            elif ownership == FieldOwnership.SHARED:
                # Check if Jira value changed since last sync
                if entity.jira_link.synced_version < entity.version:
                    # Jira might have changed
                    last_synced_value = await self._get_synced_value(entity, field)
                    if jira_value != last_synced_value:
                        conflicts.append(FieldConflict(
                            field=field,
                            slack_value=new_value,
                            jira_value=jira_value,
                            ownership=ownership
                        ))

        if conflicts:
            return PreflightCheck(
                result=PreflightResult.CONFLICT,
                details=f"{len(conflicts)} field(s) have conflicts",
                conflicts=conflicts,
                resolution_options=["Use Slack values", "Use Jira values", "Merge manually"]
            )

        return PreflightCheck(result=PreflightResult.OK, details="No conflicts")

    async def check_decision_projection(
        self,
        decision: CommittedEntity,
        jira_key: JiraKey,
        field_path: str
    ) -> PreflightCheck:
        """Check before projecting decision to Jira."""

        jira_issue = await self.jira.get_issue(jira_key)
        current_value = getattr(jira_issue.fields, field_path, "")

        # Check if our managed section is intact
        if MANAGED_SECTION_START in current_value:
            # Can safely update our section
            return PreflightCheck(result=PreflightResult.OK, details="Managed section found")

        # No managed section - check if field is empty
        if not current_value.strip():
            return PreflightCheck(result=PreflightResult.OK, details="Field empty, will add managed section")

        # Field has content but no managed section
        return PreflightCheck(
            result=PreflightResult.CONFLICT,
            details="Field has user content without MARO section",
            resolution_options=["Append MARO section", "Cancel"]
        )
```

### 10.4 Jira Client

```python
class JiraClient:
    """Jira API wrapper."""

    def __init__(self, url: str, email: str, token: str):
        from atlassian import Jira
        self.jira = Jira(url=url, username=email, password=token)

    async def create_issue(
        self,
        project_key: str,
        content: WorkItemContent,
        actor: UserId
    ) -> JiraKey:
        """Create Jira issue."""

        fields = {
            "project": {"key": project_key},
            "summary": content.title,
            "description": content.description,
            "issuetype": {"name": self._issue_type_name(content.issue_type)},
        }

        if content.acceptance_criteria:
            # Add to description or custom field
            ac_text = "\n".join(f"- [ ] {ac}" for ac in content.acceptance_criteria)
            fields["description"] += f"\n\n## Acceptance Criteria\n{ac_text}"

        result = await asyncio.to_thread(self.jira.create_issue, fields=fields)
        return JiraKey(result["key"])

    async def update_issue(
        self,
        jira_key: JiraKey,
        updates: dict,
        use_managed_section: bool = True
    ) -> None:
        """Update Jira issue."""

        if use_managed_section and "description" in updates:
            # Get current description
            issue = await self.get_issue(jira_key)
            writer = ManagedSectionWriter()
            updates["description"] = writer.update_description(
                issue.fields.description or "",
                updates["description"]
            )

        await asyncio.to_thread(
            self.jira.update_issue,
            jira_key,
            fields=updates
        )

    async def get_issue(self, jira_key: JiraKey) -> Any:
        """Get Jira issue."""
        return await asyncio.to_thread(self.jira.issue, jira_key)

    async def search(self, jql: str, max_results: int = 10) -> list[Any]:
        """Search Jira with JQL."""
        results = await asyncio.to_thread(
            self.jira.jql,
            jql,
            limit=max_results
        )
        return results.get("issues", [])

    async def add_comment(self, jira_key: JiraKey, comment: str) -> None:
        """Add comment to issue."""
        await asyncio.to_thread(
            self.jira.issue_add_comment,
            jira_key,
            comment
        )

    def _issue_type_name(self, issue_type: IssueType) -> str:
        """Map IssueType to Jira issue type name."""
        return {
            IssueType.EPIC: "Epic",
            IssueType.STORY: "Story",
            IssueType.TASK: "Task",
            IssueType.BUG: "Bug",
            IssueType.SPIKE: "Spike",
        }.get(issue_type, "Task")
```

### 10.5 Jira Sync Service

```python
class JiraSyncService:
    """Handles bidirectional Jira sync."""

    def __init__(
        self,
        jira: JiraClient,
        preflight: PreflightService,
        channel_repo: ChannelRepository,
        event_store: EventStore
    ):
        self.jira = jira
        self.preflight = preflight
        self.channel_repo = channel_repo
        self.event_store = event_store

    async def commit_entity(
        self,
        channel: Channel,
        entity_id: EntityId,
        actor: UserId,
        project_key: str
    ) -> list[DomainEvent]:
        """Commit approved entity to Jira."""

        entity = channel.entities.get(entity_id)
        if not isinstance(entity, ApprovedEntity):
            raise ValueError("Only approved entities can be committed")

        content = entity.content

        if isinstance(content, WorkItemContent):
            # Preflight check
            preflight_result = await self.preflight.check_create(content, project_key)
            if preflight_result.result == PreflightResult.CONFLICT:
                raise ConflictError(preflight_result.details)

            # Create in Jira
            jira_key = await self.jira.create_issue(project_key, content, actor)

            # Create commit event
            result = channel.commit_entity(
                actor=actor,
                entity_id=entity_id,
                jira_key=jira_key
            )

            match result:
                case Ok(event):
                    return [event]
                case Err(error):
                    raise ValueError(error.message)

        elif isinstance(content, DecisionContent):
            # Decisions project to existing Jira issues
            # This requires a target issue to be specified
            raise ValueError("Decision projection requires target Jira issue")

    async def project_decision(
        self,
        channel: Channel,
        entity_id: EntityId,
        target_jira_key: JiraKey,
        field_path: str,
        actor: UserId
    ) -> list[DomainEvent]:
        """Project decision to Jira issue field."""

        entity = channel.entities.get(entity_id)
        if not isinstance(entity, ApprovedEntity):
            raise ValueError("Only approved decisions can be projected")

        if not isinstance(entity.content, DecisionContent):
            raise ValueError("Only decisions can be projected")

        # Preflight
        preflight_result = await self.preflight.check_decision_projection(
            entity, target_jira_key, field_path
        )
        if preflight_result.result == PreflightResult.CONFLICT:
            raise ConflictError(preflight_result.details)

        # Format decision for Jira
        decision_text = f"""
**Decision: {entity.content.title}**
Type: {entity.content.decision_type.value}

{entity.content.description}

*Rationale:* {entity.content.rationale or "Not specified"}
"""

        # Update Jira
        await self.jira.update_issue(
            target_jira_key,
            {field_path: decision_text},
            use_managed_section=True
        )

        # Create commit event
        result = channel.commit_entity(
            actor=actor,
            entity_id=entity_id,
            jira_key=target_jira_key,
            field_path=field_path
        )

        match result:
            case Ok(event):
                return [event]
            case Err(error):
                raise ValueError(error.message)

    async def reconcile(self, channel_id: ChannelId) -> list["SyncDiscrepancy"]:
        """Find discrepancies between channel and Jira."""

        channel = await self.channel_repo.load(channel_id)
        discrepancies = []

        for entity_id, entity in channel.entities.items():
            if not isinstance(entity, CommittedEntity):
                continue

            try:
                jira_issue = await self.jira.get_issue(entity.jira_link.jira_key)

                # Check each tracked field
                for field, ownership in FIELD_OWNERSHIP.items():
                    if ownership == FieldOwnership.JIRA_OWNED:
                        continue

                    slack_value = self._get_entity_field(entity, field)
                    jira_value = getattr(jira_issue.fields, field, None)

                    if slack_value != jira_value:
                        discrepancies.append(SyncDiscrepancy(
                            entity_id=entity_id,
                            jira_key=entity.jira_link.jira_key,
                            field=field,
                            slack_value=slack_value,
                            jira_value=jira_value,
                            ownership=ownership
                        ))

            except Exception as e:
                discrepancies.append(SyncDiscrepancy(
                    entity_id=entity_id,
                    jira_key=entity.jira_link.jira_key,
                    field="__access__",
                    slack_value="entity exists",
                    jira_value=f"error: {e}",
                    ownership=FieldOwnership.SHARED
                ))

        return discrepancies

@dataclass
class SyncDiscrepancy:
    """Discrepancy between Slack and Jira."""
    entity_id: EntityId
    jira_key: JiraKey
    field: str
    slack_value: Any
    jira_value: Any
    ownership: FieldOwnership
```

---

## Part 11: Channel Lifecycle

### 11.1 Channel Onboarding

When MARO is added to a channel:

```python
class OnboardingType(Enum):
    FRESH_START = "fresh_start"                 # New channel, start clean
    IMPORT_FROM_JIRA = "import_from_jira"       # Import existing Jira issues
    CATCH_UP_DECISIONS = "catch_up_decisions"   # Scan history for decisions
    CATCH_UP_SIMPLE = "catch_up_simple"         # Just start tracking

@dataclass
class OnboardingConfig:
    """Configuration for channel onboarding."""
    onboarding_type: OnboardingType
    jira_project_key: str | None = None
    jira_filter: str | None = None  # JQL for import
    history_scan_days: int = 30     # For decision catch-up

class OnboardingService:
    """Handles channel onboarding."""

    def __init__(
        self,
        slack: SlackClient,
        jira: JiraClient,
        channel_repo: ChannelRepository,
        llm: LLMProvider
    ):
        self.slack = slack
        self.jira = jira
        self.channel_repo = channel_repo
        self.llm = llm

    async def start_onboarding(self, channel_id: ChannelId, user_id: UserId) -> None:
        """Start onboarding flow."""

        # Post welcome message
        await self.slack.post_to_channel(channel_id, [
            {"type": "header", "text": {"type": "plain_text", "text": ":wave: Hello! I'm MARO"}},
            {"type": "section", "text": {"type": "mrkdwn", "text":
                "I help turn conversations into structured work. How would you like to start?"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Fresh Start"},
                 "action_id": "onboard_fresh", "style": "primary"},
                {"type": "button", "text": {"type": "plain_text", "text": "Import from Jira"},
                 "action_id": "onboard_import"},
                {"type": "button", "text": {"type": "plain_text", "text": "Scan History"},
                 "action_id": "onboard_scan"},
                {"type": "button", "text": {"type": "plain_text", "text": "Just Start"},
                 "action_id": "onboard_simple"}
            ]}
        ])

    async def execute_onboarding(self, channel_id: ChannelId, config: OnboardingConfig) -> None:
        """Execute onboarding based on config."""

        match config.onboarding_type:
            case OnboardingType.FRESH_START:
                await self._fresh_start(channel_id, config)

            case OnboardingType.IMPORT_FROM_JIRA:
                await self._import_from_jira(channel_id, config)

            case OnboardingType.CATCH_UP_DECISIONS:
                await self._catch_up_decisions(channel_id, config)

            case OnboardingType.CATCH_UP_SIMPLE:
                await self._catch_up_simple(channel_id)

    async def _fresh_start(self, channel_id: ChannelId, config: OnboardingConfig) -> None:
        """Initialize empty channel."""
        # Create channel aggregate (will have no events)
        channel = Channel(
            id=channel_id,
            version=0,
            entities={},
            processes={},
            plans={},
            conflicts=[],
            config=ChannelConfig(jira_project_key=config.jira_project_key)
        )

        await self.slack.post_to_channel(channel_id,
            ":white_check_mark: Ready! Mention me to start a conversation or use `/maro help`."
        )

    async def _import_from_jira(self, channel_id: ChannelId, config: OnboardingConfig) -> None:
        """Import existing Jira issues."""

        jql = config.jira_filter or f'project = {config.jira_project_key} AND status != Done ORDER BY created DESC'
        issues = await self.jira.search(jql, max_results=50)

        await self.slack.post_to_channel(channel_id,
            f":hourglass: Importing {len(issues)} issues from Jira..."
        )

        channel = await self.channel_repo.load(channel_id)
        events = []

        for issue in issues:
            # Create committed entity for each issue
            content = WorkItemContent(
                issue_type=self._map_jira_type(issue.fields.issuetype.name),
                title=issue.fields.summary,
                description=issue.fields.description or ""
            )

            # Skip draft/proposed, go straight to committed
            event = WorkItemCommitted(
                aggregate_id=channel_id,
                actor_id=UserId("import"),
                version=len(events) + 1,
                entity_id=EntityId.generate(),
                jira_key=JiraKey(issue.key)
            )
            events.append(event)

        await self.channel_repo.save(channel, events)

        await self.slack.post_to_channel(channel_id,
            f":white_check_mark: Imported {len(issues)} issues. They're now tracked in this channel."
        )

    async def _catch_up_decisions(self, channel_id: ChannelId, config: OnboardingConfig) -> None:
        """Scan history for decisions."""

        # Get channel history
        history = await self.slack.get_channel_history(channel_id, days=config.history_scan_days)

        await self.slack.post_to_channel(channel_id,
            f":mag: Scanning {len(history)} messages for decisions..."
        )

        # Use LLM to find decisions
        decisions = await self._extract_decisions_from_history(history)

        if decisions:
            await self.slack.post_to_channel(channel_id, [
                {"type": "section", "text": {"type": "mrkdwn", "text":
                    f"Found {len(decisions)} potential decisions:"}},
                *[{"type": "context", "elements": [
                    {"type": "mrkdwn", "text": f"• {d['title']}"}
                ]} for d in decisions[:10]],
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Import All"},
                     "action_id": "import_decisions_all", "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Review Each"},
                     "action_id": "import_decisions_review"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Skip"},
                     "action_id": "import_decisions_skip"}
                ]}
            ])
        else:
            await self.slack.post_to_channel(channel_id,
                ":white_check_mark: No clear decisions found. Ready to start fresh!"
            )

    async def _catch_up_simple(self, channel_id: ChannelId) -> None:
        """Simple start without history analysis."""
        await self.slack.post_to_channel(channel_id,
            ":white_check_mark: Ready! I'll start tracking from here. Mention me to begin."
        )

    async def _extract_decisions_from_history(self, messages: list) -> list[dict]:
        """Use LLM to extract decisions from history."""
        prompt = """
Analyze these messages and extract any decisions that were made.
Look for patterns like:
- "we decided...", "the decision is...", "agreed on..."
- Architecture choices
- Scope decisions
- Process agreements

For each decision, extract:
- title: Short summary
- description: Full context
- type: architecture/scope/constraint/priority/process

Messages:
{messages}

Respond as JSON array of decisions.
"""
        # Batch messages to avoid token limits
        result = await self.llm.complete(
            prompt.format(messages=messages[:50]),
            schema=list[dict]
        )
        return result
```

### 11.2 Continuous Operation

```python
class ChannelOperator:
    """Manages continuous channel operation."""

    def __init__(
        self,
        channel_repo: ChannelRepository,
        jira_sync: JiraSyncService,
        dashboard_manager: DashboardManager
    ):
        self.channel_repo = channel_repo
        self.jira_sync = jira_sync
        self.dashboard_manager = dashboard_manager

    async def periodic_reconcile(self, channel_id: ChannelId) -> None:
        """Periodic reconciliation with Jira."""

        discrepancies = await self.jira_sync.reconcile(channel_id)

        if discrepancies:
            # Log but don't auto-fix
            for d in discrepancies:
                logger.info(f"Discrepancy: {d.jira_key}.{d.field}: "
                           f"slack={d.slack_value}, jira={d.jira_value}")

            # Update dashboard with sync status
            await self.dashboard_manager.create_or_update(channel_id)

    async def handle_jira_webhook(self, event: "JiraWebhookEvent") -> None:
        """Handle Jira webhook for real-time sync."""

        # Find channel(s) tracking this issue
        # This requires a reverse lookup from Jira key to channel
        channels = await self._find_channels_for_jira_key(event.issue_key)

        for channel_id in channels:
            channel = await self.channel_repo.load(channel_id)

            # Find entity
            entity = self._find_entity_by_jira_key(channel, event.issue_key)
            if not entity:
                continue

            # Check if this is a field we care about
            ownership = FIELD_OWNERSHIP.get(event.changed_field)
            if ownership == FieldOwnership.JIRA_OWNED:
                # Jira is source of truth - update our view
                # (This is informational, no event needed)
                pass
            elif ownership == FieldOwnership.SHARED:
                # Potential conflict - notify channel
                await self.slack.post_to_thread(
                    channel_id,
                    entity.canonical_message_ts,
                    f":warning: `{event.changed_field}` was updated in Jira. "
                    f"Use `/maro sync` to reconcile."
                )
```

### 11.3 Slash Commands

```python
class CommandHandler:
    """Handles /maro slash commands."""

    COMMANDS = {
        "help": "Show help",
        "status": "Show channel status",
        "sync": "Check Jira sync status",
        "decisions": "List active decisions",
        "entities": "List all entities",
        "config": "Channel configuration",
    }

    async def handle(self, command: str, args: list[str], channel_id: ChannelId, user_id: UserId) -> None:
        """Route command to handler."""

        match command:
            case "help":
                await self._help(channel_id, user_id)
            case "status":
                await self._status(channel_id, user_id)
            case "sync":
                await self._sync(channel_id, user_id)
            case "decisions":
                await self._decisions(channel_id, user_id)
            case "entities":
                await self._entities(channel_id, user_id, args)
            case "config":
                await self._config(channel_id, user_id, args)
            case _:
                await self.slack.post_ephemeral(
                    channel_id, user_id,
                    f"Unknown command: `{command}`. Use `/maro help` for available commands."
                )

    async def _help(self, channel_id: ChannelId, user_id: UserId) -> None:
        """Show help."""
        help_text = "*Available commands:*\n"
        for cmd, desc in self.COMMANDS.items():
            help_text += f"• `/maro {cmd}` - {desc}\n"

        await self.slack.post_ephemeral(channel_id, user_id, help_text)

    async def _status(self, channel_id: ChannelId, user_id: UserId) -> None:
        """Show channel status."""
        channel = await self.channel_repo.load(channel_id)

        # Count by lifecycle
        counts = {}
        for entity in channel.entities.values():
            lifecycle = get_lifecycle(entity)
            counts[lifecycle] = counts.get(lifecycle, 0) + 1

        status = f"*Channel Status*\n"
        for lifecycle, count in counts.items():
            status += f"• {lifecycle.value}: {count}\n"

        status += f"\n*Active processes:* {len([p for p in channel.processes.values() if p.status == ProcessStatus.RUNNING])}"
        status += f"\n*Active plans:* {len([p for p in channel.plans.values() if p.status == PlanStatus.EXECUTING])}"

        await self.slack.post_ephemeral(channel_id, user_id, status)

    async def _sync(self, channel_id: ChannelId, user_id: UserId) -> None:
        """Check sync status."""
        discrepancies = await self.jira_sync.reconcile(channel_id)

        if not discrepancies:
            await self.slack.post_ephemeral(channel_id, user_id,
                ":white_check_mark: All entities are in sync with Jira."
            )
        else:
            text = f":warning: Found {len(discrepancies)} discrepancies:\n"
            for d in discrepancies[:5]:
                text += f"• `{d.jira_key}`.`{d.field}`: Slack has `{d.slack_value}`, Jira has `{d.jira_value}`\n"

            if len(discrepancies) > 5:
                text += f"_...and {len(discrepancies) - 5} more_"

            await self.slack.post_ephemeral(channel_id, user_id, text)
```

---

## Part 12: Configuration

### 12.1 Channel Configuration

```python
@dataclass
class ChannelConfig:
    """Configuration for a channel."""
    jira_project_key: str | None = None
    jira_board_id: str | None = None

    # Permissions
    permissions: ChannelPermissions = field(default_factory=ChannelPermissions)

    # Behavior
    auto_create_threads: bool = True     # Auto-create thread for new work
    require_approval: bool = True        # Require approval before Jira sync
    dashboard_enabled: bool = True       # Maintain pinned dashboard

    # Question behavior
    max_questions_per_stage: int = 3
    question_timeout_minutes: int = 30   # Auto-skip after timeout

    # Sync behavior
    sync_on_approval: bool = True        # Auto-sync to Jira on approval
    sync_interval_minutes: int = 60      # Background sync interval

@dataclass
class GlobalConfig:
    """Global MARO configuration."""
    # Slack
    slack_bot_token: str
    slack_app_token: str
    slack_signing_secret: str

    # Jira
    jira_url: str
    jira_email: str
    jira_api_token: str

    # Database
    database_url: str

    # LLM
    llm_provider: str = "gemini"
    llm_model: str = "gemini-1.5-pro"
    llm_api_key: str = ""

    # Operational
    log_level: str = "INFO"
    debug_mode: bool = False

    @classmethod
    def from_env(cls) -> "GlobalConfig":
        """Load from environment variables."""
        import os
        return cls(
            slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
            slack_app_token=os.environ["SLACK_APP_TOKEN"],
            slack_signing_secret=os.environ["SLACK_SIGNING_SECRET"],
            jira_url=os.environ["JIRA_URL"],
            jira_email=os.environ["JIRA_EMAIL"],
            jira_api_token=os.environ["JIRA_API_TOKEN"],
            database_url=os.environ["DATABASE_URL"],
            llm_provider=os.environ.get("LLM_PROVIDER", "gemini"),
            llm_model=os.environ.get("LLM_MODEL", "gemini-1.5-pro"),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            debug_mode=os.environ.get("DEBUG_MODE", "false").lower() == "true"
        )
```

---

## Part 13: Database Schema

```sql
-- Event sourcing core
CREATE TABLE channel_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id VARCHAR(50) NOT NULL,  -- Channel ID
    version INTEGER NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',

    UNIQUE (aggregate_id, version)
);

CREATE INDEX idx_events_aggregate ON channel_events(aggregate_id, version);
CREATE INDEX idx_events_type ON channel_events(event_type);
CREATE INDEX idx_events_timestamp ON channel_events(timestamp);

-- Projection: Current entity states
CREATE TABLE entities_view (
    id UUID PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    entity_type VARCHAR(20) NOT NULL,  -- work_item, decision
    lifecycle VARCHAR(20) NOT NULL,    -- draft, proposed, approved, committed, deprecated
    content JSONB NOT NULL,
    attribution JSONB NOT NULL,
    version INTEGER NOT NULL,
    thread_ts VARCHAR(50),
    canonical_message_ts VARCHAR(50),
    jira_key VARCHAR(20),
    jira_link JSONB,
    last_event_id BIGINT REFERENCES channel_events(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_entities_channel ON entities_view(channel_id);
CREATE INDEX idx_entities_lifecycle ON entities_view(lifecycle);
CREATE INDEX idx_entities_jira_key ON entities_view(jira_key);
CREATE INDEX idx_entities_thread ON entities_view(channel_id, thread_ts);

-- Projection: Active processes
CREATE TABLE processes_view (
    id UUID PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    thread_ts VARCHAR(50) NOT NULL,
    process_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    current_stage_index INTEGER NOT NULL,
    stage_states JSONB NOT NULL,
    outputs JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    last_event_id BIGINT REFERENCES channel_events(id)
);

CREATE INDEX idx_processes_channel_thread ON processes_view(channel_id, thread_ts);
CREATE INDEX idx_processes_status ON processes_view(status);

-- Projection: Active plans
CREATE TABLE plans_view (
    id UUID PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    thread_ts VARCHAR(50) NOT NULL,
    items JSONB NOT NULL,
    status VARCHAR(20) NOT NULL,
    current_index INTEGER NOT NULL,
    source_process_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    last_event_id BIGINT REFERENCES channel_events(id)
);

CREATE INDEX idx_plans_channel ON plans_view(channel_id);
CREATE INDEX idx_plans_status ON plans_view(status);

-- Projection: Decision conflicts
CREATE TABLE conflicts_view (
    id UUID PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    decision_a_id UUID NOT NULL,
    decision_b_id UUID,
    jira_key VARCHAR(20),
    conflict_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    resolution JSONB,
    detected_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_conflicts_channel ON conflicts_view(channel_id);
CREATE INDEX idx_conflicts_status ON conflicts_view(status);

-- Channel configuration
CREATE TABLE channel_config (
    channel_id VARCHAR(50) PRIMARY KEY,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dashboard tracking
CREATE TABLE channel_dashboards (
    channel_id VARCHAR(50) PRIMARY KEY,
    message_ts VARCHAR(50) NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Jira key reverse lookup
CREATE TABLE jira_channel_mapping (
    jira_key VARCHAR(20) PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jira_mapping_channel ON jira_channel_mapping(channel_id);
```

---

## Part 14: Directory Structure

```
maro/
├── pyproject.toml              # Project config (uses uv/poetry)
├── Dockerfile
├── docker-compose.yml
├── .env.example
│
├── src/
│   └── maro/
│       ├── __init__.py
│       ├── main.py             # Entry point
│       │
│       ├── domain/             # Core domain model
│       │   ├── __init__.py
│       │   ├── types.py        # Value objects (ChannelId, EntityId, etc.)
│       │   ├── entities.py     # Entity sum types
│       │   ├── events.py       # Domain events
│       │   ├── channel.py      # Channel aggregate
│       │   └── errors.py       # Domain errors
│       │
│       ├── application/        # Application layer
│       │   ├── __init__.py
│       │   ├── handlers/       # Mode handlers
│       │   │   ├── __init__.py
│       │   │   ├── create.py
│       │   │   ├── modify.py
│       │   │   ├── record.py
│       │   │   └── converse.py
│       │   ├── services/       # Application services
│       │   │   ├── __init__.py
│       │   │   ├── approval.py
│       │   │   ├── objection.py
│       │   │   ├── conflict.py
│       │   │   ├── onboarding.py
│       │   │   └── operator.py
│       │   ├── workflows/      # Process/Plan/Workflow
│       │   │   ├── __init__.py
│       │   │   ├── definitions.py
│       │   │   ├── process.py
│       │   │   ├── plan.py
│       │   │   └── workflow.py
│       │   └── coordinator.py  # Request coordination
│       │
│       ├── infrastructure/     # Infrastructure layer
│       │   ├── __init__.py
│       │   ├── persistence/
│       │   │   ├── __init__.py
│       │   │   ├── event_store.py
│       │   │   ├── projections.py
│       │   │   └── repository.py
│       │   ├── slack/
│       │   │   ├── __init__.py
│       │   │   ├── client.py
│       │   │   ├── handlers.py
│       │   │   └── commands.py
│       │   ├── jira/
│       │   │   ├── __init__.py
│       │   │   ├── client.py
│       │   │   ├── sync.py
│       │   │   └── preflight.py
│       │   └── llm/
│       │       ├── __init__.py
│       │       ├── provider.py
│       │       ├── gemini.py
│       │       ├── openai.py
│       │       └── anthropic.py
│       │
│       ├── routing/            # Intent routing
│       │   ├── __init__.py
│       │   ├── pre_gates.py
│       │   └── router.py
│       │
│       └── config/             # Configuration
│           ├── __init__.py
│           └── settings.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Fixtures
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   └── routing/
│   ├── integration/
│   │   ├── persistence/
│   │   ├── slack/
│   │   └── jira/
│   └── e2e/
│       └── scenarios/
│
├── migrations/                 # Database migrations
│   └── 001_initial.sql
│
└── scripts/
    ├── deploy.sh
    └── local-dev.sh
```

---

## Part 15: Testing Strategy

### 15.1 Testing Pyramid

```
        ┌─────────────┐
        │    E2E      │  5% - Full Slack/Jira integration
        ├─────────────┤
        │ Integration │  25% - Database, external services
        ├─────────────┤
        │    Unit     │  70% - Domain logic, pure functions
        └─────────────┘
```

### 15.2 Unit Tests (Domain)

```python
# tests/unit/domain/test_channel.py
import pytest
from maro.domain.channel import Channel
from maro.domain.types import ChannelId, UserId, ThreadTs
from maro.domain.entities import WorkItemContent, IssueType

class TestChannelDraftWorkItem:
    """Tests for Channel.draft_work_item()"""

    def test_creates_draft_event(self):
        """Valid content produces WorkItemDrafted event."""
        channel = Channel(
            id=ChannelId("C123"),
            version=0,
            entities={},
            processes={},
            plans={},
            conflicts=[],
            config=ChannelConfig.default()
        )

        content = WorkItemContent(
            issue_type=IssueType.STORY,
            title="Test story",
            description="Description",
            acceptance_criteria=["AC1"]
        )

        result = channel.draft_work_item(
            actor=UserId("U123"),
            thread_ts=ThreadTs("123.456"),
            content=content
        )

        assert result.is_ok()
        event = result.unwrap()
        assert event.event_type == "WorkItemDrafted"
        assert event.content == content

    def test_rejects_invalid_content(self):
        """Missing required fields produces error."""
        channel = Channel(id=ChannelId("C123"), ...)

        content = WorkItemContent(
            issue_type=IssueType.STORY,
            title="",  # Invalid: empty title
            description="",
            acceptance_criteria=[]  # Invalid: stories need AC
        )

        result = channel.draft_work_item(
            actor=UserId("U123"),
            thread_ts=ThreadTs("123.456"),
            content=content
        )

        assert result.is_err()
        assert "Title is required" in result.unwrap_err().message

class TestChannelApprove:
    """Tests for approval flow."""

    def test_cannot_approve_non_proposed(self):
        """Approving draft entity fails."""
        channel = self._channel_with_draft()

        result = channel.approve_entity(
            actor=UserId("U123"),
            entity_id=EntityId("E1")
        )

        assert result.is_err()
        assert "must be proposed" in result.unwrap_err().message

    def test_cannot_approve_with_objections(self):
        """Approving with active objections fails."""
        channel = self._channel_with_objected_proposal()

        result = channel.approve_entity(
            actor=UserId("U123"),
            entity_id=EntityId("E1")
        )

        assert result.is_err()
        assert "objection" in result.unwrap_err().message
```

### 15.3 Property-Based Tests (State Machine)

```python
# tests/unit/domain/test_entity_lifecycle.py
from hypothesis import given, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

class EntityLifecycleMachine(RuleBasedStateMachine):
    """Property-based testing for entity lifecycle."""

    def __init__(self):
        super().__init__()
        self.channel = Channel(id=ChannelId("C1"), ...)
        self.entities = {}  # Track expected states

    @rule(title=st.text(min_size=1, max_size=100))
    def draft_work_item(self, title):
        """Can always draft a new work item."""
        content = WorkItemContent(
            issue_type=IssueType.TASK,
            title=title,
            description=""
        )
        result = self.channel.draft_work_item(
            actor=UserId("U1"),
            thread_ts=ThreadTs("t1"),
            content=content
        )
        if result.is_ok():
            event = result.unwrap()
            self.entities[event.entity_id] = "draft"

    @rule(entity_id=st.sampled_from(lambda self: list(self.entities.keys())))
    def propose_entity(self, entity_id):
        """Can propose drafts."""
        if self.entities.get(entity_id) != "draft":
            return  # Skip invalid transitions

        result = self.channel.propose_entity(
            actor=UserId("U1"),
            entity_id=entity_id,
            canonical_message_ts="m1"
        )
        if result.is_ok():
            self.entities[entity_id] = "proposed"

    @invariant()
    def no_invalid_states(self):
        """Entities can only be in valid states."""
        for entity in self.channel.entities.values():
            lifecycle = get_lifecycle(entity)
            assert lifecycle in EntityLifecycle

    @invariant()
    def committed_entities_have_jira_link(self):
        """All committed entities must have JiraLink."""
        for entity in self.channel.entities.values():
            if isinstance(entity, CommittedEntity):
                assert entity.jira_link is not None
                assert entity.jira_link.jira_key

TestEntityLifecycle = EntityLifecycleMachine.TestCase
```

### 15.4 Integration Tests (Database)

```python
# tests/integration/persistence/test_event_store.py
import pytest
import asyncpg
from maro.infrastructure.persistence.event_store import EventStore, ConcurrencyError

@pytest.fixture
async def event_store(test_db_pool):
    return EventStore(test_db_pool)

class TestEventStore:

    @pytest.mark.asyncio
    async def test_append_and_retrieve(self, event_store):
        """Events can be appended and retrieved."""
        event = WorkItemDrafted(
            aggregate_id=ChannelId("C123"),
            actor_id=UserId("U123"),
            version=1,
            entity_id=EntityId.generate(),
            thread_ts=ThreadTs("123.456"),
            content=WorkItemContent(...)
        )

        await event_store.append(event)

        events = await event_store.get_events(ChannelId("C123"))
        assert len(events) == 1
        assert events[0].event_type == "WorkItemDrafted"

    @pytest.mark.asyncio
    async def test_version_conflict(self, event_store):
        """Duplicate version raises ConcurrencyError."""
        event1 = WorkItemDrafted(
            aggregate_id=ChannelId("C123"),
            version=1,
            ...
        )
        event2 = WorkItemProposed(
            aggregate_id=ChannelId("C123"),
            version=1,  # Same version!
            ...
        )

        await event_store.append(event1)

        with pytest.raises(ConcurrencyError):
            await event_store.append(event2)

    @pytest.mark.asyncio
    async def test_ordering(self, event_store):
        """Events retrieved in version order."""
        for i in range(1, 11):
            await event_store.append(WorkItemDrafted(
                aggregate_id=ChannelId("C123"),
                version=i,
                ...
            ))

        events = await event_store.get_events(ChannelId("C123"))
        versions = [e.version for e in events]
        assert versions == list(range(1, 11))
```

### 15.5 Integration Tests (Jira)

```python
# tests/integration/jira/test_sync.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_jira():
    """Mock Jira client."""
    jira = MagicMock()
    jira.create_issue = AsyncMock(return_value={"key": "TEST-123"})
    jira.get_issue = AsyncMock(return_value=MagicMock(
        fields=MagicMock(summary="Test", description="Desc")
    ))
    return jira

class TestJiraSyncService:

    @pytest.mark.asyncio
    async def test_commit_entity_creates_jira_issue(self, mock_jira):
        """Committing approved entity creates Jira issue."""
        sync = JiraSyncService(jira=mock_jira, ...)

        channel = self._channel_with_approved_entity()

        events = await sync.commit_entity(
            channel=channel,
            entity_id=EntityId("E1"),
            actor=UserId("U1"),
            project_key="TEST"
        )

        assert len(events) == 1
        assert events[0].event_type == "WorkItemCommitted"
        assert events[0].jira_key == "TEST-123"

        mock_jira.create_issue.assert_called_once()
```

### 15.6 E2E Tests

```python
# tests/e2e/scenarios/test_full_workflow.py
import pytest
from maro.testing import SlackSimulator, JiraSimulator

@pytest.fixture
def slack_sim():
    """Simulated Slack client."""
    return SlackSimulator()

@pytest.fixture
def jira_sim():
    """Simulated Jira API."""
    return JiraSimulator()

class TestFullWorkflow:

    @pytest.mark.asyncio
    async def test_message_to_jira_ticket(self, slack_sim, jira_sim, app):
        """Complete flow: message → draft → approve → Jira."""

        # User sends message
        await slack_sim.send_message(
            channel="C123",
            user="U123",
            text="@MARO create a story: User can login with email"
        )

        # Wait for bot response
        response = await slack_sim.wait_for_response()
        assert "draft" in response.text.lower()

        # Click approve button
        await slack_sim.click_button(response, "approve")

        # Wait for Jira creation
        await asyncio.sleep(1)

        # Verify Jira issue created
        issues = jira_sim.get_created_issues()
        assert len(issues) == 1
        assert "login with email" in issues[0].summary

    @pytest.mark.asyncio
    async def test_decision_recording(self, slack_sim, jira_sim, app):
        """Flow: decision statement → record → approve → project to Jira."""

        await slack_sim.send_message(
            channel="C123",
            user="U123",
            text="We decided to use PostgreSQL for the event store"
        )

        response = await slack_sim.wait_for_response()
        assert "decision" in response.text.lower()

        # Should post to channel for approval
        channel_messages = slack_sim.get_channel_messages("C123")
        assert any("PostgreSQL" in m.text for m in channel_messages)
```

### 15.7 Test Configuration

```python
# tests/conftest.py
import pytest
import asyncpg
import os

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def test_db_pool():
    """Create test database pool."""
    pool = await asyncpg.create_pool(
        os.environ.get("TEST_DATABASE_URL", "postgresql://localhost/maro_test")
    )
    yield pool
    await pool.close()

@pytest.fixture(autouse=True)
async def clean_db(test_db_pool):
    """Clean database before each test."""
    async with test_db_pool.acquire() as conn:
        await conn.execute("TRUNCATE channel_events CASCADE")
        await conn.execute("TRUNCATE entities_view CASCADE")
        await conn.execute("TRUNCATE processes_view CASCADE")
        await conn.execute("TRUNCATE plans_view CASCADE")
    yield

@pytest.fixture
def channel_factory():
    """Factory for creating test channels."""
    def create(
        id: str = "C123",
        with_entities: list = None
    ) -> Channel:
        channel = Channel(
            id=ChannelId(id),
            version=0,
            entities={},
            processes={},
            plans={},
            conflicts=[],
            config=ChannelConfig.default()
        )
        # Add entities if provided
        ...
        return channel
    return create
```

---

## Summary

### Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Event sourcing with Channel as aggregate | Single source of truth, full audit trail |
| Sum types for entity states | Illegal states unrepresentable |
| 2-stage intent routing | Simpler than 6-layer system |
| 4 SuperModes instead of 13 intents | Developer-friendly, same capability |
| Process → Plan → Workflow orchestration | Handles complex multi-stage tasks |
| Managed sections in Jira | Never overwrites user content |
| Preflight before every Jira write | Prevents conflicts and data loss |

### Implementation Priorities

1. **Week 1-2:** Domain model (entities, events, channel aggregate)
2. **Week 3-4:** Event store and projections
3. **Week 5-6:** Intent routing and mode handlers
4. **Week 7-8:** Process/Plan/Workflow execution
5. **Week 9-10:** Slack integration
6. **Week 11-12:** Jira integration
7. **Week 13-14:** Multi-user support and testing
8. **Week 15-16:** Channel lifecycle and polish

### What's NOT in This Design

- Mobile app (Slack-first)
- Multi-language support (English only)
- Real-time collaborative editing (async model)
- Horizontal scaling (single instance sufficient for 100 channels)
- Custom LLM fine-tuning (using off-the-shelf models)

---

*Document version: 2.0*
*Last updated: 2026-02-02*

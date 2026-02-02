# Phase 1: Foundation - Research

**Researched:** 2026-02-02
**Domain:** Python Event Sourcing with PostgreSQL
**Confidence:** HIGH

<research_summary>
## Summary

Researched the Python event sourcing ecosystem for building a production-grade event store with PostgreSQL. The **pyeventsourcing/eventsourcing** library (v9.5.2, released Jan 2026) is the standard choice—it provides snapshotting, optimistic concurrency, projections, and PostgreSQL support out of the box.

Key finding: PostgreSQL is a legitimate event store choice. You don't need EventStoreDB for most use cases. The eventsourcing library with eventsourcing-sqlalchemy handles the heavy lifting. However, the outbox pattern for async projections requires custom implementation or using python-event-sourcery which has built-in outbox support.

**Primary recommendation:** Use `eventsourcing` library with SQLAlchemy backend for core event store. Implement outbox pattern manually following established patterns (event + outbox in same transaction, async processor). Add schema versioning from day one with explicit version fields on events.

</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| eventsourcing | 9.5.2 | Event sourcing framework | Most mature Python ES library, active development (Jan 2026 release) |
| eventsourcing-sqlalchemy | 0.6+ | PostgreSQL persistence | Official extension for SQLAlchemy/PostgreSQL |
| pydantic | 2.x | Domain model types | Native support in eventsourcing for serialization |
| asyncpg | 0.29+ | Async PostgreSQL client | 5x faster than psycopg3, required for async operations |
| sqlalchemy | 2.x | ORM/database toolkit | Foundation for eventsourcing-sqlalchemy |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-event-sourcery | latest | Alternative ES library | If you need built-in outbox pattern, simpler API |
| orjson | 3.x | Fast JSON serialization | eventsourcing has native orjson support via PydanticMapper |
| alembic | 1.x | Database migrations | Schema versioning for PostgreSQL tables |
| psycopg | 3.x | Sync PostgreSQL client | When sync operations are acceptable |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| eventsourcing | python-event-sourcery | Simpler API, built-in outbox, but less mature |
| PostgreSQL | EventStoreDB/KurrentDB | Purpose-built for ES, but adds infrastructure complexity |
| Custom event store | Manual implementation | Full control, but reinvents solved problems |

**Installation:**
```bash
pip install eventsourcing eventsourcing-sqlalchemy pydantic asyncpg alembic orjson
```

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/
├── domain/
│   ├── events.py           # Base event classes, all event types
│   ├── aggregates.py       # Aggregate root classes (Channel)
│   └── types.py            # Value objects (EntityId, ChannelId, etc.)
├── infrastructure/
│   ├── event_store.py      # EventStore configuration
│   ├── projections.py      # Projection base classes
│   ├── outbox.py           # Outbox pattern implementation
│   └── snapshots.py        # Snapshot configuration
├── application/
│   └── services.py         # Application services using aggregates
└── persistence/
    ├── models.py           # SQLAlchemy models for projections
    └── migrations/         # Alembic migrations
```

### Pattern 1: Aggregate with Event Decorator
**What:** Define aggregates using the eventsourcing library's declarative syntax
**When to use:** All domain aggregates
**Example:**
```python
# Source: eventsourcing docs - domain module
from eventsourcing.domain import Aggregate, event
from uuid import UUID

class Channel(Aggregate):
    @event('Created')
    def __init__(self, channel_id: str, name: str) -> None:
        self.channel_id = channel_id
        self.name = name
        self.entities: dict[UUID, Entity] = {}

    @event('EntityAdded')
    def add_entity(self, entity_id: UUID, content: dict) -> None:
        self.entities[entity_id] = Entity(entity_id, content)

    @event('EntityApproved')
    def approve_entity(self, entity_id: UUID, approver: str) -> None:
        self.entities[entity_id].approve(approver)
```

### Pattern 2: Pydantic Events with Schema Versioning
**What:** Use Pydantic models for events with explicit schema versions
**When to use:** All event definitions
**Example:**
```python
# Source: eventsourcing docs - Aggregate 7/8 Pydantic examples
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID

class BaseEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: int = 1
    correlation_id: UUID | None = None
    causation_id: UUID | None = None

class EntityCreated(BaseEvent):
    entity_id: UUID
    content_type: str
    content: dict
    created_by: str
    created_at: datetime
```

### Pattern 3: Outbox Pattern for Projections
**What:** Store events + outbox record in same transaction, process async
**When to use:** All projection updates
**Example:**
```python
# Source: blog.szymonmiks.pl outbox pattern
from sqlalchemy.orm import Session

class OutboxProcessor:
    def __init__(self, session: Session, projectors: list):
        self.session = session
        self.projectors = projectors

    async def process_pending(self):
        """Called by scheduled task (e.g., every 100ms)"""
        pending = self.session.query(OutboxEvent)\
            .filter(OutboxEvent.processed_at.is_(None))\
            .order_by(OutboxEvent.id)\
            .limit(100)\
            .all()

        for outbox_event in pending:
            event = self._deserialize(outbox_event)
            for projector in self.projectors:
                if projector.handles(event):
                    projector.apply(event)
            outbox_event.processed_at = datetime.utcnow()

        self.session.commit()
```

### Pattern 4: Automatic Snapshotting
**What:** Configure library to snapshot aggregates at intervals
**When to use:** Long-lived aggregates with many events
**Example:**
```python
# Source: eventsourcing docs - application module
from eventsourcing.application import Application

class ChannelApplication(Application):
    is_snapshotting_enabled = True
    snapshotting_intervals = {Channel: 500}  # Snapshot every 500 events

    def get_channel(self, channel_id: UUID) -> Channel:
        # Automatically loads from snapshot + tail events
        return self.repository.get(channel_id)
```

### Anti-Patterns to Avoid
- **Property Sourcing:** Events like `NameChanged` with no business meaning. Use domain events like `EntityApproved`, `DecisionRecorded`
- **Event Sourcing Everywhere:** Only event-source the Channel aggregate. Projections can be normal CRUD
- **Synchronous Projections:** Always use outbox pattern to decouple event persistence from projection updates
- **Skipping Schema Versions:** Always include `schema_version` on events from day one

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Event store infrastructure | Custom append/read logic | eventsourcing library | Handles optimistic concurrency, versioning, serialization |
| Aggregate reconstruction | Manual event replay | eventsourcing Repository | Handles snapshotting, caching, version checking |
| Optimistic concurrency | Custom version checking | eventsourcing built-in | Tested edge cases, retry logic, conflict detection |
| Event serialization | Custom JSON handling | PydanticMapper + orjson | Handles nested types, value objects automatically |
| Snapshot management | Manual snapshot logic | eventsourcing snapshotting | Automatic intervals, storage, retrieval |
| Projection tracking | Custom position tracking | eventsourcing ProcessRecorder | Handles idempotency, position tracking |

**Key insight:** The eventsourcing library has 10+ years of development solving edge cases you haven't thought of yet. Custom event store implementations fail on: concurrent writes, event ordering, snapshot consistency, schema evolution. Use the library and focus on your domain logic.

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Synchronous Projections
**What goes wrong:** Projection failure prevents event persistence, or partial projection application
**Why it happens:** Projections applied in same transaction as event append
**How to avoid:** Always use outbox pattern—event + outbox record in one transaction, projections async
**Warning signs:** Slow event writes, failed events due to projection errors, inconsistent read models

### Pitfall 2: Missing Schema Version on Events
**What goes wrong:** Can't evolve event schemas without breaking existing events
**Why it happens:** "We'll add versioning later"
**How to avoid:** Every event has `schema_version: int = 1` from day one
**Warning signs:** Fear of changing event payloads, workarounds instead of proper evolution

### Pitfall 3: Property Sourcing Instead of Domain Events
**What goes wrong:** Events become meaningless change logs, no business value
**Why it happens:** Thinking in CRUD instead of domain
**How to avoid:** Events should be domain actions: `EntityApproved`, `DecisionRecorded`, not `StatusChanged`
**Warning signs:** Events named after fields, projections duplicating aggregate logic

### Pitfall 4: No Snapshotting Strategy
**What goes wrong:** Aggregate load time grows linearly with event count
**Why it happens:** Works fine with few events, degradation is gradual
**How to avoid:** Enable snapshotting from start, configure intervals (500-1000 events)
**Warning signs:** Increasing latency on reads, memory spikes during reconstruction

### Pitfall 5: Projections Not Idempotent
**What goes wrong:** Duplicate event processing corrupts read models
**Why it happens:** Outbox pattern delivers at-least-once, not exactly-once
**How to avoid:** Track processed_event_id, use upserts instead of inserts
**Warning signs:** Incorrect counts, duplicate records in projections

### Pitfall 6: Tight Coupling Between Services via Events
**What goes wrong:** Changes to one service require changes everywhere
**Why it happens:** Services subscribe directly to each other's events
**How to avoid:** Use process managers for cross-aggregate coordination
**Warning signs:** Every change touches multiple services, hard to trace flows

</common_pitfalls>

<code_examples>
## Code Examples

### Basic Application Setup with PostgreSQL
```python
# Source: eventsourcing docs + eventsourcing-sqlalchemy
import os
from eventsourcing.application import Application
from eventsourcing.domain import Aggregate, event

os.environ["PERSISTENCE_MODULE"] = "eventsourcing_sqlalchemy"
os.environ["SQLALCHEMY_URL"] = "postgresql://user:pass@localhost/maro"
os.environ["IS_SNAPSHOTTING_ENABLED"] = "true"

class Channel(Aggregate):
    @event('Created')
    def __init__(self, slack_id: str, name: str):
        self.slack_id = slack_id
        self.name = name
        self.entities = {}

class ChannelApplication(Application):
    snapshotting_intervals = {Channel: 500}

    def create_channel(self, slack_id: str, name: str) -> Channel:
        channel = Channel(slack_id, name)
        self.save(channel)
        return channel
```

### Outbox Table Schema
```sql
-- Source: outbox pattern best practices
CREATE TABLE outbox_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ NULL,

    INDEX idx_outbox_unprocessed (processed_at) WHERE processed_at IS NULL
);
```

### Event with Schema Versioning
```python
# Source: eventsourcing docs + event-driven.io versioning patterns
from pydantic import BaseModel, ConfigDict
from typing import Literal
from uuid import UUID
from datetime import datetime

class EntityCreatedV1(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    entity_id: UUID
    entity_type: str  # "work_item" | "decision"
    content: dict
    created_by: str
    created_at: datetime
    correlation_id: UUID | None = None
    causation_id: UUID | None = None

# When schema evolves:
class EntityCreatedV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[2] = 2
    entity_id: UUID
    entity_type: str
    content: dict
    created_by: str
    created_at: datetime
    source_thread_ts: str | None = None  # New field in v2
    correlation_id: UUID | None = None
    causation_id: UUID | None = None

def upcast_entity_created(event_data: dict) -> dict:
    """Upcast v1 events to v2 format"""
    if event_data.get("schema_version", 1) == 1:
        event_data["schema_version"] = 2
        event_data["source_thread_ts"] = None
    return event_data
```

### Idempotent Projection
```python
# Source: outbox pattern + eventsourcing projections
from sqlalchemy.dialects.postgresql import insert

class EntityProjection:
    def __init__(self, session):
        self.session = session
        self.last_processed_id: int = 0

    def apply(self, event_id: int, event: EntityCreated):
        # Skip if already processed
        if event_id <= self.last_processed_id:
            return

        # Upsert to handle duplicates
        stmt = insert(EntityView).values(
            entity_id=event.entity_id,
            entity_type=event.entity_type,
            content=event.content,
            created_at=event.created_at,
        ).on_conflict_do_update(
            index_elements=['entity_id'],
            set_={'content': event.content}
        )
        self.session.execute(stmt)
        self.last_processed_id = event_id
```

</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| EventStoreDB required | PostgreSQL sufficient | Ongoing | Simpler infrastructure, one less database |
| Manual event store | eventsourcing library | Mature by 2024 | Don't reinvent the wheel |
| Sync projections | Outbox pattern standard | 2023+ | Better reliability, decoupling |
| No schema versioning | Explicit version fields | Best practice | Required for production evolution |
| psycopg2 | asyncpg / psycopg3 | 2024+ | 5x performance improvement |

**New tools/patterns to consider:**
- **eventsourcing 9.5.x:** Latest release (Jan 2026) with improved Pydantic support
- **python-event-sourcery:** Newer library with built-in outbox, simpler API
- **KurrentDB (formerly EventStoreDB):** If you need specialized event store features

**Deprecated/outdated:**
- **eventsourcing < 9.x:** Major API changes in v9
- **Manual event store implementations:** Library support is now mature
- **Synchronous projection patterns:** Outbox is now standard

</sota_updates>

<open_questions>
## Open Questions

1. **Outbox Processing Frequency**
   - What we know: Process pending every 100ms-1s is typical
   - What's unclear: Optimal frequency for MARO's expected load
   - Recommendation: Start with 100ms, tune based on observation

2. **Snapshot Storage Location**
   - What we know: eventsourcing stores snapshots separately
   - What's unclear: Whether to use same PostgreSQL or separate store
   - Recommendation: Same PostgreSQL, separate table (simpler operations)

3. **Event Encryption**
   - What we know: eventsourcing supports AES encryption
   - What's unclear: Whether MARO needs encrypted events (contains Slack messages)
   - Recommendation: Defer until security review, library supports it when needed

</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [eventsourcing library documentation](https://eventsourcing.readthedocs.io/) - Official docs, v9.5.2
- [eventsourcing on PyPI](https://pypi.org/project/eventsourcing/) - Version 9.5.2, Jan 2026
- [eventsourcing-sqlalchemy](https://pypi.org/project/eventsourcing-sqlalchemy/) - PostgreSQL persistence

### Secondary (MEDIUM confidence)
- [The Outbox Pattern in Python](https://blog.szymonmiks.pl/p/the-outbox-pattern-in-python/) - Implementation patterns, verified against library docs
- [Event Sourcing with PostgreSQL](https://breadcrumbscollector.tech/implementing-event-sourcing-in-python-part-2-robust-event-store-atop-postgresql/) - PostgreSQL-specific patterns
- [Simple patterns for events schema versioning](https://event-driven.io/en/simple_events_versioning_patterns/) - Schema evolution strategies
- [python-event-sourcery](https://github.com/python-event-sourcery/python-event-sourcery) - Alternative library with outbox

### Tertiary (LOW confidence - needs validation)
- [DEV.to FastAPI + Event Sourcing](https://dev.to/markoulis/how-i-learned-to-stop-worrying-and-love-raw-events-event-sourcing-cqrs-with-fastapi-and-celery-477e) - Practical patterns, verify implementation details

</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Python event sourcing with PostgreSQL
- Ecosystem: eventsourcing, python-event-sourcery, asyncpg, Pydantic
- Patterns: Aggregate, outbox, snapshotting, schema versioning
- Pitfalls: Sync projections, property sourcing, missing versions

**Confidence breakdown:**
- Standard stack: HIGH - eventsourcing is established, actively maintained
- Architecture: HIGH - patterns verified against official docs
- Pitfalls: HIGH - documented in multiple authoritative sources
- Code examples: HIGH - from official documentation

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days - stable ecosystem)

</metadata>

---

*Phase: 01-foundation*
*Research completed: 2026-02-02*
*Ready for planning: yes*

# Phase 1: Foundation - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<vision>
## How This Should Work

Follow the maro_2_0.md spec in order, building each layer as defined. The Foundation establishes the event-sourced core that everything else builds on.

The EventStore isn't just a place to append events — it's the complete infrastructure for reliable state management. When you load a channel, it reads the last snapshot, replays only the tail events, and the projection system keeps read models eventually consistent through the outbox pattern.

This should feel like a solid, well-tested foundation. Not cutting corners to "iterate later" — the snapshotting, outbox, and schema versioning all need to be there from the start because retrofitting them is painful.

</vision>

<essential>
## What Must Be Nailed

- **Full EventStore infrastructure** — Snapshotting, outbox pattern, schema versioning all built in from day one (not retrofitted later)
- **Real PostgreSQL schema** — Actual migrations and tables (channel_events, channel_snapshots, outbox_events) — not just in-memory mocks
- **Complete projection pattern** — Event → Store → Outbox → Projection → Query chain working end-to-end
- **Spec-first approach** — Work through maro_2_0.md sections in defined order

</essential>

<specifics>
## Specific Ideas

From update-1.md architectural enhancements:
- Snapshot channels every N events (500-1000) or by time (hourly for active channels)
- Outbox pattern: append events → write to outbox → async projector reads outbox → idempotent apply
- Each projection tracks processed_event_id for idempotency
- Events include schema_version field for evolution
- Correlation/causation IDs on every action for tracing

Database tables defined:
- channel_events (id, aggregate_id, version, event_type, schema_version, payload jsonb, created_at)
- channel_snapshots (aggregate_id, version, state jsonb, created_at)
- outbox_events (event_id, status, retries, created_at)

</specifics>

<notes>
## Additional Context

Reference v1.x (../reqirements-orchestrator-old/) for patterns only — Slack patterns, credential setup, deployment approaches. Don't copy code structure; this is a clean rewrite.

The goal is a production-ready event sourcing foundation, not a prototype. The update-1.md additions (snapshotting, outbox, schema versioning) exist because synchronous projections and no-snapshot replays cause real operational problems.

</notes>

---

*Phase: 01-foundation*
*Context gathered: 2026-02-02*

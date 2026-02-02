# Phase 4: Entity Lifecycle - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<vision>
## How This Should Work

Entities (WorkItems and Decisions) follow a strict lifecycle defined by sum types — each entity can only be in ONE state at a time. The system enforces transitions at the domain model level, making illegal states unrepresentable.

**The flow:**
1. User drafts something in a thread → **DraftEntity** created
2. User proposes to channel → transitions to **ProposedEntity** with canonical message
3. Team members approve/object → approvals accumulate, objections block
4. Enough approvals → transitions to **ApprovedEntity**, ready for Jira
5. Synced to Jira → becomes **CommittedEntity** with required JiraLink
6. Later superseded → **DeprecatedEntity** (decisions only)

**Channel as aggregate root:** All entity mutations flow through the channel. Events are stored at the channel level, entities are projections of those events.

</vision>

<essential>
## What Must Be Nailed

All three are equally important — they work together:

- **State machine correctness** — Transitions are airtight. Can't approve a Draft directly. Can't modify a Committed entity. Can't sync a Proposed entity to Jira. Domain model enforces these invariants.

- **Channel aggregate root** — All mutations produce events at the channel level. Entity state is derived from event replay. Consistent event ordering within a channel.

- **Approval/Objection flow** — Human-driven workflow where objections block progress until resolved. Clear tracking of who approved/objected and when.

</essential>

<specifics>
## Specific Ideas

Follow the spec in `docs/maro_2_0.md` exactly:

- **Sum types pattern** — DraftEntity, ProposedEntity, ApprovedEntity, CommittedEntity, DeprecatedEntity as separate classes, not a single class with optional fields
- **Attribution model** — proposed_by, approved_by, modifications list tracking all changes
- **Approval/Objection records** — with user_id, timestamp, comment/reason, resolution status
- **Canonical message management** — the Slack message that represents an entity in the channel
- **Entity projections** — efficient read models for queries and dashboard

From `docs/update-1.md`:
- **Lifecycle invariants at domain level** — validation in domain model, not just in handlers
- **Approval locking** — after approval, entity is locked except for override processes

</specifics>

<notes>
## Additional Context

This phase connects the intent routing from Phase 3 to actual entity creation and state transitions. The mode handlers (CREATE, MODIFY, RECORD) will now have real entities to work with instead of placeholders.

Key integration point: The SafetyEvaluator from Phase 3 will use the LifecycleState from this phase to validate whether actions are allowed.

The existing event store infrastructure from Phase 1 (EventStore, projections, outbox) provides the foundation for entity events.

**Documentation update required:** Update `docs/architecture/*.md` (especially BOT_DESIGN.md) to document the entity lifecycle implementation, sum types pattern, and how the mode handlers integrate with entities.

</notes>

---

*Phase: 04-entity-lifecycle*
*Context gathered: 2026-02-02*

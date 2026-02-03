# Phase 5: Process Orchestration - Context

**Gathered:** 2026-02-02 (Updated)
**Status:** Ready for planning

<vision>
## How This Should Work

**Updated model:** Task-based orchestration instead of linear ProcessExecutor.

The bot converts conversations into Jira artifacts through flexible, entity-centric workflows:

1. User starts a conversation (mentions work item, asks for architecture review, etc.)
2. Orchestrator detects intent, creates a Task with a goal
3. Task gathers context through questions (flexible, not rigid stages)
4. Entities emerge during conversation (decisions, work items) — captured in real-time
5. User can revisit earlier topics, switch focus between tasks
6. When ready, user approves → entities go through lifecycle → sync to Jira

**Key scenarios:**
- **Simple:** "Create a login story" → single Task, single Entity
- **Parallel:** "Create stories for each epic" → parent Task fans out to children
- **Emergent:** Architecture discussion → decisions captured as they're mentioned
- **Multi-user:** Alice starts, Bob contributes, Carol approves

</vision>

<essential>
## What Must Be Nailed

All equally important — they enable the flexible model:

- **Orchestrator routing** — Routes every message to the right Task (or creates new). Detects task-switch intent ("let's go back to..."). Single entry point for all conversation handling.

- **Task lifecycle** — Tasks gather context toward goals, spawn children for fan-out, track contributors, complete when requirements met. Not rigid stages — flexible context accumulation.

- **Entity emergence** — Detect when conversation contains decisions/work items. Capture during discussion, not just at end. Confirm with user to avoid false positives.

- **Integration with Phase 1-4** — Task events in EventStore, routing through existing PreGates, entities flow through ChannelAggregate, LLM from Phase 3.

</essential>

<specifics>
## Specific Ideas

**New components (from 05-MODEL-PROPOSAL.md):**
- `Task` — Unit of work with goal, context, status, parent/child hierarchy
- `Workspace` — Channel/thread state, tracks active tasks and focus
- `Orchestrator` — Routes input, manages task lifecycle, detects intent
- `FlowTemplate` — Guides (not enforces) what context to gather

**Flow templates to implement:**
- `create_work_item` — Single item creation
- `create_decision` — Capture architectural decision
- `architecture_review` — Multi-entity discussion with fan-out
- `batch_create` — Parallel item creation ("for each X")
- `review` — Review and refine existing entities

**Phase 1-4 updates needed:**
- Phase 1: Add Task events (TaskCreated, TaskCompleted, TaskCancelled, etc.)
- Phase 3: Update PreGates to route to Orchestrator (Gate 3 check for active workspace)
- Keep existing entity lifecycle (Phase 4) — Tasks create entities through ChannelAggregate

</specifics>

<notes>
## Additional Context

**Evolution from spec:**
The original maro_2_0.md Part 7 defined linear ProcessExecutor with fixed stages. After discussion, we evolved to Task-based model because:
- Real conversations are non-linear
- "Create stories for each epic" needs parallelism
- Decisions emerge during discussion, not at end
- Multi-user collaboration is natural in Slack

**Documentation updates required:**
- `docs/architecture/BOT_DESIGN.md` — Add Task-based orchestration section
- Potentially new `docs/architecture/ORCHESTRATION.md` — Detailed orchestration design

**Connection points:**
- Phase 3 PreGates → Orchestrator (instead of ProcessExecutor)
- Phase 4 ChannelAggregate → Tasks create entities through it
- Phase 6 Jira → Plan execution still applies for bulk sync

</notes>

---

*Phase: 05-process-orchestration*
*Context updated: 2026-02-02*
*Model: Task-based orchestration (evolved from spec's ProcessExecutor)*

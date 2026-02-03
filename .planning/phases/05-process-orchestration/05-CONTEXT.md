# Phase 5: Process Orchestration - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<vision>
## How This Should Work

Follow the spec (maro_2_0.md Part 7) exactly. Processes are multi-stage workflows that guide users through complex tasks like architecture reviews or work item creation.

**The flow:**
1. User triggers a process (e.g., starts architecture review)
2. ProcessExecutor runs through stages (discovery → analysis → decisions → planning)
3. Each stage asks questions, gathers info, iterates until requirements met
4. Stage outputs accumulate into process.outputs
5. When process completes, PlanGenerator creates executable Plan
6. Plan items execute sequentially (create decisions, create work items, sync to Jira)

**Two process types from spec:**
- `architecture_review` - 4 stages: discovery, analysis, decisions, planning
- `work_item_creation` - 3 stages: understand, refine, validate

</vision>

<essential>
## What Must Be Nailed

All three are equally important — they form the complete flow:

- **Stage progression logic** — Moving through stages, tracking iteration count, handling max_iterations, stage skipping. StageStatus and ProcessStatus state machines.

- **LLM question generation** — Context-aware questions based on stage definition and gathered info. Follow-up questions when requirements not yet met.

- **Process → Plan flow** — Converting process outputs into executable Plans with PlanItems. Plan execution with status tracking.

</essential>

<specifics>
## Specific Ideas

Follow spec Part 7 as-is:

- **ProcessDefinition** and **StageDefinition** dataclasses exactly as specified
- **Process** and **StageState** for runtime state
- **ProcessExecutor** with `start()` and `handle_input()` methods
- **Plan**, **PlanItem**, **PlanGenerator** for execution
- **ProcessProjection** for read model
- Two predefined processes: `ARCHITECTURE_REVIEW_PROCESS` and `WORK_ITEM_CREATION_PROCESS`

No external statechart library needed — the spec defines a simple, purpose-built state machine.

</specifics>

<notes>
## Additional Context

This phase connects to:
- **Phase 3 (Intent)** — PreGates Gate 3 routes to process_handler when thread has active process
- **Phase 4 (Entities)** — Process outputs become entity content (decisions, work items)
- **Phase 6 (Jira)** — Plan items include sync_jira actions

The PreGates already check for active processes in threads. ProcessExecutor will be invoked when that gate matches.

**Documentation update required:** Update `docs/architecture/*.md` (especially BOT_DESIGN.md) to document the process orchestration implementation, stage progression, and Plan execution flow.

</notes>

---

*Phase: 05-process-orchestration*
*Context gathered: 2026-02-02*

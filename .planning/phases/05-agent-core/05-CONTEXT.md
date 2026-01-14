# Phase 5: Agent Core - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

The agent is a "PM-machine" - not a chatty tool-caller, but a deterministic pipeline: **extract → validate → decide → (optionally) call tools → finish or wait for human**.

Two nested loops:
1. **ReAct loop** (LLM ↔ tools): Model decides what tools to call, repeats until data acquired or stop condition. This is the *mechanism*.
2. **Product loop** (draft ↔ validation ↔ decision): The workflow that wraps ReAct. Draft is the center of gravity. This is the *product logic*.

Key philosophy: **ReAct is subordinate to the workflow, not the other way around.** The draft/validation/decision cycle is what makes this a PM tool instead of a generic agent.

When a message arrives in a bound thread:
- @mention triggers the graph immediately
- Regular messages batch with debounce, then trigger
- If a run is already in progress, new messages queue and wait (per-thread serialization from Phase 4)

The graph can pause (interrupt), persist state via checkpointer, and resume when the human responds. State machine allows backwards transitions - user can say "wait, change the title" after seeing PREVIEW and we regress to COLLECTING.

</vision>

<essential>
## What Must Be Nailed

Three things are equally critical and inseparable:

1. **Loop protection** - No infinite tool loops ever
   - max_steps=10 per run
   - Stop condition if state unchanged after tool call
   - Logging of "why model called tool again" for debugging

2. **Interrupt/resume flow** - Clean HIL gates
   - Graph pauses at ASK/PREVIEW decision points
   - State persists through PostgresSaver checkpointer
   - Resume with `Command(resume=...)` when human responds
   - Single gentle reminder if no response (configurable timing)

3. **Patch-style draft updates** - Incremental, not rewrites
   - Extraction adds/modifies specific fields
   - Evidence links trace back to source messages
   - No "drift and chaos" from full rewrites

</essential>

<specifics>
## Specific Ideas

**Draft Structure:**
```
epic_id, title, problem, proposed_solution,
acceptance_criteria[], constraints[] (key/value/status),
open_questions[], dependencies[], risks[],
evidence_links[] (Slack permalinks)
```

Minimum viable draft for PREVIEW: **title + problem + 1 AC**

**Graph Architecture:**
- Custom graph (not prebuilt `create_react_agent`)
- Hybrid approach: custom graph structure, reuse Phase 3 LLM adapters for actual calls
- Nodes: assistant (LLM step), tools (executor), route/condition, guards

**State Machine Phases:**
`COLLECTING → VALIDATING → AWAITING_USER → READY_TO_CREATE → CREATED`
- Backwards transitions allowed (can regress to COLLECTING from PREVIEW)
- state_version/last_updated_at for race detection

**Node Boundaries:**
- **Extraction**: Single node updates all draft fields at once (patch-style)
- **Validation**: LLM-first with rule-based fallback. Outputs detailed report: `missing_fields[], conflicts[], suggestions[]`
- **Decision**: Three outcomes (ASK / PREVIEW / EXECUTE), prioritizes most impactful issues first. Smart batching for questions (immediate if urgent, else batch related).

**Decision Node Outcomes (Phase 5):**
- ASK: Post questions to Slack, interrupt, wait for response
- PREVIEW: Show draft as Slack blocks, request approval
- EXECUTE: Deferred to Phase 7 (update state to READY_TO_CREATE only)

**Observability:**
- Both modes: structured JSON logs for prod + verbose debug traces for dev
- Track: which node executed, what changed in state, tool call count, why decision chose ASK vs PREVIEW

**DoD Scenarios:**
1. Enough data → PREVIEW → approval → state becomes READY_TO_CREATE
2. Not enough data → ASK → interrupt → resume → PREVIEW (single gentle nudge if no response)
3. Constraint conflict → Hybrid resolution: in-graph for draft conflicts, Phase 4 contradiction detector for cross-thread KG conflicts

</specifics>

<notes>
## Additional Context

**Integration with Phase 4:**
- Handlers from 04-02 trigger the graph
- Session lock from 04-03 ensures one active run per thread
- New messages during run queue and wait (no merging into running graph)
- Uses Zep (04-05) for context, Knowledge Graph (04-06) for constraints

**What's NOT in Phase 5:**
- Actual Jira creation (Phase 7)
- Persona switching (Phase 9)
- Tools beyond extraction/validation helpers

**Key anti-pattern to avoid:**
ReAct loop that talks forever. The product loop (draft/validation/decision) must be in control. Agent is a "PM-machine" that drives toward ticket creation, not a chatbot.

</notes>

---

*Phase: 05-agent-core*
*Context gathered: 2026-01-14*

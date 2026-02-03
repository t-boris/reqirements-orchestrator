# Phase 5: Process Orchestration - Research

**Researched:** 2026-02-02
**Domain:** Python state machines and workflow orchestration for conversational AI
**Confidence:** HIGH

<research_summary>
## Summary

Researched Python state machine libraries and workflow engines to determine whether to use an external library vs the custom ProcessExecutor defined in maro_2_0.md spec.

**Key finding:** The spec's ProcessExecutor is a **simple linear stage machine** (not a complex statechart). External libraries like `transitions` or `python-statemachine` are designed for arbitrary state graphs with complex transitions, guards, and concurrent states. Our use case is simpler: sequential stages with iteration counts and output accumulation.

**Primary recommendation:** Follow the spec's custom ProcessExecutor design. It's simpler, purpose-built for our needs, and avoids the overhead of learning/integrating a general-purpose state machine library for what is essentially a linear workflow with counters.

</research_summary>

<standard_stack>
## Standard Stack

### Recommended: Custom Implementation (per spec)

| Component | Purpose | Why Custom |
|-----------|---------|------------|
| ProcessDefinition | Define stage sequences | Simple dataclass, no library needed |
| ProcessExecutor | Execute stages | Linear progression, not complex state graph |
| StageState | Track iteration/outputs | Plain Python dict/dataclass |
| Plan/PlanItem | Execute outputs | Sequential execution |

### Alternatives Considered

| Library | Stars | Async | Why NOT to use |
|---------|-------|-------|----------------|
| [python-statemachine](https://github.com/fgmacedo/python-statemachine) | 1.2k | Yes | Overkill for linear stages; designed for arbitrary transitions |
| [transitions](https://github.com/pytransitions/transitions) | 5.5k | Yes | Same - too flexible for our simple needs |
| [llmstatemachine](https://github.com/robocorp/llmstatemachine) | ~100 | No | Interesting for LLM agents, but doesn't fit our stage-based model |
| LiteFlow | ~600 | Yes | Designed for distributed workflows, not conversational processes |

**Why libraries don't fit:**

Our ProcessExecutor has a **linear stage model**:
```
Stage 1 → Stage 2 → Stage 3 → Stage 4 → Complete
   ↓         ↓         ↓         ↓
 iterate  iterate   iterate   iterate
 (max N)  (max N)   (max N)   (max N)
```

Libraries like `transitions` are designed for **arbitrary state graphs**:
```
     ┌──→ State B ──→ State D
State A ─┤              ↑
     └──→ State C ──────┘
```

The spec's ProcessExecutor is 100 lines of straightforward Python. A library would add:
- Learning curve
- Configuration complexity
- Dependency management
- Potential async compatibility issues

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended: Spec's ProcessExecutor Pattern

```python
# Process = definition + runtime state
Process:
  definition: ProcessDefinition  # Static stage sequence
  status: ProcessStatus          # PENDING/RUNNING/PAUSED/COMPLETED/CANCELLED
  current_stage_index: int       # Which stage we're on
  stage_states: list[StageState] # Per-stage iteration tracking
  outputs: dict[str, Any]        # Accumulated outputs

# ProcessExecutor handles the flow
ProcessExecutor:
  start(process) → events        # Initialize, ask first question
  handle_input(process, msg) → events  # Process user reply, advance stages
```

### Project Structure

```
src/
├── process/
│   ├── definitions.py     # ProcessDefinition, StageDefinition, predefined processes
│   ├── models.py          # Process, StageState, ProcessStatus, StageStatus
│   ├── executor.py        # ProcessExecutor - core orchestration logic
│   ├── plan.py            # Plan, PlanItem, PlanGenerator, PlanExecutor
│   ├── projection.py      # ProcessProjection for read model
│   └── __init__.py
```

### Pattern: Stage Iteration with Output Accumulation

```python
async def handle_input(self, process: Process, message: SlackMessage) -> list[DomainEvent]:
    stage_def = process.definition.stages[process.current_stage_index]
    stage_state = process.stage_states[process.current_stage_index]

    # Extract info from user message via LLM
    extracted = await self._extract_stage_info(message.text, stage_def, stage_state.gathered_info)
    stage_state.gathered_info.update(extracted)
    stage_state.iteration += 1

    # Check if requirements met
    if self._stage_complete(stage_def, stage_state):
        # Complete stage, move to next (or finish process)
        ...
    elif stage_state.iteration >= stage_def.max_iterations:
        # Max iterations reached - skip or require more input
        ...
    else:
        # Ask follow-up question
        ...
```

### Anti-Patterns to Avoid

- **Don't use a graph-based state machine** for this linear workflow
- **Don't store state in the executor** - use Process dataclass (event sourcing compatible)
- **Don't block on LLM calls** - use async throughout
- **Don't skip validation** - check stage requirements are met before advancing

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Use Instead | Why |
|---------|-------------|-----|
| LLM question generation | Existing LLM client from Phase 3 | Already have `src/llm/client.py` |
| Stage requirement validation | Simple Python `all()` check | Don't overcomplicate |
| Event sourcing | Existing EventStore from Phase 1 | Reuse `src/infrastructure/event_store.py` |
| Slack integration | Existing SlackClient from Phase 2 | Reuse `src/slack/client.py` |

**Key insight:** The spec's ProcessExecutor isn't "hand-rolling a state machine" - it's implementing a simple linear workflow. True state machines (with arbitrary transitions, guards, hierarchies) should use libraries, but our stage-based model is simpler.

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Over-Engineering with State Machine Libraries
**What goes wrong:** Importing `transitions` or `python-statemachine` for a linear workflow
**Why it happens:** "State machine" in the name leads to reaching for libraries
**How to avoid:** Recognize that stages are sequential, not a graph
**Warning signs:** Finding yourself mapping stages to arbitrary transitions

### Pitfall 2: Mutable State in Executor
**What goes wrong:** ProcessExecutor holds process state, becomes stateful singleton
**Why it happens:** Easier to mutate in place than return new state
**How to avoid:** Executor is stateless; Process dataclass holds all state
**Warning signs:** Instance variables on ProcessExecutor other than dependencies

### Pitfall 3: Synchronous LLM Calls
**What goes wrong:** Blocking the event loop during question generation
**Why it happens:** Forgetting to await LLM calls
**How to avoid:** All ProcessExecutor methods are async
**Warning signs:** `await` missing from LLM client calls

### Pitfall 4: Not Emitting Events
**What goes wrong:** Process state changes without events; can't replay
**Why it happens:** Directly mutating Process instead of emitting events
**How to avoid:** Every state change → emit event → apply event
**Warning signs:** `process.status = ...` without corresponding event

### Pitfall 5: Blocking on Stage Completion
**What goes wrong:** Process waits indefinitely for user input
**Why it happens:** Not setting `max_iterations` or `can_skip`
**How to avoid:** Every stage has iteration limit; some stages can be skipped
**Warning signs:** Processes that never complete

</common_pitfalls>

<code_examples>
## Code Examples

### Process Definition (from spec)
```python
# Source: maro_2_0.md Part 7.1
@dataclass
class ProcessDefinition:
    process_type: str
    stages: list["StageDefinition"]
    description: str

@dataclass
class StageDefinition:
    name: str
    description: str
    required_outputs: list[str]
    max_iterations: int = 3
    can_skip: bool = False

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
        # ... more stages
    ]
)
```

### Stage Completion Check
```python
# Source: maro_2_0.md Part 7.2
def _stage_complete(self, stage_def: StageDefinition, stage_state: StageState) -> bool:
    """Check if stage has all required outputs."""
    return all(
        output in stage_state.gathered_info
        for output in stage_def.required_outputs
    )
```

### Plan Generation from Process Outputs
```python
# Source: maro_2_0.md Part 7.3
async def generate_from_process(self, process: Process) -> Plan:
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
            # Then create work items from plan
            for item in process.outputs.get("plan_items", []):
                items.append(PlanItem(
                    index=len(items),
                    action="create_work_item",
                    params=item
                ))

    return Plan(
        id=str(uuid4()),
        channel_id=process.channel_id,
        thread_ts=process.thread_ts,
        items=items,
        status=PlanStatus.PENDING,
        source_process_id=process.id
    )
```

</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Complex FSM libraries | Purpose-built simple executors | Less overhead for linear workflows |
| Blocking LLM calls | Async-first (asyncio) | Non-blocking stage progression |
| State in executor | Event-sourced process state | Replay-safe, consistent state |

**New tools/patterns to consider:**
- **LLMStateMachine** (robocorp) - interesting for future if we need AI-controlled state transitions
- **python-statemachine 2.5** - if we later need complex branching workflows

**Deprecated/outdated:**
- **XWorkflows** - last updated for Python 3.9, not recommended for new projects
- **Blocking synchronous patterns** - all modern Python should be async-first

</sota_updates>

<open_questions>
## Open Questions

1. **LLM Prompt Design for Stage Questions**
   - What we know: Spec shows basic prompt template
   - What's unclear: Optimal prompt structure for extraction vs follow-up
   - Recommendation: Start with spec's prompts, iterate based on testing

2. **Process Persistence Between Sessions**
   - What we know: Events are stored, state can be rebuilt
   - What's unclear: How to resume a process after bot restart
   - Recommendation: Load active processes from projection on startup

</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- maro_2_0.md Part 7 - Complete spec for Process/Plan/Workflow
- 05-CONTEXT.md - User vision: follow spec exactly

### Secondary (MEDIUM confidence)
- [python-statemachine docs](https://python-statemachine.readthedocs.io/) - Evaluated for complexity comparison
- [transitions GitHub](https://github.com/pytransitions/transitions) - Evaluated for fit
- [State Machine Based Human-Bot Conversation](https://pmc.ncbi.nlm.nih.gov/articles/PMC7266438/) - Academic pattern validation

### Tertiary (LOW confidence - for future reference)
- [llmstatemachine](https://github.com/robocorp/llmstatemachine) - Interesting for LLM-controlled state

</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Python async workflow execution
- Ecosystem: State machine libraries (transitions, python-statemachine)
- Patterns: Linear stage execution, event sourcing, LLM question generation
- Pitfalls: Over-engineering, mutable state, blocking calls

**Confidence breakdown:**
- Standard stack: HIGH - spec provides complete design
- Architecture: HIGH - spec Part 7 is detailed
- Pitfalls: HIGH - derived from event sourcing and async patterns
- Code examples: HIGH - directly from spec

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days - patterns are stable)
</metadata>

---

*Phase: 05-process-orchestration*
*Research completed: 2026-02-02*
*Ready for planning: yes*

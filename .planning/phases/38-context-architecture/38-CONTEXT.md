# Phase 38: Context Architecture - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<vision>
## How This Should Work

Context should be built from goal, not from "what we could load." Right now the system loads everything it can find and hopes the LLM sorts it out. Instead, context should be driven by ContextSpec — what mode are we in, what's the target, what's the purpose, what's the token budget, what artifacts are required.

When MARO processes a message, it should:
1. Know what task it's doing (BUILD/OPERATE/etc.)
2. Ask for exactly the context needed for that task
3. Get context in layers: canonical state (DB), working history (messages), retrieval add-ons (attachments)
4. Deliver a clean ContextPacket to the LLM with clear sections

The key insight: **checkpoint is cache for graph resume, not source of truth.** Things like `review_artifact` should live in the database, not just checkpoint. The checkpoint can cache them, but DB is authoritative.

</vision>

<essential>
## What Must Be Nailed

- **Goal-driven context** — ContextSpec determines what gets loaded, not "load everything available"
- **Three-layer separation** — Layer A (canonical DB state), Layer B (working history with rendered blocks), Layer C (retrieval add-ons)
- **Block rendering** — Bot messages with Slack blocks must be converted to `rendered_text` for LLM consumption. Bot says things via blocks, those need to be readable text.
- **review_artifact in DB** — Move from checkpoint-only to persistent store. Checkpoint is cache, DB is truth.
- **MessageIndex cache** — Expensive block rendering should be cached, not re-computed every time

</essential>

<specifics>
## Specific Ideas

**ContextSpec model:**
```python
ContextSpec:
  mode: SuperMode  # BUILD, OPERATE, DECIDE, THINK, CHAT
  target: str      # channel_id, thread_ts, workitem_id
  purpose: str     # "extract draft fields", "explain decision"
  budget_tokens: int
  required_artifacts: list[str]  # ["review_artifact", "decisions"]
```

**Three-layer architecture:**
- **Layer A: Canonical State** — From DB: registry, anchors, decisions, workitems, TaskPlan
- **Layer B: Working History** — Normalized messages with:
  - `message_type: "user" | "bot" | "system"`
  - `rendered_text` for bot messages (blocks → text)
  - MessageIndex for caching
- **Layer C: Retrieval Add-ons** — Attachments, Jira snapshots, summaries (chunked, budget-aware)

**ContextPacket output:**
```
=== SYSTEM STATE ===
[canonical from Layer A]

=== CONVERSATION ===
[normalized history from Layer B]

=== RETRIEVED ===
[chunked add-ons from Layer C]
```

**What changes:**
- `thread_state` narrows to binding + execution only (not everything)
- `conversation_context` gets block renderer + MessageIndex cache
- `channel_decisions` is Layer A (canonical), not fallback
- `review_artifact` moves from checkpoint to ReviewArtifactStore

</specifics>

<notes>
## Additional Context

This addresses the root cause of the OPS explain bug — the LLM was copying technical state dumps verbatim because context was unstructured. With proper layer separation, the LLM gets:
- Clean canonical state (what IS true)
- Readable conversation history (what was SAID)
- Retrieved extras (what's RELEVANT)

Not a dump of internal data structures.

The current `_build_conversation_context` in `src/slack/handlers/core.py` loads raw Slack history without rendering blocks. The `fetch_thread_history` in `src/slack/history.py` returns raw message payloads. Neither understands that bot messages need block rendering.

</notes>

---

*Phase: 38-context-architecture*
*Context gathered: 2026-01-25*

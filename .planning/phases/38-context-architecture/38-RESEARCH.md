# Phase 38: Context Architecture - Research

**Researched:** 2026-01-25
**Domain:** Internal Python/LangGraph context refactoring
**Confidence:** HIGH (codebase analysis, not external ecosystem)

<research_summary>
## Summary

Researched the current context-building architecture to understand what needs refactoring. The system has partial context layering but lacks:
1. Block rendering (bot messages with blocks → empty LLM context)
2. Goal-driven context (same context for all modes)
3. review_artifact persistence (checkpoint-only, lost between sessions)

The architecture follows a handler→graph→nodes pattern where context is built in handlers, injected into AgentState, and consumed by nodes. Message normalization exists but doesn't handle blocks. Checkpoint stores execution state but shouldn't be source of truth for artifacts.

**Primary recommendation:** Implement ContextSpec-driven loading with three-layer separation (DB canonical → working history with blocks → retrieval add-ons), and move review_artifact from checkpoint-only to database-backed.
</research_summary>

<current_architecture>
## Current Architecture

### Context Building Flow

```
Handler Layer (core.py)
    │
    ├─→ _build_conversation_context()  ←── Slack API or ListeningStore
    │   └─→ ConversationContext {messages, summary, last_updated_at}
    │
    └─→ runner.run_with_message(text, user, conversation_context)
            │
            ├─→ AgentState["conversation_context"] = conversation_context
            │
            └─→ Graph Execution
                    │
                    ├─→ intent_router_node() ←── classifies intent
                    │
                    ├─→ extraction_node() ←── uses conversation_context + review_artifact
                    │   └─→ Builds context_str for LLM prompts
                    │
                    └─→ review_node() ←── uses _build_context_string()
```

### State Sources

| Source | What It Stores | Persistence |
|--------|---------------|-------------|
| Checkpoint | Full AgentState including review_artifact | LangGraph persistence |
| ThreadStateStore | draft, pending_questions, step_count, workflow_step, bound_workitem_id | PostgreSQL |
| ChannelStateStore | workitem_ids, commit_ids, mode, jira_project, default_epic | PostgreSQL |
| Slack API | Raw message history with blocks | External (fetched on-demand) |
| ListeningStore | summary + raw_buffer for listening channels | PostgreSQL |

### Critical Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/slack/handlers/core.py` | 103-180 | `_build_conversation_context()` |
| `src/slack/history.py` | 16-227 | `fetch_thread_history()`, `ConversationContext`, `format_messages_for_context()` |
| `src/graph/runner.py` | 49-204 | `run_with_message()`, `_get_current_state()`, `_load_separated_state()` |
| `src/graph/nodes/extraction.py` | 640-880 | Context injection into extraction prompts |
| `src/graph/nodes/review.py` | 135-167 | `_build_context_string()` for review prompts |
| `src/graph/nodes/decision_approval.py` | 18-119 | Creates review_artifact (checkpoint-only) |
| `src/schemas/state.py` | 193-359 | AgentState TypedDict definition |
</current_architecture>

<gaps_identified>
## Critical Gaps

### Gap 1: No Block Rendering

**Current behavior:**
```python
# history.py:169
text = msg.get("text", "")  # Ignores blocks field entirely
```

**Impact:**
- Bot messages with blocks only → empty string in context
- LLM can't see questions, previews, status cards that bot posted
- Context appears incomplete to user ("why doesn't bot remember what it said?")

**Evidence:**
- Grep for `rendered_text`: Only in planning docs, not code
- No block-to-text conversion anywhere in codebase
- `format_messages_for_context()` only reads `text` field

### Gap 2: review_artifact Checkpoint-Only

**Current behavior:**
```python
# decision_approval.py:69-84
return {
    "review_artifact": {  # Only in checkpoint return
        "summary": summary,
        "kind": artifact_kind,
        ...
    }
}
```

**Impact:**
- Lost when thread closes and reopens
- Not available for cross-thread reference
- Can't query "what decisions were made in this channel"

**Evidence:**
- No `ReviewArtifactStore` exists
- `state.get("review_artifact")` in extraction.py:790 reads from checkpoint only
- ThreadStateStore doesn't store review_artifact

### Gap 3: No Goal-Driven Context

**Current behavior:**
- Same context built regardless of mode (BUILD/OPERATE/DECIDE/THINK/CHAT)
- No token budget enforcement
- No selective loading based on task requirements

**Evidence:**
- No `ContextSpec` class anywhere in codebase
- `_build_conversation_context()` has no mode parameter
- All context fields loaded unconditionally in `_get_current_state()`

### Gap 4: No Message Normalization

**Current format:**
```python
{"user": "U123", "text": "...", "ts": "...", "blocks": [...]}  # Raw Slack API
```

**Needed format:**
```python
{
    "message_type": "user" | "bot" | "system",
    "author": "U123" | "BOT",
    "text": "...",           # For user messages
    "rendered_text": "...",  # For bot messages (blocks → text)
    "ts": "...",
    "blocks": [...],         # Original if needed
}
```

### Gap 5: No MessageIndex Cache

**Current behavior:**
- Block rendering (when implemented) would run on every graph execution
- Same messages re-processed repeatedly
- No caching layer

**Impact:**
- Expensive operation repeated
- Latency on every message
- No incremental processing
</gaps_identified>

<architecture_patterns>
## Architecture Patterns (Recommended)

### Pattern 1: ContextSpec Model

**What:** Goal-driven context request specifying what to load
**When to use:** Every context build operation

```python
# src/context/spec.py (NEW)
class ContextSpec(BaseModel):
    mode: SuperMode                    # BUILD, OPERATE, DECIDE, THINK, CHAT
    target: str                        # channel_id, thread_ts, workitem_id
    purpose: str                       # "extract draft fields", "explain decision"
    budget_tokens: int = 4000          # Max tokens for context
    required_artifacts: list[str] = [] # ["review_artifact", "decisions"]
    include_history: bool = True       # Whether to load conversation
    history_limit: int = 20            # Max messages to include
```

### Pattern 2: Three-Layer Context

**What:** Separation of context sources by reliability/mutability
**When to use:** All context building

```
Layer A: Canonical State (DB)
├── ChannelDecisions (from DecisionStore)
├── WorkItems (from WorkItemStore)
├── ReviewArtifacts (from ReviewArtifactStore) ← NEW
├── Anchors (from AnchorStore)
└── Registry (from JiraRegistryStore)

Layer B: Working History (Slack + rendering)
├── ConversationContext.messages (normalized with rendered_text)
├── ConversationContext.summary (if listening mode)
└── MessageIndex cache (avoid re-rendering)

Layer C: Retrieval Add-ons (chunked, budget-aware)
├── AttachmentContext (pinned + retrieved chunks)
├── JiraSnapshots (ticket details when referenced)
└── ChannelSummary (for context on channel purpose)
```

### Pattern 3: Block Renderer

**What:** Convert Slack blocks to readable text
**When to use:** Bot messages with blocks

```python
# src/slack/block_renderer.py (NEW)
class BlockRenderer:
    def render(self, blocks: list[dict]) -> str:
        """Convert Slack blocks to human-readable text."""
        parts = []
        for block in blocks:
            block_type = block.get("type")
            if block_type == "section":
                parts.append(self._render_section(block))
            elif block_type == "actions":
                parts.append(self._render_actions(block))
            elif block_type == "context":
                parts.append(self._render_context(block))
            # etc.
        return "\n".join(parts)

    def _render_section(self, block: dict) -> str:
        text = block.get("text", {})
        return text.get("text", "")

    def _render_actions(self, block: dict) -> str:
        elements = block.get("elements", [])
        buttons = [e.get("text", {}).get("text", "") for e in elements if e.get("type") == "button"]
        return f"[Buttons: {', '.join(buttons)}]" if buttons else ""
```

### Pattern 4: ContextPacket Output

**What:** Structured context delivered to LLM
**When to use:** All prompt building

```python
# src/context/packet.py (NEW)
class ContextPacket(BaseModel):
    header: str           # Mode, target, purpose
    canonical: str        # Layer A - DB state
    history: str          # Layer B - conversation
    retrieved: str        # Layer C - add-ons
    total_tokens: int     # Tracked for budget

    def to_prompt(self) -> str:
        sections = []
        if self.canonical:
            sections.append(f"=== SYSTEM STATE ===\n{self.canonical}")
        if self.history:
            sections.append(f"=== CONVERSATION ===\n{self.history}")
        if self.retrieved:
            sections.append(f"=== RETRIEVED ===\n{self.retrieved}")
        return "\n\n".join(sections)
```

### Anti-Patterns to Avoid

- **Loading everything:** Don't load all context sources unconditionally
- **Checkpoint as truth:** Don't rely on checkpoint for persistent artifacts
- **Raw blocks to LLM:** Never pass Slack blocks array to LLM without rendering
- **Re-rendering on every request:** Cache rendered messages in MessageIndex
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token counting | Character math | tiktoken library | Accurate, handles encoding |
| Block parsing | Custom parser | Slack Block Kit types | Official types, maintained |
| State persistence | File-based | Existing PostgreSQL stores | Already have infrastructure |
| LRU cache | Dict with eviction | functools.lru_cache | Built-in, tested |

**Key insight:** The project already has PostgreSQL stores, Pydantic models, and LangGraph patterns. Extend existing infrastructure, don't create parallel systems.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Block Types Explosion

**What goes wrong:** Trying to handle all 20+ Slack block types perfectly
**Why it happens:** Slack Block Kit has many types with nested structures
**How to avoid:**
- Start with section, actions, context, divider (most common)
- Fallback to `[Unknown block]` for others
- Add types as needed based on actual usage
**Warning signs:** Spending days on edge cases that never appear

### Pitfall 2: Token Budget Overflow

**What goes wrong:** Context exceeds LLM context window
**Why it happens:** No budget enforcement during context building
**How to avoid:**
- Track tokens during build, stop when budget reached
- Prioritize: canonical → history → retrieved
- Truncate intelligently (summaries, not arbitrary cuts)
**Warning signs:** LLM errors about context length

### Pitfall 3: Cache Invalidation

**What goes wrong:** Stale rendered messages shown
**Why it happens:** Message edited in Slack but cache not invalidated
**How to avoid:**
- Key cache by (channel_id, ts, edited_ts)
- Include edited timestamp in cache key
- Short TTL for recent messages, longer for old
**Warning signs:** User sees outdated bot responses in context

### Pitfall 4: Circular Dependencies

**What goes wrong:** ContextBuilder imports from nodes, nodes import from ContextBuilder
**Why it happens:** Context is used everywhere
**How to avoid:**
- ContextSpec and ContextPacket are pure data classes (no logic)
- Builder lives in src/context/, doesn't import from graph/
- Nodes receive built context, don't build it
**Warning signs:** ImportError on startup
</common_pitfalls>

<implementation_approach>
## Implementation Approach

### Phase Order (dependency-driven)

1. **ReviewArtifactStore** (no dependencies)
   - New store in src/db/
   - Table: review_artifacts
   - Fields: id, channel_id, thread_ts, summary, kind, version, created_at

2. **BlockRenderer** (no dependencies)
   - New module src/slack/block_renderer.py
   - Handles common block types
   - Returns rendered_text string

3. **MessageIndex** (depends on BlockRenderer)
   - Cache for rendered messages
   - Key: (channel_id, ts, edited_ts)
   - Value: rendered_text

4. **ContextSpec model** (no dependencies)
   - New module src/context/spec.py
   - Pure Pydantic model

5. **ContextBuilder** (depends on all above)
   - New module src/context/builder.py
   - Takes ContextSpec, returns ContextPacket
   - Integrates all three layers

6. **Integration** (depends on ContextBuilder)
   - Update handlers to use ContextBuilder
   - Update nodes to consume ContextPacket
   - Migration: review_artifact checkpoint → DB

### Key Integration Points

**Handler layer (core.py):**
```python
# Before
conversation_context = await _build_conversation_context(...)

# After
spec = ContextSpec(
    mode=SuperMode.BUILD,
    target=f"{channel}:{thread_ts}",
    purpose="extract draft fields",
    budget_tokens=4000,
)
packet = await context_builder.build(spec)
```

**Node layer (extraction.py):**
```python
# Before
context_str = build_context_from_conversation(state.get("conversation_context"))

# After
packet = state.get("context_packet")
context_str = packet.to_prompt()  # Already structured
```
</implementation_approach>

<open_questions>
## Open Questions

1. **MessageIndex storage location**
   - What we know: Need caching for rendered blocks
   - What's unclear: PostgreSQL table vs Redis vs in-memory?
   - Recommendation: Start with in-memory LRU, add persistence if needed

2. **review_artifact migration**
   - What we know: Current data in checkpoints
   - What's unclear: How to migrate existing checkpoint data to new store?
   - Recommendation: Dual-write during transition, backfill from checkpoints

3. **Token budget allocation**
   - What we know: Need to split budget across layers
   - What's unclear: What's the right ratio? 40/40/20? 50/30/20?
   - Recommendation: Make configurable per ContextSpec, tune empirically
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- Codebase analysis: src/slack/handlers/core.py, src/graph/runner.py, src/graph/nodes/
- 38-CONTEXT.md user vision document
- Existing store patterns: ThreadStateStore, ChannelStateStore, ArtifactStore

### Secondary (MEDIUM confidence)
- Slack Block Kit documentation (block types and structure)
- LangGraph checkpoint documentation (state persistence patterns)
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Python, LangGraph, PostgreSQL
- Ecosystem: Slack Block Kit, Pydantic
- Patterns: Context layering, state separation, caching
- Pitfalls: Token overflow, cache invalidation, circular imports

**Confidence breakdown:**
- Current architecture: HIGH - direct codebase analysis
- Recommended patterns: HIGH - based on existing project patterns
- Pitfalls: MEDIUM - based on experience, not observed failures
- Implementation approach: HIGH - follows project conventions

**Research date:** 2026-01-25
**Valid until:** N/A (internal architecture, not external ecosystem)
</metadata>

---

*Phase: 38-context-architecture*
*Research completed: 2026-01-25*
*Ready for planning: yes*

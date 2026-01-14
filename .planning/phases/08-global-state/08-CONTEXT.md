# Phase 8: Global State - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

Phase 8 is the moment when the bot stops being a "thread-session" and becomes a **channel organism**: it knows what's happening in this channel, what the rules are, which epics are active, and why people have been arguing about timestamp vs ISO for the third month.

**Core principle:** Global State must be:
1. Channel-scoped (not global-global)
2. Layered (multiple sources with priorities)
3. Incrementally updated (not "re-read everything each time")

**The golden rule:**
> Global State is "default context", NOT "truth".
> Truth lives in Jira and confirmed constraints.

The bot becomes "PM-level" — it remembers not just the thread, but the **culture of the channel**.

</vision>

<essential>
## What Must Be Nailed

- **Layered model over monolithic blob** — 4 layers with clear priorities:
  1. Channel Profile (manual settings) — default project, trigger rules, epic binding behavior
  2. Channel Knowledge (pinned facts) — "How we work here", conventions, DoD. **Higher priority than LLM guesses**
  3. Channel Activity Snapshot (live summary) — active epics, recent tickets, top constraints, unresolved conflicts
  4. Derived Signals (computed) — hot topics, frequent entities, typical duplicates, common priority

- **Versions and hashes everywhere** — idempotency for updates, pinned content hash, Jira sync cursor

- **Context doesn't dominate threads** — agent gets: (1) session state, (2) epic context, (3) channel context briefly (top 10 bullets max). Channel context is configurable — some channels don't want "bot remembers everything"

- **Staleness is the enemy** — TTL/retention, refresh policy, "stale pins" detection

</essential>

<specifics>
## Specific Ideas

### 4-Layer Storage Model

**Layer 1 - Channel Profile (manual config):**
- default_jira_project / board
- trigger_rule: "mention_only" | "listen_all"
- epic_binding_behavior
- language / tone settings

**Layer 2 - Channel Knowledge (pinned facts):**
- Pinned "How we work here"
- Pinned "Current Epic / Roadmap"
- Pinned "API conventions"
- Processed into structured constraints: naming_convention, definition_of_done, api_format_rules

**Layer 3 - Channel Activity Snapshot:**
- active epics in this channel
- recent created tickets
- top constraints by active epics
- unresolved conflicts

**Layer 4 - Derived Signals:**
- hot topics
- frequent entities
- typical duplicates
- common priority patterns

### Postgres Schema (minimal)

```sql
channel_context:
  - team_id, channel_id
  - config_json (manual settings)
  - pinned_digest (hash/version)
  - snapshot_json
  - updated_at

channel_sources:
  - what we analyzed: message_ts, pin_id, jira_sync_cursor

channel_context_events (optional audit):
  - "why context changed"
```

### Pinned Content Processing

- Hash pinned-set (pin_ids + message_ts) → if unchanged, don't recompute
- Mark "stale pins": if pinned older than X months, bot can softly suggest update
- Convert to structured "channel constraints" (not free text)

### Root Message Indexing

- Catalog of root topics (last N weeks)
- Extract tags/entities (not full text)
- Index: root_ts → epic_id → ticket_keys

### Jira History Integration

**Linkage rules:**
- Jira ticket description stores Slack thread permalink
- Slack preview stores Jira key
- Channel gets: "Recent tickets from this channel", "Active Epics discussed here", "Most common labels/components"

**What to pull from Jira (minimal):**
- issue created/updated timestamps
- status transitions
- assignee, priority
- labels/components
- epic link / parent

**NOT full changelog — store as "channel index", not Jira copy**

**Sync strategy:**
- Incremental sync by time (cursor)
- Batch updates (cron/worker), NOT in Slack handler
- Store only needed fields

### Suggested Plan Breakdown (5 plans instead of 3)

08-01: ChannelContext schema + config + API
08-02: Pin ingestion + pinned-to-constraints extractor
08-03: Root message indexer (root → epic → threads)
08-04: Jira linkage + incremental sync cursor
08-05: Retrieval strategy (how agent gets compressed context)

This separates storage, ingestion, and retrieval cleanly.

</specifics>

<notes>
## Additional Context

### Main Risk

"Global State" easily becomes:
- Source of stale truth
- Overbearing "bot knows better"
- Storage of everything

**Antidote:**
- Layered model
- Versions + cursors
- Compression + limits
- Priority: pinned + Jira > guesses

### Pitfalls to Watch

- Context grows infinitely → need TTL/retention
- Context goes stale → need refresh policy
- Channel can be multi-project → context must support "multiple project keys"
- Jira rate limits → incremental sync, batch updates
- Different projects have different fields → flexible mapping

### Definition of Done

- ChannelContext in DB with versions/hashes
- Pins analyzed and converted to "channel rules"
- Root messages indexed and linked to epics
- Jira tickets created by bot go into channel index
- Agent can request "channel context summary" and get short, stable output

</notes>

---

*Phase: 08-global-state*
*Context gathered: 2026-01-14*

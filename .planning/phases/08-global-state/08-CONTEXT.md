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

- **Layered model over monolithic blob** — 4 layers with explicit priority order:
  1. Channel Knowledge (pinned facts) — "How we work here", conventions, DoD. **Highest priority**
  2. Jira (facts) — tickets, statuses, what actually happened
  3. Channel Profile (manual settings) — default project, trigger rules, epic binding behavior (defaults/preferences)
  4. Derived Signals (computed) — hot topics, frequent entities, typical duplicates (suggestions only)

  **Conflict rule:** Higher layer wins. Pins > Jira facts > Profile defaults > Derived guesses.

- **Versions and hashes everywhere** — idempotency for updates, pinned content hash, Jira sync cursor

- **Context doesn't dominate threads** — agent gets: (1) session state, (2) epic context, (3) channel context briefly (top 10-20 bullets max). Channel context is configurable — some channels don't want "bot remembers everything"

- **Staleness discipline** — prevents "ghost context":
  - Pins refresh: on change (hash-based)
  - Activity snapshot: periodic (every X hours) + on major events (new epic bound / ticket created)
  - Derived signals: TTL (7-30 days), recalculated in batches

</essential>

<specifics>
## Specific Ideas

### 4-Layer Storage Model

**Layer 1 - Channel Profile (manual config):**
- default_jira_project / board — **most important setting, configure first**
- trigger_rule: "mention_only" | "listen_all"
- epic_binding_behavior
- language / tone settings
- config_permissions: "locked" | "open" (who can change settings)

**Configuration UX:**
- Primary: `/analyst config` slash command (opens modal or shows settings)
- Secondary: Bot conversation ("set default project to PROJ")
- Permissions: Configurable per channel — locked (admins only) vs open (any member)

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

- Catalog of root topics with **explicit window: last 30-90 days**
- Extract tags/entities (not full text)
- Index: root_ts → epic_id → ticket_keys
- "Pinned root threads" can live beyond window
- **Retention policy:** Old roots collapse into summary, raw not stored

### Jira History Integration

**Linkage rules:**
- **Binding rule:** Slack thread ↔ Jira issue linkage via permalink stored in Jira + issue key stored in session
- This connects Phase 7 (jira_create) with Phase 8 (channel index)

**Bot pins epic/ticket message in thread:**
- On epic binding → pin message with epic link
- On ticket creation → update same pinned message to include ticket
- Separate from session card — dedicated pinned message for Jira links
- Makes the Jira connection visible and clickable in every thread

**Pin management — consolidate to summary:**
- One pinned message per thread (not multiple)
- Format: Summary only — "Epic: PROJ-123 | Ticket: PROJ-456 | Status: Created"
- Updated in place as state changes (not new pins)
- Clean and scannable
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

### Background Sync Architecture

**Model:** Hybrid — events for urgent updates, cron for full refresh

**Event-driven triggers (immediate):**
- Pin changes (message pinned/unpinned)
- Ticket created by bot
- Epic bound to thread
- Any significant channel activity

**Cron triggers (periodic):**
- Full Jira sync (every N hours)
- Derived signals recalculation (daily/weekly)
- Stale context cleanup

**NOT in Slack handler** — async workers to avoid blocking user interactions

### First-Time Channel Setup

**When bot joins a new channel:**
1. **Automatic pin scan** — immediately scan pinned messages to build initial context
2. **Welcome message** — post intro message with:
   - What the bot does
   - How to configure (`/analyst config`)
   - Default project prompt (most important setting)
3. **Empty state is OK** — bot works without config, just with fewer defaults

**No wizard** — too intrusive. Welcome message + `/analyst config` is enough.

### Context Debugging

**Primary tool:** Admin web panel (extends existing admin routes)
- Shows context per channel
- Shows which sources contributed (pins, Jira, root index)
- Shows context version and freshness
- Can inspect individual thread's context snapshot

**Why admin panel over Slack commands:**
- More space to show complex information
- Easier to navigate history
- No noise in channels
- Already have admin routes infrastructure

### Error Handling

**When context fetch fails:**
1. Retry a few times (with backoff)
2. If still failing → gracefully degrade
3. Agent works without context, uses defaults
4. No blocking, no user-facing error unless critical
5. Log for debugging, don't spam channels

### Testing Strategy

**Primary approach:** Unit tests + mocks
- Mock Slack API (pins, messages, channels)
- Mock Jira API (issues, search results)
- Test context logic in isolation
- Fast, reliable, no external dependencies

**No integration tests with real Slack in Phase 8** — test real integration manually during dev

### Privacy/Visibility

**Context is internal only:**
- Users don't see raw context
- No `/analyst context` command for users
- Context is used by bot to make better decisions
- Debugging via admin panel (not Slack)
- Keeps channels clean, avoids "bot surveillance" feeling

### Suggested Plan Breakdown (5 plans instead of 3)

08-01: ChannelContext schema + config + API
08-02: Pin ingestion + pinned-to-constraints extractor
08-03: Root message indexer (root → epic → threads, 30-90 day window)
08-04: Jira linkage + incremental sync cursor (binding: permalink ↔ issue key)
08-05: Retrieval strategy (how agent gets compressed context)

This separates storage, ingestion, and retrieval cleanly.

### Context Retrieval Contract

Agent API for getting channel context:
```python
get_channel_context(channel_id, mode="compact") -> ChannelContextResult
```

**Modes:**
- `compact` — max 10-20 bullets + links + version (production)
- `debug` — full details, for troubleshooting only
- `raw` — internal use

**Always include:**
- `context_version` — for cache invalidation
- `sources` — which pins/jira/roots contributed
- Enables explaining "why bot decided this way"

### Context Injection Strategy

**When:** Always on new thread start — every thread begins with channel context
**Where:** Embedded in AgentState (not in prompt directly) — extraction/validation nodes can access it
**Flow:**
1. New thread detected → fetch `get_channel_context(channel_id, "compact")`
2. Store in AgentState as `channel_context` field
3. Extraction/validation nodes use it for defaults, constraints, conventions
4. Not dumped into LLM prompt — used programmatically by nodes

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

- Context grows infinitely → TTL for derived signals, but **base context kept forever**
- Context goes stale → refresh policy for activity snapshots
- Channel can be multi-project → **Primary + secondary model**: one default project, others available on request
- Channel archival → **Keep forever** — if channel revives, context is still there
- Cross-channel → **Global Jira index** — channel contexts isolated, but all channels contribute to workspace-wide Jira knowledge (better duplicate detection, smarter patterns)
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

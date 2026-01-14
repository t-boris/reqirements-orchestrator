# Phase 4: Slack Router - Context

## Vision Summary

Build a Slack integration with **Hub & Spoke architecture**: Epics are containers, threads are working sessions. The bot acts as a Project Manager maintaining coherence across discussions.

**Scope Revision**: Phase 4 proves the **infrastructure spine**. Memory layers store and retrieve, but don't police. PM behaviors (dedup, contradiction enforcement) come later after quality is validated.

## Core Concept: Hub & Spoke Model

### Epic as Container
- Epic is an entity in Jira AND in Knowledge Graph
- Threads are working sessions that contribute to an Epic
- One Epic can have MANY threads across time
- Bot maintains cross-thread consistency

### The Four Rules (Implementation Phased)

**Rule 1: Context Binding** — Phase 4A (enforced)
Every thread with bot interaction gets bound to an Epic.
- DoD: `session(thread_ts) -> epic_id` stored
- DoD: Pinned "Session Card" in thread (epic link, status, commands)
- LLM only for *suggesting* epics, not enforcing

**Rule 2: Traffic Cop / Dedup** — Phase 4C (non-blocking suggestions only)
- Only trigger on extremely high similarity
- Non-blocking: "Related thread exists; want me to link it?"
- Log similarity score + rationale
- Button: "Merge context" (adds link to session card)

**Rule 3: Cross-Thread Context** — Phase 4C (query only, alert with confirmation)
- Bot can answer: "What constraints exist for this epic?"
- Contradiction alerts require:
  - Subject match + conflicting accepted values
  - User confirmation: "Mark as conflict" / "Override previous"

**Rule 4: Aggregation** — Phase 4C (batch writes with changelog)
- Write to Epic description in batches (per N decisions or manual command)
- Every write includes changelog entry + source thread links

## Architectural Principles

### Separate Ingestion from Decisioning
- **Ingestion** (inline): Store message → session → epic linkage
- **Decisioning** (deferred/async): Dedupe checks, contradiction scans, summaries
- Don't run everything inline inside Slack handlers

### Explicit Triggers Only (Phase 4)
No "LLM-based classification on all messages" — too many dragons:
- Cost + latency at scale
- Privacy concerns ("bot reading everything")
- False positives erode trust
- Hard to debug

**Phase 4 triggers:**
1. `@mention`
2. `/jira <subcommand>`
3. Message in thread where bot already participates

Ambient listening deferred to later phase with per-channel opt-in + clear banner.

### Idempotency and Serialization
Socket Mode has retries. Events arrive close together. Threads have parallel replies.

Required:
- **Idempotency**: Dedupe by Slack event_id / message_ts
- **Per-thread serialization**: One run at a time per thread_ts
- **Canonical identity**: `session_id = team:channel:thread_ts`

## Phase 4 Layered Structure

### Phase 4A: Slack Spine (ship first, rock solid)

**04-01**: Bolt + Socket Mode + permissions + basic handlers
- Slack app setup, Socket Mode connection
- Permission scopes: `chat:write`, `commands`, `app_mentions:read`
- Ignore message subtypes (edited, bot messages)
- Ack immediately, enqueue work

**04-02**: Router: mentions + slash commands + event handling
- @mention detection
- `/jira create|search|status` slash commands
- Ignore bots/edits, fast ack pattern
- Rate limit + backoff for Web API calls

**04-03**: Session model + persistence + serialization
- Session identity: `team:channel:thread_ts`
- LangGraph checkpointer (PostgresSaver)
- Dedupe store (event_id tracking)
- Per-session lock (serialize runs per thread)

**04-04**: Epic binding flow (UI)
- Suggest epics (Zep semantic search)
- Pick epic / create new epic placeholder
- Session Card message (pinned in thread)
- `session(thread_ts) -> epic_id` persistence

✅ **Checkpoint**: Every thread with bot interaction reliably attached to an Epic.

### Phase 4B: Memory Plumbing (store first, judge later)

**04-05**: Zep integration (storage + search API)
- Zep client setup
- Store Epic summaries as searchable memories
- Store thread summaries for later dedup
- Search API for epic suggestions
- **No enforcement** — just storage and retrieval

**04-06**: Knowledge Graph schema + storage
- PostgreSQL tables: entities, relationships, constraints
- **Structured constraints** (not free-form text):
```yaml
constraint:
  subject: "API.date_format"
  value: "unix_timestamp"
  status: proposed|accepted|deprecated
  source: thread_ts + message_ts
```
- Entity/constraint storage API
- Retrieval: "What constraints exist for this epic?"

**04-07**: Document processing (PDF, DOCX, MD, TXT)
- File downloader (Slack attachments)
- Text extractors (pypdf, python-docx)
- Content normalizer for LLM consumption
- Store extracted content in session context

✅ **Checkpoint**: Can persist and retrieve session state, constraints, documents without duplication/races.

### Phase 4C: PM Behaviors (turn on carefully)

**04-08**: Dedup suggestions (high-confidence, non-blocking)
- Only when similarity extremely high
- Suggest, don't block: "Related thread exists"
- Log similarity score + rationale
- "Merge context" button

**04-09**: Contradiction detector (structured, with approval)
- Only on accepted constraints
- Subject match + value conflict detection
- Approval buttons: "Mark as conflict" / "Override"
- No free-form text contradiction (too noisy)

✅ **Checkpoint**: PM behaviors that help without being annoying.

## Slack-Specific Checklist

### Permissions (decide early)
- `chat:write` — send messages
- `commands` — slash commands
- `app_mentions:read` — @mention events
- `channels:history` — only if ambient listening (later)
- `files:read` — for document attachments

### Event Handling
- Ignore message subtypes: `message_changed`, `message_deleted`, bot messages
- Ack within 3 seconds, enqueue actual work
- Handle Socket Mode reconnection gracefully

### Rate Limiting
- Backoff for Web API calls
- Queue outgoing messages if hitting limits

### Identity and Deduplication
- Canonical: `session_id = {team_id}:{channel_id}:{thread_ts or ts}`
- Dedupe store: track processed `event_id` / `client_msg_id`
- Per-session queue/lock: serialize LangGraph runs per thread

### Operating Modes (per channel)
- Default: explicit triggers only (@mention, slash commands)
- Opt-in: ambient monitoring (future phase)
- Clear banner when bot monitors a channel

## Constraint Data Model

Free-form text contradictions become LLM judgment calls → random nags.

**Structured approach:**
```sql
constraints (
  id UUID PRIMARY KEY,
  epic_id UUID NOT NULL,
  thread_ts VARCHAR(32) NOT NULL,
  message_ts VARCHAR(32),
  subject VARCHAR(255) NOT NULL,  -- e.g., "API.date_format"
  value TEXT NOT NULL,             -- e.g., "unix_timestamp"
  status VARCHAR(20) DEFAULT 'proposed',  -- proposed|accepted|deprecated
  created_at TIMESTAMP DEFAULT NOW()
)
```

Contradiction detection:
- Subject same, value differs → conflict
- Subject overlaps (date_format vs timezone) → maybe conflict (flag for review)

## Definition of Done

### Phase 4A Complete When:
- [ ] Bot connects via Socket Mode, stays connected
- [ ] @mention triggers bot response in thread
- [ ] `/jira create|search|status` commands work
- [ ] Every thread interaction creates/updates session
- [ ] Session Card posted with epic link
- [ ] No duplicate processing of same event
- [ ] Per-thread serialization prevents race conditions

### Phase 4B Complete When:
- [ ] Zep stores and retrieves epic/thread summaries
- [ ] KG stores structured constraints
- [ ] Documents extracted and content available in session
- [ ] Can query: "What constraints exist for epic X?"

### Phase 4C Complete When:
- [ ] High-confidence dedup suggestions appear (non-blocking)
- [ ] Contradiction alerts only for accepted constraints with subject match
- [ ] User can approve/override contradictions
- [ ] Epic aggregation writes batched with changelog

## Dependencies

### New Dependencies
- `slack-bolt>=1.18` — Slack app framework
- `slack-sdk>=3.21` — Low-level Slack API
- `zep-python>=2.0` — Zep memory client
- `pypdf>=4.0` — PDF text extraction
- `python-docx>=1.0` — DOCX text extraction

### Infrastructure
- Zep server (Docker) for semantic memory
- PostgreSQL tables for KG entities/constraints
- Redis optional for dedupe store (or PostgreSQL)

### Integration Points
- **Phase 2**: PostgresSaver checkpointer, database connection pool
- **Phase 3**: get_llm() for epic suggestion, entity extraction
- **Phase 5**: Agent core consumes session events

## Key Insight

> "Phase 4 should primarily prove:
> 1. You can reliably bind Slack threads to Epics
> 2. You can persist and retrieve session state without duplication/races
> 3. Your memory layers can store + fetch (before they start policing humans)
>
> Do that, and Phase 5 becomes fun instead of a firefight."

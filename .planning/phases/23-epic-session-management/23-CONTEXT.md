# Phase 23: Communication as Source of Truth — Context

**Gathered:** 2026-01-20
**Status:** Ready for planning

<vision>
## How This Should Work

MARO is not a "Jira bot" — it's a **collective thinking system** where communication is the source of truth and Jira is a projection/replica of that truth.

### The Core Model

**Channel = Source of Truth (workspace)**
- Contains a registry of WorkItems (0..N): Epics, Stories, Bugs, Tasks, Spikes
- Stores canonical facts/decisions (constraints, architecture decisions)
- Has a "mode" that determines default behaviors (project/feature/bugs/ops)
- Maintains a git-log style commit history of all changes

**Thread = Working Branch (local session)**
- Where exploration, discussion, and drafting happens
- Changes are "drafted" in thread, then "committed" to channel
- Can have mode override (e.g., bug thread in project channel)

**Jira = Execution Replica**
- A projection of selected truths from communication
- Receives "deployments" of work items
- Can have "hotfixes" (direct edits) that sync back
- Never overwrites channel truth without conflict resolution

### The Key Metaphor

Not "discussion is attached to Jira."
Instead: **"Jira reflects what became truth in communication."**

### Channel Work Board (pinned, git-log style)

```
Channel Work Board

Mode: project (set by @boris)

Recent Commits:
14:32 Decision: Use background worker + idempotency key [thread]
14:15 STORY draft created: Retry mechanism [thread]
13:50 EPIC PROJ-50 updated: Added auth requirements [thread]

Active Work Items:
- EPIC PROJ-50 Email System (active, Jira: PROJ-50)
- STORY (draft) Retry mechanism
- BUG PROJ-311 Duplicate emails (triage, Jira: PROJ-311)

Untriaged: 0 items
```

Entries are minimal: timestamp + summary + thread link.

</vision>

<essential>
## What Must Be Nailed

### 1. WorkItem Registry (not "Epic container")

Replace "session binds to Epic" with "contribution binds to WorkItem (any type)":
- WorkItem types: Epic, Story, Bug, Task, Spike
- Each has: local_id, jira_key (nullable), status (draft/active/done), summary, facts
- Drafts are first-class citizens — live in registry, sync to Jira only on explicit action
- No orphan contributions — everything lands in a WorkItem or Untriaged Inbox

### 2. Channel Mode (deterministic, not magic)

Three-layer approach:
1. **Manual config** = source of truth (`/maro mode project`)
2. **Suggested + confirm** = one-time convenience for first setup
3. **Per-thread override** = handles messy reality (bug thread in project channel)

Modes affect:
- Intent routing defaults
- Scope gate options
- Work item type preferences
- Jira sync strictness

### 3. Commit Semantics (explicit approval only)

**Nothing becomes channel truth without explicit approval.**

- MARO detects "significant events" (decision approved, ticket created, constraint captured)
- Shows commit preview with summary of what will be committed
- User clicks "Approve & Commit"
- Entry added to Channel Work Board log with thread link

No time-based batching. No silent auto-commits. The channel stays clean.

### 4. Jira Sync Strategy (bidirectional with manual merge)

**Offer-on-ready, create-on-explicit:**
- MARO calculates readiness_score for drafts
- When ready: shows CTA (Create in Jira / Keep local / Edit)
- Creation only on explicit action with idempotency key

**Field classification:**
- Jira-owned: status, assignee, story points (Slack can suggest, not push)
- Slack-owned: description sections, links, decisions/constraints
- Shared: priority, due date, dependencies (conflict-detect)

**Section-level sync:**
- Description stored as structured blocks (Problem, AC, Architecture, Source)
- Fingerprint per section to detect what changed
- Conflict = both sides changed same section → manual resolution

**Never silent overwrites:**
```
Sync conflict for PROJ-123 (Architecture Notes)
Slack version (commit C-0091): …
Jira version (edited by @alex): …
[Keep Slack] [Keep Jira] [Merge manually]
```

</essential>

<specifics>
## Specific Ideas

### Channel Work Board UX
- Git-log style: minimal entries showing commits chronologically
- Format: `14:32 Decision: Use background worker [thread]`
- Pinned in channel, auto-updated on commits
- Header shows mode and who set it

### Commit Preview UX
```
Draft ready

Summary (what will be committed):
- Decision: Use background worker + idempotency key
- Work items: EPIC PROJ-50 updated, STORY draft created

[Approve & Commit] [Edit] [Not now]
```

### Mode Configuration
- `/maro mode project` — full work item types
- `/maro mode feature --primary-epic PROJ-50` — focused on one epic
- `/maro mode bugs` — bug/task focused, epic suppressed
- `/maro mode ops` — incidents, runbooks, stricter Jira writes

### Draft Workflow
- Drafts are first-class in WorkItem registry
- Shown on board with "(draft)" status
- Readiness calculated automatically
- CTA shown when ready: Create in Jira / Keep local / Edit

</specifics>

<notes>
## Additional Context

### Philosophy Shift

This phase transforms MARO from "Jira integration bot" to "collective thinking system":
- Jira is one output, not the source of truth
- Communication patterns (discussions, decisions, drafts) are the primary artifacts
- Explicit approval gates maintain trust and cleanliness

### Backward Compatibility

The original 5 issues (ISS-001, ISS-003, ISS-004, ISS-005, ISS-006) are absorbed into this larger vision:
- `/jira create` → becomes part of WorkItem creation flow
- `/jira status` → replaced by Channel Work Board
- Session cards → replaced by WorkItem entries with Jira links
- Epic binding → replaced by WorkItem-to-Jira replication

### Technical Foundation

Existing infrastructure to build on:
- SessionStore → evolves into WorkItemStore
- binding.py → evolves into sync engine
- ChannelContext (Phase 8) → extended with mode and commit log
- Phase 21 tracking → integrates with WorkItem registry

### Sync Triggers

- Event-driven: Jira webhooks for real-time updates
- Cron safety net: periodic full refresh to catch missed webhooks
- Manual: `/maro sync` for on-demand comparison

</notes>

---

*Phase: 23-communication-source-of-truth*
*Context gathered: 2026-01-20*

# Phase 25: WorkItem-Centric Architecture

## Status: DISCUSSION

---

## Core Philosophy

**Current:** Jira-centric — "proactive Jira ticket analyst"
**Target:** WorkItem-centric — "requirements orchestrator"

**Mantra:** "Threads propose. Channels decide. Jira executes."

---

## Git Model (Explicit)

| Git Concept | MARO Equivalent | Description |
|-------------|-----------------|-------------|
| Repository | Channel | Source of truth, owns registry |
| Working Tree | Thread | Exploration/drafting space |
| Commit | Approved Decision | Immutable truth entry |
| Remote | Jira | Deployment target (replica) |
| Push | Sync/Publish | Propagate truth to Jira |

**Key insight:** Jira is not the source of truth. Jira is where truth gets *deployed* after being decided in the channel.

---

## New Intents

### 1. OPS Intent (with subtypes)

**Decision:** Single `OPS` intent with `subtype: DEBUG | EXPLAIN`

**Rationale:**
- Engine benefits from shared infrastructure (state snapshot, event correlation, log formatting, safe redaction, retry policies)
- UX benefits from two distinct "manners" for the user

```python
class OpsSubtype(str, Enum):
    DEBUG = "debug"    # Triage + retry
    EXPLAIN = "explain"  # Policy trace
```

#### Subtype: DEBUG

**Triggers (deterministic):**
- Error patterns: `error`, `failed`, `exception`, `stack trace`, `timeout`, `rate limit`, `permission denied`
- Phrases: "fix this error", "why did this fail", "retry"
- Context: Bot just reported a failure

**Behavior:**
1. Skip review/ticket extraction
2. Triage flow: What failed → Probable cause → Plan → Retry
3. Log + idempotency

#### Subtype: EXPLAIN

**Triggers:**
- "why did you do that?"
- "show me your reasoning"
- "how did you decide?"

**Behavior:**
1. Output in state machine terms:
   - Intent detected: X
   - Policy applied: Y
   - Action executed: Z
2. System operator perspective (not LLM chain-of-thought)

#### UX Commands

| Command | Effect |
|---------|--------|
| `/maro debug` | Force OPS(subtype=DEBUG) |
| `/maro explain` | Force OPS(subtype=EXPLAIN) |

Buttons:
- "Explain this decision" → EXPLAIN
- "Investigate failure" → DEBUG

---

### 3. CHANGE_REQUEST (Diff-Based Updates)

**Purpose:** Modify existing truth (not create new).

**Key difference from TICKET/WORKITEM_CREATE:**
- TICKET: Create new unit of work (draft → ready → publish)
- CHANGE_REQUEST: Change existing truth in ChannelState and/or Jira replica

**Triggers (high confidence):**
- Verbs: "change", "update", "modify", "rename", "remove", "drop", "replace"
- Phrases: "this is wrong", "not like that", "we decided differently"
- Actions: "delete this ticket", "split into 3 tickets", "move under another epic"

**Flow:**
```
1. Identify target(s)
   - WorkItem(s) by key/id
   - Last committed decision
   - Jira issue(s)

2. Build diff
   - What changes?
   - Before/after preview

3. Show diff preview
   ┌────────────────────────────────┐
   │ CHANGE REQUEST                 │
   │                                │
   │ Target: SCRUM-123              │
   │                                │
   │ - priority: Medium → High      │
   │ - summary: "Old" → "New"       │
   │ + labels: ["urgent"]           │
   │                                │
   │ [Approve] [Edit] [Cancel]      │
   └────────────────────────────────┘

4. Require explicit approve

5. Apply updates to:
   - Channel truth (WorkItem registry + commit log)
   - Jira replica (if sync enabled)
```

**ADR/Architecture decisions:**
- ADR created → commit
- "Architecture changed" → CHANGE_REQUEST → diff → commit → update
- CHANGE_REQUEST is not limited to ADR — covers any edit of existing truth

---

## ReviewArtifact Model

### Why not `WorkItem(type=Review)`?

**WorkItem = unit of execution** (potentially goes to Jira)
**Review = knowledge/reasoning/decision** (not always a task)

Problems with Review-as-WorkItem:
- Registry bloats with non-actionable items
- People start treating reviews as tasks to "complete"
- Jira receives "architecture review tickets" (usually unwanted)

### Why not just a flat table?

Need to support:
- Link review to commits
- Handoff Review → Ticket
- Diff/change request based on review content

### Proposed Model

```python
class ReviewArtifact(BaseModel):
    artifact_id: str
    channel_id: str
    source_thread_ts: str
    kind: Literal["architecture", "security", "pm", "general"]
    version: int
    content_hash: str
    summary: str
    decisions: list[str]
    risks: list[str]
    open_questions: list[str]
    created_at: datetime
    approved_by: Optional[str]
    approved_at: Optional[datetime]
```

```python
class ArtifactLink(BaseModel):
    artifact_id: str
    target_type: Literal["workitem", "commit", "jira"]
    target_id: str  # workitem_id, commit_id, or jira_key
    link_type: Literal["derived_from", "resulted_in", "references"]
```

### When Review becomes WorkItem

Only on explicit user request:
- "create an ADR ticket"
- "create a Spike for architecture"
- "track this decision as a task"

Result: `WorkItem(type=Task|Spike)` with link to artifact.

---

## Documentation Changes

### 1. System Identity (HOW_THE_BOT_THINKS.md §4.1)

**Current:**
> "You are a proactive Jira ticket analyst..."

**Proposed:**
> "You are a requirements orchestrator. Your role is to:
> 1. Capture decisions from conversations
> 2. Build complete, unambiguous work items
> 3. Maintain channel truth (the registry)
> 4. Sync truth to external systems (Jira) on demand
>
> You never create half-baked items. Chat is the source of truth."

### 2. Rename Flows (Dual-Stack Migration)

**Decision:** Rename TICKET → WORKITEM_CREATE with backward compatibility.

**Why rename:**
- "Ticket" makes Jira the center
- "WorkItem" fixes the philosophy: channel = truth, Jira = publication
- Affects LLM quality: stops forcing Jira-format in reviews

**Migration strategy:**

| Layer | Approach |
|-------|----------|
| Intent/Classifier | Accept both TICKET and WORKITEM_CREATE, internally always use WORKITEM_CREATE |
| State | Always store as WORKITEM_CREATE |
| Interface | Show only "WorkItem", keep `/jira create` as shortcut |
| Commands | Add `/maro create` or `/maro workitem` |
| Logs/Metrics | Map old → new to preserve dashboards |
| Code | Mark `TICKET` as deprecated, remove after 1-2 releases |

**Code changes:**
```python
class Intent(str, Enum):
    WORKITEM_CREATE = "workitem_create"  # Primary
    TICKET = "ticket"  # Deprecated alias

# In router:
if intent == Intent.TICKET:
    intent = Intent.WORKITEM_CREATE  # Normalize
```

### 3. New Section: Git Model

Add explicit section explaining:
- Channel = repository
- Thread = working tree
- Commit = approved decision
- Jira = remote/deployment target

### 4. New Section: Commit Semantics

Extract from scattered mentions into dedicated section:
- What is a commit?
- What triggers commit preview?
- Commit log structure
- Relation to Jira sync

### 5. Dedupe Order

**Current:** Search Jira first
**Proposed:**
1. Check Channel registry (local)
2. Then check Jira (remote)
3. Prefer local matches over remote

---

## State Separation

### Current: Mixed in AgentState

Thread and channel concerns mixed together.

### Proposed: Explicit Separation

```python
class ChannelState(BaseModel):
    """Channel-level truth (the repository)"""
    channel_id: str
    workitem_registry: list[WorkItem]
    commit_log: list[Commit]
    artifacts: list[ReviewArtifact]
    settings: ChannelSettings

class ThreadState(BaseModel):
    """Thread-level working state (the working tree)"""
    thread_ts: str
    channel_id: str
    draft: Optional[WorkItemDraft]
    pending_questions: list[Question]
    step_count: int
    phase: Phase
```

**Benefits:**
- Clear ownership: thread proposes, channel decides
- Easier to reason about state transitions
- Natural model for "commit" = transfer from thread to channel

---

## Summary: What Changes

### Code Changes
1. New intents: `OPS_DEBUG`, `EXPLAIN`, `CHANGE_REQUEST`
2. New intent router branches
3. New flows: `ops_debug_flow`, `explain_flow`, `change_request_flow`
4. New table: `review_artifacts` + `artifact_links`
5. Rename: `ticket_flow` → `workitem_flow` (optional, may be disruptive)
6. State separation: `ChannelState` vs `ThreadState` (refactor)
7. Dedupe order: channel-first, then Jira

### Documentation Changes
1. Rewrite system identity (remove Jira-centricity)
2. Add Git Model section
3. Add Commit Semantics section
4. Rename Ticket Flow → WorkItem Flow
5. Update dedupe description

### Database Changes
1. `review_artifacts` table
2. `artifact_links` table
3. Possibly `commits` table (if not already explicit)

---

## Decisions Made

| Question | Decision |
|----------|----------|
| OPS_DEBUG vs EXPLAIN | Single `OPS` intent with `subtype: DEBUG \| EXPLAIN` |
| TICKET → WORKITEM_CREATE | Yes, dual-stack migration with backward compat |
| Scope | All 5 sub-phases in v1.2 |

## Open Questions (Remaining)

1. **Commit table:** Do we need explicit `commits` table or is current WorkItem versioning sufficient?

2. **ReviewArtifact storage:** Separate table or JSON in existing table?
   - **Leaning:** Separate table for queryability + links

3. **Migration:** How to handle existing data during transition?
   - Intent history in logs: map on read
   - No DB migration needed for intent rename

---

## Execution Plan

### Phase 25.1: Documentation Update
**Focus:** Conceptual rewrite, no code changes

- [ ] Rewrite system identity (remove Jira-centricity)
- [ ] Add Git Model section (Channel=repo, Thread=branch, Commit=truth)
- [ ] Add Commit Semantics section
- [ ] Rename Ticket Flow → WorkItem Flow throughout
- [ ] Update mantra: "Threads propose. Channels decide. Jira executes."

### Phase 25.2: Intent Rename + OPS Intent
**Focus:** Intent classification changes

- [ ] Add `OPS` intent with `subtype: DEBUG | EXPLAIN`
- [ ] Rename `TICKET` → `WORKITEM_CREATE` (dual-stack)
- [ ] Add `/maro explain` command
- [ ] Update intent classification prompt
- [ ] Add OPS flow (shared infra for both subtypes)
- [ ] Add OPS_DEBUG behavior (triage + retry)
- [ ] Add OPS_EXPLAIN behavior (policy trace)

### Phase 25.3: CHANGE_REQUEST Intent
**Focus:** Diff-based updates to existing truth

- [ ] Add `CHANGE_REQUEST` intent
- [ ] Build diff preview UI
- [ ] Implement target identification (workitems, jira keys, last commit)
- [ ] Apply updates to channel truth + Jira replica
- [ ] Require explicit approve for changes

### Phase 25.4: ReviewArtifact Persistence
**Focus:** Make reviews first-class persistent entities

- [ ] Create `review_artifacts` table
- [ ] Create `artifact_links` table
- [ ] Store reviews on approval
- [ ] Link artifacts to commits/workitems
- [ ] Add "turn into ticket" with artifact link
- [ ] Show artifact history in channel context

### Phase 25.5: State Separation + Dedupe Reorder
**Focus:** Architecture cleanup

- [ ] Extract `ChannelState` model
- [ ] Extract `ThreadState` model
- [ ] Refactor AgentState to use separated models
- [ ] Dedupe order: channel registry first, then Jira
- [ ] Update confidence scoring for local matches

---

## Dependencies

```
25.1 (docs) ─────────────────────────────────────┐
                                                 │
25.2 (OPS + rename) ──────────────────┐          │
                                      │          │
25.3 (CHANGE_REQUEST) ────────────────┼──→ 25.5 (state + dedupe)
                                      │
25.4 (ReviewArtifact) ────────────────┘
```

- 25.1 can run in parallel with 25.2-25.4
- 25.5 depends on 25.2-25.4 (needs new intents and artifacts)

---

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| 25.1 | Low | Docs only |
| 25.2 | Medium | Dual-stack prevents breaking changes |
| 25.3 | Medium | New flow, but isolated |
| 25.4 | Medium | New tables, additive |
| 25.5 | High | State refactor touches core | Thorough testing, feature flag |

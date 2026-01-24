# Phase 35: Multi-Intent Task Orchestration - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<vision>
## How This Should Work

When a user writes "create stories, check duplicates, and advise on architecture" — MARO doesn't pick one intent and ignore the rest. It parses the message into a **TaskPlan** — a list of tasks with priorities, dependencies, and safety classifications.

**The feeling:** Like talking to a mature PM/operator who says:

```
Got it. I see 3 actions:
1. Create list of Epics from Decisions
2. Check duplicates in Jira
3. Provide architecture recommendations

Executing 1 and 2 now. For 3 — OK?
```

**UI experience:** One editable Status Card that updates in place:

```
🛠 MARO Plan #P-184 — BUILD (3 tasks)

1) ✅ OPERATE: Jira duplicate check
2) ⏳ BUILD: Generate stories under SCRUM-166 (3/12)
3) ⏸ DECIDE: Create in Jira (waiting for approval)

Controls:
[Cancel plan]   [Pause]   [Details]
Task controls:
(2) [Cancel task]  (3) [Approve] [Reject]
```

This is "reliable and calm operator" — not a chatbot that says "I don't understand".

</vision>

<essential>
## What Must Be Nailed

### 1. Atomicity: TaskPlan as Transaction

TaskPlan is not "do everything sequentially". It's a pipeline where each step either:
- **completes**
- **blocks** and requires user input
- **cancels**

**TaskStatus = PENDING | RUNNING | BLOCKED | DONE | CANCELED**

If a task blocks (e.g., Jira write needs approval), everything that depends on it is also BLOCKED.

TaskPlan persists in state (checkpointer) — progress is never lost.

### 2. Task Ownership: Each Task Has a Target

Every task must be bound to an object:
- `task.target = {channel | thread | decision_id | workitem_id | jira_key}`

If target is not determined → first do a "Context Binding task" to resolve it.

This directly solves "bot doesn't know where to apply the action".

### 3. Two-Stage Extraction (Determinism)

LLM must not fantasize tasks. Two-stage classification:
- **Stage 1:** Cheap classify (modes + rough tasks)
- **Stage 2:** For each task — extract params only if needed (parent key, issue types, etc.)

Executor NEVER runs a task with missing required params — it sets status to BLOCKED and asks.

### 4. Safety Classification

**Auto-execute (safe):**
- Analysis/plan/preview
- Duplicate search
- History reading
- Draft collection

**Requires confirmation (dangerous):**
- Jira create/update
- Deprecate decision
- Mass changes

### 5. History Rule

> History is used only to determine object context (anchor) and current mode,
> but new tasks are created only from the trigger message (or explicit /command).

Otherwise bot starts "inventing work for itself".

</essential>

<specifics>
## Specific Ideas

### Status Card UI (Single Editable Message)

One TaskPlan = one control message that updates via `chat.update`, never republished.

**Where to show:**
- Status Card → in thread (don't spam channel)
- "Commit-like" events → short record to channel

Channel gets:
```
✅ Created 12 stories under SCRUM-166.
📌 Decision DEC-41 updated to v4 (affects 8 issues).
```

Thread gets the progress, controls, cancellation.

### Cancel/Stop Variants

**Cancel Task (soft stop):**
- `task.status = CANCELED`
- Executor stops executing it
- Dependent tasks → BLOCKED or CANCELED (by policy)

**Cancel Plan (hard stop):**
- All RUNNING/PENDING → CANCELED
- Status card freezes as "Canceled by @user"

**Pause/Resume:**
- Pause = stop scheduling next steps
- Current running step reaches safe checkpoint

### Throttling

Slack hates 20 updates/sec. Rule:
- Update UI max once per 1-2 seconds
- OR on significant events: task start/finish, blocked, error, user input needed

Progress "3/12" updates:
- Every N items, OR
- Every few seconds

### Button Idempotency (Version Binding)

Every button bound to:
- `plan_id`
- `task_id`
- `task_version` (or `plan_version`)

Double-click protection:
- If task already DONE → "already done"
- If task already CANCELED → "already canceled"
- If version mismatch → "stale action, refresh card" + update UI

### Data Model

```
TaskPlan {
  plan_id
  anchor: channel|thread|decision_id|jira_key
  tasks: [Task...]
  status
  created_by
  ui_message_ts   # message we update
  version
}

Task {
  task_id
  mode
  title
  status
  progress: {current, total} optional
  requires_user_input
  side_effects
  depends_on
  last_error
}
```

### LangGraph Integration

LangGraph remains the brain:
- Graph nodes → return "events"
- Event handler → updates TaskPlan state
- UI renderer → renders Status Card
- UI updater → does throttled `chat.update`

</specifics>

<notes>
## Additional Context

### Design Options Analyzed

1. **Single-winner + follow-up** — Simple but frustrates users ("I asked for everything")
2. **Multi-label, execute one** — Better understanding, still doesn't solve "do all"
3. **TaskPlan (To-Do plan)** ✅ RECOMMENDED — Full orchestration pipeline
4. **Two-Lane (Chat vs Work)** — Clean separation but harder UI
5. **Multi-intent as object change** — Elegant for anchor-based threads

### Multi-intent Detection Signals

- LLM returns `intents=[...]`
- Low confidence on top-1
- Text contains "and/also/plus"

### Canonical UX Response

If more than one task, MARO always responds:
1. List of tasks (1-3 lines)
2. What it will do now
3. What requires confirmation

### Dependencies

- Phase 34: Attachment context available in task execution
- Phase 31: SuperMode classification (modes map to safety levels)
- Phase 33: Anchor context for object-centric multi-intents

</notes>

---

*Phase: 35-multi-intent-task-orchestration*
*Context gathered: 2026-01-24*

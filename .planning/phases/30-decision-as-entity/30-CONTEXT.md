# Phase 30: Decision as First-Class Entity - Context

**Gathered:** 2026-01-23
**Status:** Ready for planning

<vision>
## How This Should Work

Decision approval is like git commit. Jira update is its side-effect. You never commit without pushing in a single-repo system.

When a decision is approved, it immediately reflects in linked Jira tickets. Anything else creates temporal inconsistency — channel says one thing, Jira says another, nobody knows which is true. That's how systems rot.

**The core rule:** Decision approval = commit + immediate Jira update, with preflight as universal guardrail.

### Canonical Message Model

Each Decision has **one canonical message** in the channel — like HEAD in git. This message:
- Is pinned
- Has a Decision ID (DEC-41)
- Always reflects the current active version
- Never disappears — updated or marked deprecated

The channel is not a log of what happened. It's a representation of **what is true now**.

### Thread as Working Area

All discussion happens in the thread under the canonical message:
- Arguments
- Examples
- Doubts
- Wording changes

The decision message = the object. The thread = its working area.

### Update in Place

When a decision changes:
1. New version created in thread (preview)
2. After approve → canonical message is **edited** (not new message)
3. Same message "moves in time"

This makes the channel look like a **live state board**.

### Deprecation and Splits

If deprecated → canonical message marked (not deleted):
```
🧠 Decision DEC-41 (ARCH)
Status: DEPRECATED
Replaced by: DEC-57

[This decision is no longer active]
```

If split into multiple → old decision shows what it became:
```
This decision was split into:
• DEC-62: …
• DEC-63: …
```

It becomes a historical node with traceability.

### Why Not New Messages Each Time?

If every update creates a new message:
- Channel gets cluttered
- "Where is the truth now?" becomes impossible
- Visual chaos

The goal is the opposite: **channel = live model of project reality**.

</vision>

<essential>
## What Must Be Nailed

All three pillars are equally critical — interconnected, can't compromise on any:

1. **Decision → Jira projection integrity**
   - Deterministic mapping (Decision type → known Jira field)
   - Managed sections only ("Decisions managed by MARO")
   - Never rewrite hand-written content above/below

2. **Preflight + conflict handling**
   - Every decision → Jira update goes through Preflight
   - No exceptions — decisions don't get "privileges"
   - Conflicts are detected and resolved explicitly
   - Partial failure tolerance — one conflict doesn't block others

3. **Visibility and audit trail**
   - Every decision change visible in channel
   - Preview before approval shows what will change
   - Commit log entries after updates
   - Canonical message always shows current truth

</essential>

<specifics>
## Specific Ideas

### Four Visual States (matching psychological weight)

**1. Draft/Discussion mode → Compact inline card**
```
🧠 Proposed decision:
Dates stored as Unix timestamps
[Edit] [Approve] [Discard]
```
Click expands to show full details. Keeps conversation flowing.

**2. Approval moment → Full decision block**
```
━━━━━━━━━━━━━━━━━━━━━━
🧠 Decision DEC-41 (ARCH) — Ready for approval

Title:
Dates stored as Unix timestamps

Description:
All backend services will exchange dates in Unix timestamp format...

Will update Jira:
• SCRUM-153
• SCRUM-158

Version: v1
Status: PROPOSED
━━━━━━━━━━━━━━━━━━━━━━

[Approve decision]   [Edit]   [Cancel]
```
Must feel heavy. This is the "are you sure?" moment.

**3. Approved → Compact but authoritative**
```
🧠 DEC-41 v1 (ARCH) — Approved
Dates stored as Unix timestamps
Applies to: SCRUM-153, SCRUM-158
[Change] [Deprecate] [Show history]
```
No longer conversational. It's infrastructure.

**4. Commit log → Ultra compact**
```
🧠 DEC-41 v1
+ Architecture: Unix timestamps
Affects: SCRUM-153, SCRUM-158
by @boris
```
Pure signal. No fluff.

### Versioning Flow

Step 1: Preview + approve in thread
```
🧠 Decision DEC-41 update (v4)

Diff:
- Format: Unix timestamp → ISO 8601 UTC

Will update 8 linked tickets:
• SCRUM-153, SCRUM-157, SCRUM-158, ...

[Approve update] [Edit] [Cancel]
```

Step 2: Commit log entry to channel (visibility)
```
🧠 DEC-41 updated to v4 (Approved by @boris)

Affects 8 Jira issues:
SCRUM-153, SCRUM-157, SCRUM-158 (+5)

Next: applying updates to Jira (preflight checks enabled).
```

Step 3: Apply updates atomically with partial tolerance

Step 4: Final report
```
✅ Decision projection complete

Updated:
• SCRUM-153
• SCRUM-157
• SCRUM-158

⚠️ Conflicts (needs attention):
• SCRUM-160 — description changed externally
  [Resolve] [Skip]
```

### Managed Sections in Jira

MARO writes only to its own block:
```
## Decisions (managed by MARO)
• DEC-41 v4 – ISO 8601 UTC dates
...
```

Never rewrites hand-written content. This drastically reduces real conflicts.

### Deterministic Mapping

| Decision Type | Jira Projection |
|---------------|-----------------|
| ARCH | Description → Architecture section |
| SCOPE | Description → Scope section |
| CONSTRAINT | Description → Constraints section |
| PRIORITY | Priority field / Labels |
| STRUCTURE | Parent/Link relations |
| PROCESS | Labels / Custom field |

No free-form LLM guessing where to write.

</specifics>

<notes>
## Additional Context

### Mental Models

- **idea → proposal → law → record** — same object, four visual identities
- **Compact cards = thinking, Full blocks = committing, Compact references = law, Commit log = history**
- **Channel as UI for decision database** — not a bot that writes messages, a system that turns channels into live project models

### Why Automatic Projection (not explicit sync)?

Explicit sync creates limbo:
- Approved but not applied
- True but not reflected
- Guaranteed drift

This breaks "communication is source of truth" principle.

### Why Not Hybrid (auto for simple, explicit for structural)?

"Structural vs simple" becomes fuzzy rule that humans and LLMs disagree on.
Deterministic behavior is required.
Structural safety belongs in Preflight, not workflow branching.

### Blast Radius Policy (optional)

If linked tickets > N (e.g., 10) → require additional "Apply to all" confirmation.
But still one confirmation, not N.

### Formal Rule Summary

- Decision always has:
  - One canonical message in channel (pinned)
  - One discussion thread under it
- Any change to decision:
  - Happens through thread
  - After approve → updates canonical message
  - Synchronizes to Jira
- Old versions don't appear as separate messages — exist only in version history

</notes>

---

*Phase: 30-decision-as-entity*
*Context gathered: 2026-01-23*

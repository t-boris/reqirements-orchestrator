# Phase 33: Anchor Message Architecture - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<vision>
## How This Should Work

Every message that creates an object of reality (Decision, Jira issue, Epic, Change) becomes an **anchor** — not just a notification, but the UI representation of that entity in the channel.

**The Anchor Pattern:**
```
🧠 Decision DEC-41 approved
```
This is no longer a log entry. It's a **card** — the visual object for DEC-41. The thread under it is the working space for that specific decision.

Same with Jira:
```
✅ SCRUM-166 created
```
This is the WorkItem's **card** in the channel. Thread = discussion of that WorkItem.

**The Shift:**

| Current (Thread-Centric) | Target (Object-Centric) |
|--------------------------|-------------------------|
| Thread exists → discussion → tickets emerge | Object created → canonical message → thread = lifecycle |
| Thread is primary | Anchor message is primary |
| Thread binding is optional | Thread binding is mandatory object reference |
| Commands require explicit ID | Commands inherit ID from anchor |

**The Git Parallel:**
```
Channel = Repository
Canonical Message = Object HEAD
Thread = Working Tree for that object
Registry = Database of objects
Jira = Projection
```

When someone opens a thread a week later, they see the anchor message and immediately understand: "We're discussing THIS object."

</vision>

<essential>
## What Must Be Nailed

All four rules work together as one system:

1. **A1: Anchor = Object**
   - Any "created/approved/updated" message is an anchor message
   - It's not a notification — it's the object's visual representation

2. **A2: Anchor Identity**
   - Each anchor has `object_id` (DEC-41, SCRUM-166) and `object_type` (Decision, WorkItem)
   - This is mandatory, not optional metadata

3. **A3: Context Inheritance**
   - Messages in thread automatically inherit `object_id` as context
   - No need to re-parse or re-extract the reference

4. **A4: Implicit Commands**
   - Commands in thread default to the anchor's object:
     - "change this"
     - "update"
     - "add story"
     - "deprecate"
   - Without repeating the ID

**The outcome:** Thread exists not for conversation, but for managing a specific object of reality.

</essential>

<specifics>
## Specific Ideas

**Thread Binding becomes mandatory, not optional:**
- Every anchor message creates a thread binding entry
- Thread binding stores: `object_id`, `object_type`, `channel_id`, `thread_ts`
- When processing messages in thread, the binding is resolved first

**Localized Context:**
- When user enters thread, they should immediately see what object is being managed
- The anchor message is the "title" of the working tree

**Commands without ID:**
- "update the description" → knows it's updating the anchor's object
- "add a story" → knows the parent is the anchor's object
- "deprecate" → knows what to deprecate

**Consistency across object types:**
- Decisions, WorkItems, Drafts — all follow same anchor pattern
- Same binding structure, same command resolution

</specifics>

<notes>
## Additional Context

This is the transition from "bot in a channel" to "state management interface."

**Why this matters:**
1. **Context is localized** — entering thread immediately tells you what you're discussing
2. **Object has one place** — not scattered across 12 places, but: registry + canonical message + thread
3. **Thread is working zone** — not archive, but active lifecycle management
4. **Solves "lost context"** — a week later, thread still clearly shows its purpose

**Quote from vision:**
> "Thread exists not for conversation. Thread exists for managing a specific object of reality."

**What this enables:**
When implemented, MARO stops being "a bot in the channel" and becomes "an interface to a living project management system."

</notes>

---

*Phase: 33-anchor-message-architecture*
*Context gathered: 2026-01-24*

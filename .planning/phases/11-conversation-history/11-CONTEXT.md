# Phase 11: Conversation History - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

MARO transforms from a "smart button" into a conversation participant. The core philosophy:

> "Я не был вызван, я просто сейчас заговорил вслух. Но я уже слушал разговор."
> ("I wasn't called, I just spoke out loud. But I was already listening to the conversation.")

When someone says "@MARO what do you think?" — MARO should already know what they're discussing. It shouldn't feel like summoning a stranger who needs to be briefed. It should feel like asking a colleague who was sitting in the room the whole time.

**Three channel modes:**

| Mode | Memory | Speech |
|------|--------|--------|
| **Disabled** | ❌ | On mention only, with on-demand history fetch |
| **Enabled** (Listening) | ✅ | Silent — only responds when called |
| **Engaged** (Temporary) | ✅ | Actively responding in thread |

**The key insight:** "Always listening" ≠ "always talking". Like a human in a meeting who hears everything but only speaks when asked.

**Opt-in model:**
- `/maro enable` — start listening in this channel
- `/maro disable` — stop listening
- `/maro status` — show listening state, last summary, linked Jira

When enabled, MARO posts a one-time banner:
> "MARO is now listening in this channel to maintain context. It won't reply unless mentioned or commanded."

**Non-opt-in channels still work:**
When MARO is mentioned in a disabled channel, it fetches recent history on-demand (last N messages + thread). This solves the "mid-conversation summon" problem without requiring always-on listening.

</vision>

<essential>
## What Must Be Nailed

- **Context restoration on @mention** — MARO must understand what's being discussed before responding, whether channel is enabled or not
- **Silent listening in enabled channels** — continuous context building without interrupting conversations
- **Two-layer context** — raw messages (bounded, 10-30) + narrative summary (1-2 paragraphs)
- **Thread-aware** — full thread history when mentioned inside a thread, linked to Epic if bound

</essential>

<specifics>
## Specific Ideas

**AgentState extension:**
```python
conversation_context: {
    messages: [...],          # raw Slack messages (bounded)
    summary: "...",           # compressed narrative
    last_updated_at: ...
}
```

**Message bounds:**
- Channel: 10-30 messages
- Thread: full history (typically compact)

**Summary example:**
> "Team is discussing scheduled notifications. Main questions: should scheduling be per user timezone, and should edits allow content change. Backend approach: DB table + worker. No final decisions yet."

**Behavior table:**

| Scenario | What MARO does |
|----------|----------------|
| @mentioned | Fetches history → responds in context |
| Not mentioned (enabled) | Listens → builds summary silently |
| "What do you think?" | Already knows — no briefing needed |
| Mid-thread entry | Fetches full thread + Epic context |

</specifics>

<notes>
## Additional Context

This phase is philosophically important: it's what makes MARO feel like a team member instead of a tool.

**Before Phase 11:** MARO is a smart button — you push it, it responds, it forgets.
**After Phase 11:** MARO is a conversation participant — it listens, remembers, and speaks only when asked.

The opt-in model provides:
- **Consent & clarity** — everyone knows the bot is listening
- **Cost control** — only summarize where it matters
- **Determinism** — no weird "half-listening" states

</notes>

---

*Phase: 11-conversation-history*
*Context gathered: 2026-01-14*

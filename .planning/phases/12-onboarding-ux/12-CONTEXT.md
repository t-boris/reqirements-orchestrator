# Phase 12: Onboarding UX - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

MARO's onboarding personality: **Quiet. Observant. Helpful only when needed.**

Like a senior engineer who doesn't explain their job on entry, but when you pause and look uncertain, says: "Want me to help you turn that into a ticket?"

**Core principle:** Teach by doing, not by lecturing. No mandatory walkthroughs. No forced "hello, here is everything I can do." MARO stays quiet until:
- User hesitates
- User gives an unclear message
- User asks something outside its scope
- User triggers a workflow that needs structure

Then it gives a small, precise nudge.

### Contextual Hints (Primary Model)

**User says "Hey":**
> "Hi. I help turn discussions into Jira tickets. Tell me about a feature, bug, or change you want to work on."

**User says "We should improve notifications":**
> "Do you want to create a Jira ticket for that, or just discuss it for now?"

**User says "What do you think?":**
> "I can review this as requirements, architecture, or security. Which perspective do you want?"
> [PM] [Architect] [Security]

**User creates confusion:**
> "Quick tip: you can say things like 'Create a Jira Story for…' or 'Draft requirements for…'"

One sentence. Not a manual.

### Welcome Message (Pinned Quick-Reference)

When MARO is added to a channel, it posts once and pins:

```
MARO is active in this channel

I help turn discussions into Jira tickets and keep context in sync.

Try:
@MARO Create a Jira story for...
@MARO What do you think about this?
@MARO Review this as security

Commands:
• /maro status – show channel ↔ Jira links
• /maro help – quick help
• /persona pm | architect | security

I stay silent unless you mention me.
```

This becomes the "installation instructions" for the room — a sign on the wall, not a greeting.

### /maro help (Interactive)

Short, structured, action-oriented with buttons that show example conversations:

```
What MARO can do:
- Draft Jira tickets from discussion
- Propose architecture + risks
- Detect duplicates
- Sync with Jira
- Track channel context

[Create Ticket] [Review] [Settings]
```

Clicking a button shows a sample exchange demonstrating that feature.

</vision>

<essential>
## What Must Be Nailed

- **The hesitation nudge** — When user pauses or seems uncertain, the hint that opens the door
- **The confusion recovery** — When user says something unclear, guiding them back on track
- **The /help structure** — Making the help command actually useful and short
- **All equally important** — These three work together as one experience

</essential>

<specifics>
## Specific Ideas

### Hesitation Detection
- Use LLM classification to detect if message seems like user needs guidance
- Not just pattern matching — understand intent
- Triggers: vague messages, questions without context, first message uncertainty

### Phrase Examples (Use These)
- "Hi. I help turn discussions into Jira tickets."
- "Do you want to create a Jira ticket for that, or just discuss it for now?"
- "I can review this as requirements, architecture, or security. Which perspective?"
- "Quick tip: you can say 'Create a Jira Story for…'"

### Persona-Aware Hints
- When context is ambiguous, suggest PM/Architect/Security perspectives
- Use buttons: [PM] [Architect] [Security]
- Let user choose, don't assume

### Welcome Message Behavior
- Post to channel (not thread) — channel is workspace, thread is conversation
- Pin the message immediately
- Never repeat — one-time installation
- No "hello" greeting — just information

### /help Interactive Buttons
- Click button → show example conversation
- Not a link to docs, not a guided wizard
- Just: "Here's what it looks like when you use this"

</specifics>

<notes>
## Additional Context

**Why not guided walkthrough:**
- Channels are shared spaces
- Onboarding spam annoys everyone
- People hate bots that introduce themselves loudly

**Why not silent join:**
- Users don't know if bot is alive
- They'll write "@MARO hello?" just to check
- Bad UX

**Why not just help command:**
- Nobody reads help
- Discovery must be in the moment of confusion

**Thread vs Channel:**
- Threads are conversations — keep clean
- Channels are workspaces — put infrastructure here
- Onboarding, Jira links, status, rules, context → channel level

**MARO's role at this point:**
- Not a "greeter"
- An "installation"
- Leaves instructions for operation

</notes>

---

*Phase: 12-onboarding-ux*
*Context gathered: 2026-01-15*

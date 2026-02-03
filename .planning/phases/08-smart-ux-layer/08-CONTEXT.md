# Phase 8: Smart UX Layer - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<vision>
## How This Should Work

The bot should feel like talking to a smart colleague who happens to have a clipboard with options. Natural conversation that auto-resolves to actions — the user says things naturally and the bot handles all the lifecycle/entity/process complexity silently. No domain jargon ever surfaces.

When the bot needs input from the user, it smartly detects whether buttons make sense. If it can infer likely answers (yes/no, pick between options, confirm an action), it shows 2-4 buttons plus a "Something else" escape hatch. If the question is genuinely open-ended, it stays as text. This should feel natural, not like clicking through a form.

The conversation flow is intelligent — the bot reads the room. It knows when to ask, when to act, when to suggest. It doesn't ask users to repeat context that's already in the thread. It doesn't expose internal states or ask users to navigate concepts like "entity lifecycle" or "process stages."

Full debug toolkit available via `/maro inspect` — event timeline, entity state inspector, task tree viewer, intent audit log. Every classification is persisted (message → intent → confidence → mode → action) so you can always answer "why did the bot do that?"

</vision>

<essential>
## What Must Be Nailed

- **Smart conversation flow** — Bot reads the room. Knows when to ask, when to act, when to suggest. Feels intelligent, not robotic. This is THE core deliverable.
- **Button-based choices** — When the LLM has options to offer, they become Slack buttons. Smart detection: buttons for choices, free text for open-ended. Every button set includes a "Something else" option.
- **Hidden complexity** — User never sees lifecycle states, entity types, process stages. Everything is natural language. The bot translates between human intent and domain operations silently.

</essential>

<specifics>
## Specific Ideas

- LLM responses should be parsed for questions/options and auto-converted to Slack button blocks
- Intent audit log: persist every message → intent → confidence → mode → action chain for debugging
- Deterministic post-filters: entity references in MODIFY must exist, otherwise downgrade to CONVERSE (prevent hallucination)
- `/maro inspect` command: event timeline viewer, entity state inspector, task tree viewer
- Source: docs/improvement-1.rtf review identified UX friction risk — "user just wanted to write a story, why is the bot holding a philosophy congress"
- Smart defaults: bot auto-resolves obvious actions without asking for confirmation when confidence is high

</specifics>

<notes>
## Additional Context

Improvement review (docs/improvement-1.rtf) identified 4 state machines running in parallel (entity lifecycle, task lifecycle, process stages, workspace focus) — risk of "Minotaur's labyrinth." This phase addresses the UX side of that complexity by hiding it entirely from users.

The review praised the core design principle "Threads propose. Channels decide. Jira executes." — this phase should reinforce that simplicity in the UX layer.

Production testing revealed multiple UX gaps: bot asking questions as free-form text when buttons would be better, bot not using thread context, bot exposing raw message content instead of extracting meaning. Several of these were hot-fixed but the systematic solution belongs in this phase.

</notes>

---

*Phase: 08-smart-ux-layer*
*Context gathered: 2026-02-03*

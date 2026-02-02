# Phase 3: Intent & Modes - Context

**Gathered:** 2026-02-02
**Status:** Ready for research

<vision>
## How This Should Work

Messages flow through a multi-stage classification pipeline that's both fast and safe:

1. **PreGates** catch obvious cases deterministically — slash commands, button clicks, explicit approvals — no LLM needed
2. **LLM Router** classifies everything else into one of 4 SuperModes (CREATE, MODIFY, RECORD, CONVERSE)
3. **Safety Evaluator** sits between classification and action — checks lifecycle state, approvals, permissions, runs dry-run validation
4. **SuperMode handlers** execute the classified intent

The system should fail safe: when uncertain, default to CONVERSE mode with no side-effects. Never do something irreversible when the LLM isn't confident.

LLM output must be reliable JSON — auto-repair on first failure, regenerate on invalid output. The router is wrapped in a validation layer that catches and fixes malformed responses.

</vision>

<essential>
## What Must Be Nailed

- **Safe defaults** — Confidence threshold triggers CONVERSE fallback, no side-effects on ambiguity, CREATE/MODIFY require confirmation
- **Deterministic pre-routing** — PreGates must catch commands/approvals/obvious cases before hitting LLM (saves latency, ensures predictability)
- **JSON reliability** — LLM output validation with auto-repair, retry on invalid, structured output enforcement

All three are equally important — they work together to make the router both fast and safe.

</essential>

<specifics>
## Specific Ideas

- **Provider-agnostic LLM abstraction from the start** — Clean abstraction layer supporting multiple LLM providers (Gemini, OpenAI, Anthropic, etc.), not just Gemini with swap-later design
- **Update architecture documentation** — Document how intent classification works in `/docs/architecture/*.md` (following the pattern from Phase 2 where we added Slack Integration Layer to BOT_DESIGN.md)
- **Follow update-1.md enhancements** — Incorporate the Router & LLM Guardrails and Intent → Action Safety Layer proposals from the architecture improvements document

</specifics>

<notes>
## Additional Context

From update-1.md (architecture improvements proposal):

**Section 3: Router и LLM Guardrails**
- 3.1 JSON validation + repair (strict schema, auto-fix 1 attempt, regenerate on invalid)
- 3.2 Confidence threshold: confidence < threshold → CONVERSE mode
- 3.3 Safe defaults: no side-effects on ambiguity, no CREATE/MODIFY without confirmation

**Section 4: Intent → Action Safety Layer**
- Router → Safety Evaluator → Process/Action
- Evaluator checks: lifecycle state, approvals, object locks, permissions, dry-run result

These enhancements strengthen the base spec without changing the core 2-stage classification concept.

</notes>

---

*Phase: 03-intent-modes*
*Context gathered: 2026-02-02*

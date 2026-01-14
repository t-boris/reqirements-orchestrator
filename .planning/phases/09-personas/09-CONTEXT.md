# Phase 9: Personas - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

Personas are **operational modes**, not "different chatbots." The bot stays the same entity — personas change what it emphasizes, which checks it runs, what questions it asks, and how it formats output.

**The golden rule:** Personas should not change the truth. If persona switching changes factual conclusions ("Security says X, PM says Y"), users will feel like the bot is roleplaying.

**Model: Persona = Policy + Lens**

Think of a persona as:
1. **Prompt overlay** — tone + priorities (small, not giant prompts)
2. **Validation policy** — extra checks to run
3. **Default tool preference** — what it asks for, what it previews

Same underlying state, different "spotlight."

**Example personas:**
- **PM** — checks: scope, acceptance criteria, risks, dependencies, timeline
- **Security** — checks: data retention, access scope, least privilege, auditability
- **Architect** — checks: boundaries, failure modes, idempotency, scaling, observability

</vision>

<essential>
## What Must Be Nailed

- **Small overlays, not giant prompts** — persona definitions as config objects (name, goals, must_check validators, questions_style, output_format, risk_tolerance). Base system prompt + tiny overlay + context slice.

- **Deterministic switching** — two-stage approach:
  1. Detection proposes a persona (explicit trigger, heuristic keywords, or high-confidence LLM)
  2. Decision node confirms based on session phase, user intent, confidence threshold

- **Visible persona changes** — announce switching ("Switching to Security review mode") or show badge in preview card. No silent changes that confuse users.

- **Persona-specific validators in Validation node** — this is where personas actually add value. Each persona adds requirements but does NOT rewrite existing facts.

- **Persona locking per thread** — prevent oscillation. Once set (or locked), persona stays stable for the thread.

</essential>

<specifics>
## Specific Ideas

### Persona Definitions (09-01)
Store each persona as a config object:
- `name`
- `goals` (3-5 bullets)
- `must_check` (list of validators to run)
- `questions_style` (short description)
- `output_format` (e.g., "bullet list + DoD section")
- `risk_tolerance` (strict/moderate)

### Topic Detection (09-02)
Detection methods in order of preference:
1. **Explicit triggers (best):** `@security`, `@architect`, `/persona security`
2. **Heuristic keywords (good):** "threat", "permission", "OAuth", "PII" → Security; "scaling", "queue", "idempotency" → Architect
3. **LLM classifier (fine):** only with logging and high confidence threshold

**Topic drift solution:** Allow multi-persona checks without switching voice. Stay PM voice but run Security validator as a silent check that raises flags.

### Integration Points (09-03)
- **Extraction node:** minor influence (what fields to prioritize)
- **Validation node:** major influence (persona-specific validators)
- **Decision node:** moderate influence (ask security questions vs show preview)

### Governance + UX (09-04)
- Explicit commands: `/persona`, `/persona auto|off`
- Logging: why persona switched, confidence, what validators ran
- "Lock persona" per thread (prevents oscillation)
- AgentState stores: `persona`, `persona_lock`, `persona_reason`

</specifics>

<notes>
## Additional Context

### Pitfalls to Avoid
- Giant narrative prompts (inflate tokens, reduce determinism)
- Silent persona changes (confuses users)
- Persona oscillation within a thread
- Changing factual conclusions based on persona (feels like roleplaying)

### Definition of Done
- Personas are small overlays (not giant prompts)
- Switching is deterministic: explicit trigger or high-confidence detection
- Persona changes are visible (badge/message)
- Persona affects validation via modular checks
- AgentState stores persona, persona_lock, and persona_reason
- Tests: same input + same state → same persona decision; no oscillation; Security persona always runs its required validators

### Suggested Plan Breakdown (4 plans instead of 3)
- 09-01: Persona definitions and config model
- 09-02: Topic detection + switching logic
- 09-03: Persona integration with extraction/validation nodes
- 09-04: Persona governance + UX (commands, locking, logging)

</notes>

---

*Phase: 09-personas*
*Context gathered: 2026-01-14*

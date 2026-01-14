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

**Three personas from the start:**
- **PM** — checks: scope, acceptance criteria, risks, dependencies, timeline
- **Security** — checks: data retention, access scope, least privilege, auditability
- **Architect** — checks: boundaries, failure modes, idempotency, scaling, observability

**Default behavior:** PM is always the default. Only switch on explicit trigger or high-confidence detection.

</vision>

<essential>
## What Must Be Nailed

- **Small overlays, not giant prompts** — persona definitions as config objects (name, goals, must_check validators, questions_style, output_format, risk_tolerance). Base system prompt + tiny overlay + context slice.

- **PM as default, deterministic switching** — Start as PM, switch only on:
  - Explicit trigger (@security, @architect, /persona [name])
  - High-confidence threshold-based detection

- **Threshold-based silent checks** — Validators run silently based on detection scores:
  - Security validator: high threshold (0.75) — security warnings are "loud"
  - Architect validator: medium threshold (0.60) — less disruptive
  - **Sensitive ops override:** Always run Security validator for: Jira writes, token/secret handling, user data, content storage — regardless of topic detection

- **Visible persona changes** — Subtle indicator (emoji prefix: 🛡️ Security:) rather than loud announcements. Keep bot feeling like a calm PM.

- **Auto-lock + unlock** — Once persona activates, it locks for the thread. Users can `/persona unlock` if needed. Prevents oscillation.

- **Validators warn, never block** — All validators surface issues but user decides. No authoritarian blocking.

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
**Threshold-based detection model:**
1. Detector produces signals (cheap heuristics + optional classifier):
   - `security_score`, `architect_score`
   - `reasons` (matched terms/features)

2. Decision node applies policy:
   - if score ≥ threshold → run validator silently
   - if score < threshold → skip
   - if action is high-risk → force security validator regardless of score

Detection methods in order of preference:
1. **Explicit triggers (best):** `@security`, `@architect`, `/persona security`
2. **Heuristic keywords (good):** "threat", "permission", "OAuth", "PII" → Security; "scaling", "queue", "idempotency" → Architect
3. **LLM classifier (fine):** only with logging and high confidence threshold

**Topic drift solution:** Allow multi-persona checks without switching voice. Stay PM voice but run Security/Architect validators as silent checks that raise flags.

### Validator Design (09-03)
**Pluggable validators** — Separate validator classes that can be composed per persona.

**Performance:** Rule-based checks first (cheap heuristics), LLM calls only when needed.

**Validator output format:**
- Each finding: ≤ 1 line
- Include ID for audit/debug (SEC-RET-001)
- Optional "Fix" hint

### Findings UX in Preview Card
**Hybrid approach:**

1. **Inline only for BLOCK findings:**
   - ⚠️ BLOCK: Missing authz model for /notifications endpoint
   - Place where it matters (under relevant section)
   - Max 2 inline ("+3 more blocking issues" if more)

2. **"Review Notes" section for WARN/INFO:**
   - At bottom of preview
   - Grouped by persona: Security (2), Architecture (1), PM (1)
   - Max 5 total with "Show more" button

3. **"Show review" action** — Button to see full findings in threaded message or modal

**If BLOCK findings exist:** Replace "Approve" with "Fix issues"

### Conflict Resolution
When validators find conflicting issues (Security vs Architect): **Flag for discussion** — Bot notes the conflict and suggests the team discuss. Don't try to resolve automatically.

### Persona Commands (09-04)
Full control interface:
- `/persona [name]` — Switch to persona (pm, security, architect)
- `/persona lock` — Lock current persona for thread
- `/persona unlock` — Allow persona switching again
- `/persona auto` — Enable auto-detection
- `/persona off` — Disable persona features
- `/persona status` — Show current persona, lock state, active validators
- `/persona list` — Show available personas

**@mention triggers work naturally:** @security in message activates Security persona for that thread.

### Integration Points
- **Extraction node:** minor influence (what fields to prioritize)
- **Validation node:** major influence (persona-specific validators)
- **Decision node:** moderate influence (ask security questions vs show preview)

### Testing Requirements
All three are critical:
1. **Determinism:** Same input + state = same persona decision, every time
2. **Validator coverage:** Each validator finds what it should find
3. **No oscillation:** Thread persona stays stable once set

</specifics>

<notes>
## Additional Context

### Pitfalls to Avoid
- Giant narrative prompts (inflate tokens, reduce determinism)
- Silent persona changes (confuses users)
- Persona oscillation within a thread
- Changing factual conclusions based on persona (feels like roleplaying)
- Keyword-triggered paranoia (too many false positives)
- Running all validators always (expensive and noisy)
- Drowning preview cards with validator output

### Sensitive Ops Override
Regardless of topic detection, always run Security validator when:
- About to create/update Jira via privileged creds
- Handling tokens/secrets
- Enabling "monitor all channel messages"
- Touching user data retention / exporting logs / storing content

These are guardrails, not persona features.

### Output Behavior for Silent Validators
When a silent validator runs:
- Don't change persona/voice
- Surface only actionable findings
- Cap findings (max 3)
- Attach confidence note ("Flagged because this touches auth scopes / PII")

### Definition of Done
- Personas are small overlays (not giant prompts)
- Switching is deterministic: explicit trigger or high-confidence detection
- Persona changes are visible (subtle indicator)
- Persona affects validation via modular checks
- AgentState stores persona, persona_lock, and persona_reason
- Tests: same input + same state → same persona decision; no oscillation; Security persona always runs its required validators

### Suggested Plan Breakdown (4 plans)
- 09-01: Persona definitions and config model
- 09-02: Topic detection + switching logic
- 09-03: Persona-specific validators + integration with nodes
- 09-04: Persona commands + UX (findings display, locking, logging)

</notes>

---

*Phase: 09-personas*
*Context gathered: 2026-01-14*

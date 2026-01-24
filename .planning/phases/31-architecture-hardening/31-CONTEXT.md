# Phase 31: Architecture Hardening — Context

## Vision

**Mantra:** "Feel like a product, not an OS kernel."

The bot has grown organically through 30 phases. It works, but the complexity is showing:
- 13 intents feel like kernel syscalls, not user modes
- Decisions project to Jira without explicit safety boundaries
- Canonical messages can fail and corrupt state
- The classifier does too much in one pass

This phase hardens the architecture for production without adding features.

## How It Should Work

### User Perception: 5 Modes, Not 13 Intents

Users should think in simple modes:
- **BUILD** — "I'm building something" (tickets, drafts, transforms)
- **OPERATE** — "I'm managing Jira" (commands, syncs, actions)
- **DECIDE** — "I'm recording a decision"
- **THINK** — "Help me think" (reviews, searches)
- **CHAT** — "Just talking"

Internally, fine-grained intents remain for routing. But docs, `/maro help`, and error messages speak in modes.

### Decision Projection: Hard Safety Rules

When decisions write to Jira descriptions:
1. **Only touch managed section** — Never modify user content outside `## Decisions (managed by MARO)`
2. **Fully reversible** — Removing managed section restores original
3. **Fail if unclear** — If boundaries can't be found, refuse to write

These are invariants, not guidelines. Code must enforce them.

### Slack is Presentation, Not Truth

If canonical message update fails:
- Decision state is still APPROVED in database
- Jira sync still proceeds
- Warning logged, retry queued
- User can always `/maro decision show` to see truth

Database is truth. Jira is projection. Slack is UI.

### Two-Stage Classification

Split the heavy classifier:
1. **Stage 1** — Quick: message → intent + confidence + super_mode
2. **Stage 2** — On-demand: message + intent → fields (persona, key, command_type)

Most messages (DISCUSSION, REVIEW) need only Stage 1.

## What's Essential

1. **Super-modes in IntentResult** — `super_mode` field, docs updated
2. **MANAGED_SECTION_ONLY invariant** — Hard rule with tests
3. **Slack failure tolerance** — Message failures don't block state
4. **Canonical message idempotency** — Version-checked, failure-safe

## What's Optional

- Two-stage classifier (evaluate complexity vs benefit)
- Draft lifecycle simplification (v2 consideration)
- Full sync semantics documentation

## Key Insight

The system is powerful but feels like configuring a kernel. Users shouldn't need to understand 13 intents, 6 lifecycle states, and 4 conflict types. They should feel like they're talking to a colleague who happens to know Jira very well.

---

*Created: 2026-01-23*
*Source: User feedback during /gsd:add-phase*

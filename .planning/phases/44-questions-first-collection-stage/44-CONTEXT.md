# Phase 44 Context: Questions-First Collection Stage

## Vision

**Smart triage** — Bot assesses what's missing from the thread context, asks targeted questions, then routes to the right mode (review/build/track/etc). No generic checklists, no interrogation.

## How It Works

User sends a request → Bot reads thread context → Identifies actual gaps → Asks targeted questions → Collects answers → Routes with complete context

### Question Characteristics

1. **Context-aware gaps** — Bot reads thread/channel context, identifies what's actually missing (not generic checklists)
2. **Mode-specific questions** — Different questions for review vs build vs track — each path needs different info
3. **Progressive depth** — Start shallow, go deeper only if answers reveal complexity

### Fast Path

If context is already complete (enough info to proceed), skip questions entirely. Don't slow down ready requests.

## Core Win

**No more "missing info" loops** — Bot collects everything upfront so there's no back-and-forth after routing. Once the request is routed to review/build/track, it has everything it needs.

## What's Essential

- Questions feel natural, not like an interrogation
- Buttons for every question (typing optional)
- Completeness gate before routing — don't proceed until you have what you need
- But also: don't over-ask — minimal friction to unblock next step

## Anti-Patterns to Avoid

- Generic 10-question checklist regardless of context
- Asking for info that's already in the thread
- Blocking on optional information
- Questions that don't affect the routing decision

## Open Questions (for planning)

- How does bot determine "complete enough" to route?
- What's the schema for tracking what's been collected?
- How does this integrate with existing Question Engine (Phase 37)?
- Does this replace or wrap the current intent detection?

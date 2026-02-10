# Phase 11: Architecture Advisor — Discussion Context

## Questions & Decisions

### 1. Mode Transition Design

**Q:** How do transitions between modes happen?

**A:** No explicit mode transitions. Each message is classified independently by the LLM intent router based on message text + thread context + existing entities. The thread context gives the LLM enough signal to understand conversation flow. For example:
- User discusses architecture → ARCHITECT
- User says "record that as an ADR" → CREATE
- User states a commitment inline → RECORD

### 2. ARCHITECT → ADR Bridge

**Q:** How should architectural recommendations become ADRs?

**A:** ARCHITECT mode conditionally offers a "Record as ADR" button when its response contains a concrete recommendation (not just exploratory analysis). The LLM decides whether the response is ADR-worthy based on whether it made a specific "use X over Y" recommendation vs. general exploration.

**Mechanism:** Clicking "Record as ADR" triggers the existing RECORD decision preview flow (same `confirm_record_decision` handler) but with content pre-filled from the ARCHITECT analysis. This reuses existing button handlers and decision lifecycle.

### 3. Enriched ADR Content

**Q:** Should ADRs from ARCHITECT include architecture-specific metadata?

**A:** Yes. Add optional fields to the existing `DecisionContent` model:
- `patterns_referenced: list[str] = []` — e.g., ["hexagonal", "event-sourcing"]
- `tradeoffs: list[str] = []` — e.g., ["Higher complexity but better isolation"]

This is backwards-compatible — existing decisions get empty lists for these fields.

### 4. Scope

**Q:** Include ADR bridge in Phase 11 or separate follow-up?

**A:** Include in Phase 11 as plan 11-02. Keeps it in the same milestone since it's directly related.

## Architecture Notes

- ARCHITECT is structurally identical to CONVERSE — single LLM call, no external API, no confirmation flow
- The key difference is the system prompt (architecture expert with pattern vocabulary and analysis framework)
- ADR bridge reuses existing `confirm_record_decision` action handler — no new button handlers needed
- `ArchitectResponse.recommend_adr: bool` field lets the LLM signal when a "Record as ADR" button should appear
- Pre-filled ADR data flows through the same JSON button value mechanism used by RECORD and CREATE modes

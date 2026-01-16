# Phase 20: Brain Refactor - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

MARO's brain needs a fundamental architecture shift. Currently, intent classification is overloaded — it handles both user intent (what they want) AND workflow events (button clicks, approvals, continuations). This creates a tangled mess where adding any new feature requires a new "intent type".

After Phase 20, the system should work like this:

1. **User sends message** → Intent router classifies as pure user intent: TICKET | REVIEW | DISCUSSION | META | AMBIGUOUS
2. **AMBIGUOUS triggers scope gate** → 2 buttons: "Review this" / "Create ticket"
3. **System checks pending_action** → If workflow is waiting for something (approval, scope choice, multi-ticket confirmation), route to that handler instead of intent router
4. **Resumable graph** → Interrupts don't restart from scratch. State knows where to continue.
5. **Multi-ticket flow** → "Create epic with 5 stories" shows preview, allows editing individual items, resumes after approval

The key insight: **intent is what user wants, not what system is doing**.

</vision>

<essential>
## What Must Be Nailed

1. **Separation of Intent and Workflow Events**
   - UserIntent: TICKET | REVIEW | DISCUSSION | META | AMBIGUOUS
   - WorkflowEvent: BUTTON_CLICK | SLASH_COMMAND | APPROVAL_RESPONSE
   - PendingAction: WAITING_APPROVAL | WAITING_SCOPE_CHOICE | WAITING_STORY_EDIT | etc.

2. **Remove "lean toward TICKET" bias**
   - AMBIGUOUS intent with scope gate (2 buttons)
   - User decides, bot doesn't guess

3. **Resumable graph**
   - pending_action in state tells where to continue
   - No more "every interrupt goes to START"

4. **Review lifecycle fixes**
   - REVIEW_COMPLETE patterns (thanks/ok/got it)
   - Patch mode by default (only diff, not full regeneration)
   - TTL/cooldown for review_context

5. **Decision approval flow**
   - Preview in thread → Edit → Post to channel
   - No more "post without confirmation"

6. **Multi-ticket support**
   - Epic + stories in one request
   - Preview all items
   - Edit individual stories
   - Resume after edits

7. **Context persistence**
   - context_summary (not raw)
   - salient_facts (constraints, decisions)
   - cursor/last_seen_ts

</essential>

<specifics>
## New State Fields

```python
class AgentState(TypedDict):
    # Existing fields...

    # NEW: Pure user intent (not workflow events)
    user_intent: Optional[UserIntent]  # TICKET | REVIEW | DISCUSSION | META | AMBIGUOUS
    intent_confidence: float  # 0.0 - 1.0

    # NEW: Workflow state (replaces overloaded intent)
    pending_action: Optional[PendingAction]  # What system is waiting for
    workflow_step: Optional[str]  # Current position in workflow

    # NEW: Multi-ticket state
    multi_ticket_state: Optional[MultiTicketState]  # Epic + stories being created

    # NEW: Persisted context
    context_summary: Optional[str]  # Compressed conversation summary
    salient_facts: list[str]  # Extracted constraints, decisions
```

## Key Architectural Changes

1. **Intent Router Simplification**
   - Remove: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION from IntentType
   - Add: AMBIGUOUS with scope gate
   - These become PendingAction values instead

2. **Graph Entry Point**
   - Check pending_action FIRST
   - If pending, route to continuation handler
   - If not, run intent classification

3. **Review Flow Rewrite**
   - Patch mode: only output changes + updated questions
   - Full synthesis: on "Show full architecture" button
   - REVIEW_COMPLETE detection (thanks/ok/got it)
   - Auto-freeze review_context after N messages without continuation signals

4. **Multi-Ticket Flow (NEW)**
   - User: "Create epic with user stories for authentication"
   - Bot: Extract epic + N stories
   - Bot: Show preview with all items
   - User: Edit story #3
   - Bot: Update story #3, show updated preview
   - User: Approve
   - Bot: Create epic, create stories as subtasks

## Test Cases That Must Work

1. "Review this architecture" → REVIEW (not TICKET)
2. "Create a ticket for login bug" → TICKET
3. "What do you think about microservices?" → REVIEW or DISCUSSION
4. "Thanks, looks good" after review → REVIEW_COMPLETE (freeze context)
5. "Now create a ticket for something unrelated" after review → TICKET (not continuation)
6. "Create epic with 5 stories for auth" → multi-ticket flow
7. User clicks "Approve" button → continues from pending_action, not intent classification

</specifics>

<analysis>
## Root Problems Being Fixed

From BRAIN-ANALYSIS.md:

| Problem | Current State | After Phase 20 |
|---------|--------------|----------------|
| Intent overload | IntentType = user intent + workflow events | Separated: UserIntent + PendingAction |
| TICKET bias | "If unclear, lean toward TICKET" | AMBIGUOUS + scope gate |
| Sticky continuation | REVIEW_CONTINUATION triggers on any related message | TTL + explicit REVIEW_COMPLETE |
| Expensive reviews | Full regeneration every answer | Patch mode default |
| Interrupt = endpoint | Every interrupt restarts graph | Resumable via pending_action |
| No multi-ticket | Single ticket per request | Epic + stories flow |
| Decision without preview | Post to channel immediately | Preview → Edit → Post |
| Context lost | conversation_context not persisted | context_summary + salient_facts |

## Scope Size

This is a **large** phase. Likely 8-12 plans across 4-5 waves:
- Wave 1: State refactoring (new fields, types)
- Wave 2: Intent router simplification + scope gate
- Wave 3: Review lifecycle fixes (patch mode, REVIEW_COMPLETE, TTL)
- Wave 4: Decision approval flow + resumable graph
- Wave 5: Multi-ticket flow

</analysis>

<notes>
## Dependencies

- BRAIN-ANALYSIS.md provides detailed current state analysis
- Builds on Phase 18 clean code (handlers already split)

## Risks

- Large refactor touching intent.py, state.py, graph.py, runner.py, handlers
- Many existing tests will need updates
- Breaking changes to flow logic

## Out of Scope

- External integrations (Confluence, GitHub)
- Voice/audio input
- Mobile app

## Core Principle

**Intent router should classify what user wants, not manage workflow state.**

The graph should be resumable. Pending actions should be explicit. Multi-ticket flows should be possible without hacking intent types.

</notes>

---

*Phase: 20-brain-refactor*
*Context gathered: 2026-01-15*

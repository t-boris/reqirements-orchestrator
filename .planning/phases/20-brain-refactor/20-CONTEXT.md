# Phase 20: Brain Refactor - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning
**Updated:** 2026-01-15 (added guardrails from review feedback)

<vision>
## How This Should Work

MARO's brain needs a fundamental architecture shift. Currently, intent classification is overloaded — it handles both user intent (what they want) AND workflow events (button clicks, approvals, continuations). This creates a tangled mess where adding any new feature requires a new "intent type".

After Phase 20, the system should work like this:

1. **WorkflowEvent first** → Button clicks, slash commands go directly to handlers (no intent classification)
2. **Check pending_action** → If workflow is waiting for something, route to continuation handler
3. **Intent classification** → Only for new messages: TICKET | REVIEW | DISCUSSION | META | AMBIGUOUS
4. **AMBIGUOUS triggers scope gate** → 3 buttons: "Review" / "Create ticket" / "Not now"
5. **Resumable graph** → Interrupts don't restart from scratch. State knows where to continue.
6. **Multi-ticket flow** → "Create epic with 5 stories" shows preview, allows editing, resumes after approval

**Event Routing Priority:**
```
WorkflowEvent (button/slash) → PendingAction → UserIntent
```

The key insight: **intent is what user wants, not what system is doing**.

</vision>

<essential>
## What Must Be Nailed

1. **Separation of Intent and Workflow Events**
   - UserIntent: TICKET | REVIEW | DISCUSSION | META | AMBIGUOUS
   - WorkflowEvent: BUTTON_CLICK | SLASH_COMMAND | APPROVAL_RESPONSE
   - PendingAction: WAITING_APPROVAL | WAITING_SCOPE_CHOICE | WAITING_STORY_EDIT | etc.

2. **Event-First Routing**
   - If event = button_click/slash_command → handler directly (no intent classifier)
   - Else if pending_action != None → continuation handler
   - Else → intent classifier

3. **Remove "lean toward TICKET" bias**
   - AMBIGUOUS intent with scope gate (3 buttons)
   - "Review" / "Create ticket" / "Not now (dismiss)"
   - "Not now" clears pending_action and stops cycle
   - User decides, bot doesn't guess

4. **Resumable graph**
   - pending_action in state tells where to continue
   - No more "every interrupt goes to START"
   - Resumable must work BEFORE review lifecycle fixes (dependency)

5. **Review lifecycle fixes**
   - REVIEW_COMPLETE patterns (thanks/ok/got it)
   - Patch mode by default (only diff, not full regeneration)
   - Full synthesis on "Show full architecture" button
   - TTL/cooldown for review_context
   - **Freeze semantics**: frozen review_context remains available for handoff but doesn't trigger continuation and doesn't affect next message's intent

6. **Decision approval flow**
   - Preview in thread → Edit → Post to channel
   - No more "post without confirmation"
   - **Source reference**: channel post must link to source thread + issue keys

7. **Multi-ticket support**
   - Epic + stories in one request
   - Preview all items
   - Edit individual stories
   - Resume after edits
   - **Safety latch**: >3 items requires explicit quantity confirmation ("Confirm create 7 items?")

8. **Context persistence**
   - context_summary (not raw)
   - cursor/last_seen_ts
   - **Structured salient_facts**:
     ```python
     class Fact(TypedDict):
         type: Literal["decision", "constraint", "assumption"]
         scope: Literal["channel", "epic", "thread"]
         source_ts: str  # Slack ts
         text: str
     ```

</essential>

<specifics>
## New State Fields

```python
class UserIntent(str, Enum):
    TICKET = "ticket"
    REVIEW = "review"
    DISCUSSION = "discussion"
    META = "meta"
    AMBIGUOUS = "ambiguous"

class PendingAction(str, Enum):
    WAITING_APPROVAL = "waiting_approval"
    WAITING_SCOPE_CHOICE = "waiting_scope_choice"
    WAITING_STORY_EDIT = "waiting_story_edit"
    WAITING_DECISION_EDIT = "waiting_decision_edit"
    WAITING_QUANTITY_CONFIRM = "waiting_quantity_confirm"
    # ... extensible

class WorkflowStep(str, Enum):
    """Typed workflow positions (not strings!)"""
    DRAFT_PREVIEW = "draft_preview"
    MULTI_TICKET_PREVIEW = "multi_ticket_preview"
    DECISION_PREVIEW = "decision_preview"
    REVIEW_ACTIVE = "review_active"
    REVIEW_FROZEN = "review_frozen"
    # ... extensible

class Fact(TypedDict):
    type: Literal["decision", "constraint", "assumption"]
    scope: Literal["channel", "epic", "thread"]
    source_ts: str
    text: str

class AgentState(TypedDict):
    # Existing fields...

    # NEW: Pure user intent (not workflow events)
    user_intent: Optional[UserIntent]
    intent_confidence: float  # 0.0 - 1.0

    # NEW: Workflow state (replaces overloaded intent)
    pending_action: Optional[PendingAction]
    workflow_step: Optional[WorkflowStep]  # Typed, not str!

    # NEW: Multi-ticket state
    multi_ticket_state: Optional[MultiTicketState]

    # NEW: Persisted context
    context_summary: Optional[str]
    salient_facts: list[Fact]  # Structured, not list[str]!
```

## Key Architectural Changes

1. **Event-First Routing (NEW)**
   ```python
   def route_message(event, state):
       # 1. WorkflowEvent (button/slash) - bypass intent entirely
       if is_workflow_event(event):
           return handle_workflow_event(event)

       # 2. PendingAction - continue workflow
       if state.pending_action:
           return continue_workflow(state.pending_action, event)

       # 3. UserIntent - classify and route
       intent = classify_intent(event.text)
       return route_by_intent(intent)
   ```

2. **Intent Router Simplification**
   - Remove: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION from IntentType
   - Add: AMBIGUOUS with 3-button scope gate
   - These become PendingAction values instead

3. **Typed WorkflowStep (NOT strings)**
   - All workflow positions are enum values
   - Enables determinism and testability
   - Migration: workflow_version field if needed

4. **Review Flow Rewrite**
   - Patch mode: only output changes + updated questions
   - Full synthesis: on "Show full architecture" button
   - REVIEW_COMPLETE detection (thanks/ok/got it)
   - **Freeze semantics**:
     - review_context remains accessible
     - but doesn't trigger continuation automatically
     - and doesn't bias next message's intent classification

5. **Multi-Ticket Flow with Safety Latch**
   - User: "Create epic with user stories for authentication"
   - Bot: Extract epic + N stories
   - **If N > 3**: "Confirm create 7 items?" (safety latch)
   - Bot: Show preview with all items
   - User: Edit story #3
   - Bot: Update story #3, show updated preview
   - User: Approve
   - Bot: Create epic, create stories as subtasks

6. **Decision Posts with Source Reference**
   - Preview in thread first
   - Edit option before posting
   - **Channel post includes**:
     - Thread link (where discussion happened)
     - Issue keys (if related tickets exist)

## Test Cases That Must Work

1. "Review this architecture" → REVIEW (not TICKET)
2. "Create a ticket for login bug" → TICKET
3. "What do you think about microservices?" → AMBIGUOUS → scope gate
4. "Thanks, looks good" after review → REVIEW_COMPLETE (freeze context)
5. "Now create a ticket for something unrelated" after frozen review → TICKET (not continuation!)
6. "Create epic with 5 stories for auth" → quantity confirmation → multi-ticket flow
7. User clicks "Approve" button → WorkflowEvent handler directly (no intent classification)
8. User clicks "Not now" on scope gate → clears pending_action, stops

</specifics>

<analysis>
## Root Problems Being Fixed

From BRAIN-ANALYSIS.md:

| Problem | Current State | After Phase 20 |
|---------|--------------|----------------|
| Intent overload | IntentType = user intent + workflow events | Separated: UserIntent + PendingAction |
| Events through intent | Button clicks classified by LLM | WorkflowEvent routed directly |
| TICKET bias | "If unclear, lean toward TICKET" | AMBIGUOUS + 3-button scope gate |
| Sticky continuation | REVIEW_CONTINUATION triggers on any related message | Freeze semantics + explicit REVIEW_COMPLETE |
| Expensive reviews | Full regeneration every answer | Patch mode default |
| Interrupt = endpoint | Every interrupt restarts graph | Resumable via pending_action |
| No multi-ticket | Single ticket per request | Epic + stories flow with safety latch |
| Decision without preview | Post to channel immediately | Preview → Edit → Post with source link |
| Context lost | conversation_context not persisted | context_summary + structured salient_facts |
| Stringly typed | workflow_step: str | WorkflowStep: Enum |

## Revised Wave Order

Based on feedback — resumable graph must come BEFORE review lifecycle:

- **Wave 1**: State types + event routing skeleton (UserIntent, PendingAction, WorkflowStep enums)
- **Wave 2**: pending_action/resume working end-to-end on 1 simple case (approve preview)
- **Wave 3**: Scope gate + AMBIGUOUS (3-button)
- **Wave 4**: Review lifecycle (patch mode, REVIEW_COMPLETE, freeze semantics)
- **Wave 5**: Multi-ticket flow with safety latch
- **Wave 6**: Context persistence (salient_facts structure)

This is a **large** phase: 10-14 plans across 6 waves.

</analysis>

<notes>
## Dependencies

- BRAIN-ANALYSIS.md provides detailed current state analysis
- Builds on Phase 18 clean code (handlers already split)

## Risks

- Large refactor touching intent.py, state.py, graph.py, runner.py, handlers
- Many existing tests will need updates
- Breaking changes to flow logic

## Guardrails (from review)

1. **Event-first routing** — WorkflowEvent → PendingAction → UserIntent
2. **Typed workflow_step** — Enum, not str
3. **3-button scope gate** — Review / Ticket / Not now
4. **Freeze semantics** — available but not triggering
5. **Structured salient_facts** — type/scope/source_ts/text
6. **Multi-ticket safety latch** — >3 items requires confirmation
7. **Decision source reference** — thread link + issue keys in channel post
8. **Resume before review** — Wave 2 before Wave 4

## Out of Scope

- External integrations (Confluence, GitHub)
- Voice/audio input
- Mobile app

## Core Principle

**Intent router should classify what user wants, not manage workflow state.**

The graph should be resumable. Pending actions should be explicit. Multi-ticket flows should be possible without hacking intent types.

Phase 20 is not just a refactor — it's a new stable platform for Phase 21+.

</notes>

---

*Phase: 20-brain-refactor*
*Context gathered: 2026-01-15*
*Updated: 2026-01-15 (guardrails from review)*

# Phase 20: Brain Refactor - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning
**Updated:** 2026-01-15 (v4: HA-ready, UI versioning, eviction policies)

<vision>
## How This Should Work

MARO's brain needs a fundamental architecture shift. Currently, intent classification is overloaded — it handles both user intent (what they want) AND workflow events (button clicks, approvals, continuations). This creates a tangled mess where adding any new feature requires a new "intent type".

After Phase 20, the system should work like this:

1. **WorkflowEvent first** → Button clicks, slash commands go directly to handlers (no intent classification)
2. **Check pending_action** → If workflow is waiting for something, route to continuation handler
3. **Intent classification** → Only for new messages: TICKET | REVIEW | DISCUSSION | META | AMBIGUOUS
4. **AMBIGUOUS triggers scope gate** → 3 buttons: "Review" / "Create ticket" / "Not now" + "Remember for this thread" option
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

2. **Event-First Routing with Idempotency**
   - If event = button_click/slash_command → handler directly (no intent classifier)
   - Else if pending_action != None → continuation handler
   - Else → intent classifier
   - **Idempotency**: track processed event_ids, reject duplicates
   - **HA-ready storage**: processed_event_ids in Postgres/Redis (24h TTL)
   - **Key**: `(team_id, event_id)` — for button clicks fallback to `(action_id, message_ts, user_id)`

3. **Remove "lean toward TICKET" bias**
   - AMBIGUOUS intent with scope gate (3 buttons)
   - "Review" / "Create ticket" / "Not now (dismiss)"
   - "Not now" clears pending_action and stops cycle
   - **"Remember for this thread"** option: stores thread_default_intent
   - **Reset conditions**: expires after 2h inactivity OR workflow_step leaves {REVIEW_ACTIVE, REVIEW_FROZEN}
   - **Clear command**: `/maro forget` or "Clear remembered mode" button
   - User decides, bot doesn't guess

4. **Resumable graph**
   - pending_action + pending_payload in state tells where to continue AND with what context
   - No more "every interrupt goes to START"
   - Resumable must work BEFORE review lifecycle fixes (dependency)
   - **pending_payload contract**: minimal identifiers only (story_id, draft_id), NOT full objects
   - Large data stored in multi_ticket_state / draft_store, payload contains refs

5. **Review lifecycle fixes**
   - REVIEW_COMPLETE patterns (thanks/ok/got it)
   - Patch mode by default (only diff, not full regeneration)
   - Full synthesis on "Show full architecture" button
   - TTL/cooldown for review_context
   - **Freeze semantics**: frozen review_context remains available for handoff but doesn't trigger continuation and doesn't affect next message's intent
   - **Frozen artifact**: explicit review_artifact_summary, review_artifact_kind, review_artifact_version
   - **Patch structure** (fixed format, max 12 bullets):
     - New decisions
     - New risks
     - New open questions
     - Changes since vN

6. **Decision approval flow**
   - Preview in thread → Edit → Post to channel
   - No more "post without confirmation"
   - **Source reference**: channel post must link to source thread + issue keys

7. **Multi-ticket support**
   - Epic + stories **linked to Epic** (not subtasks — configurable per project)
   - Preview all items
   - Edit individual stories
   - Resume after edits
   - **Quantity safety latch**: >3 items requires explicit confirmation
   - **Size safety latch**: total draft > X chars → "Split into batches?"
   - **Dry-run validation**: before create, validate all required fields, mappings, permissions
   - Reduces "Approved → failed create" failures

8. **Context persistence**
   - context_summary (not raw)
   - cursor/last_seen_ts
   - **Structured salient_facts** with confidence and dedup:
     ```python
     class Fact(TypedDict):
         type: Literal["decision", "constraint", "assumption"]
         scope: Literal["channel", "epic", "thread"]
         source_ts: str  # Slack ts
         text: str
         confidence: float  # 0.0 - 1.0
         canonical_id: str  # hash(text + scope + type) for dedup
     ```
   - **Eviction policy**:
     - Max facts per scope: thread=50, epic=200, channel=300
     - Eviction by LRU or lowest confidence
     - Merge by canonical_id (update instead of append)

9. **Event validation per workflow step**
   - Each WorkflowStep has allowed_events list
   - Invalid events → "This action is no longer available" (stale UI)
   - **UI versioning**: ui_version (int) in state, included in button values
   - Validates "same step but old preview" (edit→old approve click)

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

class WorkflowEventType(str, Enum):
    BUTTON_CLICK = "button_click"
    SLASH_COMMAND = "slash_command"
    MODAL_SUBMIT = "modal_submit"

class Fact(TypedDict):
    type: Literal["decision", "constraint", "assumption"]
    scope: Literal["channel", "epic", "thread"]
    source_ts: str
    text: str
    confidence: float  # NEW: for dedup/contradiction detection
    canonical_id: str  # NEW: hash for dedup

class ReviewArtifact(TypedDict):
    """Frozen review context for handoff"""
    summary: str  # Compressed review content
    kind: Literal["architecture", "security", "pm"]
    version: int  # For patch mode tracking

class AgentState(TypedDict):
    # Existing fields...

    # NEW: Pure user intent (not workflow events)
    user_intent: Optional[UserIntent]
    intent_confidence: float  # 0.0 - 1.0

    # NEW: Workflow state (replaces overloaded intent)
    pending_action: Optional[PendingAction]
    pending_payload: Optional[dict]  # NEW: context for pending action
    workflow_step: Optional[WorkflowStep]  # Typed, not str!

    # NEW: Event tracking for idempotency
    last_event_id: Optional[str]
    last_event_type: Optional[WorkflowEventType]
    # processed_event_ids: stored in Postgres/Redis (24h TTL, HA-ready)

    # NEW: UI versioning (prevents stale button clicks within same step)
    ui_version: int  # Incremented on each preview update

    # NEW: Thread-level preferences
    thread_default_intent: Optional[UserIntent]  # "Remember for this thread"

    # NEW: Multi-ticket state
    multi_ticket_state: Optional[MultiTicketState]

    # NEW: Review artifact (for frozen handoff)
    review_artifact: Optional[ReviewArtifact]

    # NEW: Persisted context
    context_summary: Optional[str]
    salient_facts: list[Fact]  # Structured with confidence + canonical_id
```

## Allowed Events per Workflow Step

```python
ALLOWED_EVENTS: dict[WorkflowStep, set[str]] = {
    WorkflowStep.DRAFT_PREVIEW: {"approve", "reject", "edit"},
    WorkflowStep.MULTI_TICKET_PREVIEW: {"approve", "edit_story", "cancel", "confirm_quantity"},
    WorkflowStep.DECISION_PREVIEW: {"approve", "edit", "cancel"},
    WorkflowStep.REVIEW_ACTIVE: {"show_full", "approve_decision"},
    WorkflowStep.REVIEW_FROZEN: set(),  # No workflow actions on frozen review
}

def validate_event(step: WorkflowStep, event_action: str) -> bool:
    """Returns False for stale/invalid events"""
    if step not in ALLOWED_EVENTS:
        return False
    return event_action in ALLOWED_EVENTS[step]
```

## Key Architectural Changes

1. **Event-First Routing with Idempotency**
   ```python
   def route_message(event, state):
       # 0. Check idempotency (duplicate event)
       if event.id in get_processed_events():
           return already_processed_response()

       # 1. WorkflowEvent (button/slash) - bypass intent entirely
       if is_workflow_event(event):
           # Validate event is allowed for current step
           if not validate_event(state.workflow_step, event.action):
               return stale_ui_response()
           mark_event_processed(event.id)
           return handle_workflow_event(event)

       # 2. PendingAction - continue workflow
       if state.pending_action:
           return continue_workflow(state.pending_action, state.pending_payload, event)

       # 3. Thread default intent (if "Remember" was selected)
       if state.thread_default_intent:
           return route_by_intent(state.thread_default_intent)

       # 4. UserIntent - classify and route
       intent = classify_intent(event.text)
       return route_by_intent(intent)
   ```

2. **Intent Router Simplification**
   - Remove: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION from IntentType
   - Add: AMBIGUOUS with 3-button scope gate + "Remember" checkbox
   - These become PendingAction values instead

3. **Typed WorkflowStep with Allowed Events**
   - All workflow positions are enum values
   - Each step has explicit allowed_events
   - Invalid events return "stale UI" message
   - Enables determinism and testability

4. **Review Flow Rewrite**
   - Patch mode: only output changes + updated questions
   - Full synthesis: on "Show full architecture" button
   - REVIEW_COMPLETE detection (thanks/ok/got it)
   - **Freeze semantics**:
     - review_context → review_artifact (explicit structure)
     - Remains accessible for Review→Ticket handoff
     - But doesn't trigger continuation automatically
     - And doesn't bias next message's intent classification

5. **Multi-Ticket Flow with Safety Latches**
   - User: "Create epic with user stories for authentication"
   - Bot: Extract epic + N stories
   - **If N > 3**: "Confirm create 7 items?" (quantity latch)
   - **If total_chars > X**: "Split into batches?" (size latch)
   - Bot: Show preview with all items
   - User: Edit story #3 → pending_payload: {"story_id": "3"}
   - Bot: Update story #3, show updated preview
   - User: Approve
   - Bot: Create epic, link stories to Epic (not subtasks by default)

6. **Decision Posts with Source Reference**
   - Preview in thread first (DecisionPreview)
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
9. **Duplicate Approve click** → second click returns "Already processed" (idempotent)
10. **Stale button click** → click on old preview after edit returns "This preview is outdated"
11. User selects "Remember: Review for this thread" → subsequent AMBIGUOUS messages auto-route to REVIEW
12. **Remember expires** → after 2h inactivity, AMBIGUOUS shows scope gate again
13. **UI version mismatch** → click Approve on preview v1 after edit created v2 → "Preview outdated"
14. **Dry-run catches error** → missing required field detected before create, not after

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
| Interrupt = endpoint | Every interrupt restarts graph | Resumable via pending_action + pending_payload |
| No multi-ticket | Single ticket per request | Epic + stories flow with safety latches |
| Decision without preview | Post to channel immediately | Preview → Edit → Post with source link |
| Context lost | conversation_context not persisted | context_summary + structured salient_facts |
| Stringly typed | workflow_step: str | WorkflowStep: Enum |
| No idempotency | Double-click creates duplicates | Event ID tracking, first-wins |
| Stale UI | Old buttons affect current state | Allowed events per step validation |
| Repeated scope gate | 3x "what do you think" = 3x gate | "Remember for this thread" option |

## Revised Wave Order

Based on feedback — resumable graph must come BEFORE review lifecycle:

- **Wave 1**: State types + event routing skeleton (enums, event validation, idempotency)
- **Wave 2**: pending_action/resume + pending_payload working end-to-end (approve preview)
- **Wave 3**: Scope gate + AMBIGUOUS (3-button + "Remember for thread")
- **Wave 4**: Review lifecycle (patch mode, REVIEW_COMPLETE, freeze semantics, ReviewArtifact)
- **Wave 5**: Multi-ticket flow with safety latches (quantity + size)
- **Wave 6**: Context persistence (structured salient_facts with confidence + canonical_id)

This is a **large** phase: 12-16 plans across 6 waves.

</analysis>

<notes>
## Dependencies

- BRAIN-ANALYSIS.md provides detailed current state analysis
- Builds on Phase 18 clean code (handlers already split)

## Risks

- Large refactor touching intent.py, state.py, graph.py, runner.py, handlers
- Many existing tests will need updates
- Breaking changes to flow logic

## Guardrails (production-ready)

1. **Event-first routing** — WorkflowEvent → PendingAction → UserIntent
2. **Event idempotency** — track event_id, reject duplicates
3. **HA-ready event storage** — Postgres/Redis with 24h TTL, key=(team_id, event_id)
4. **Typed workflow_step** — Enum, not str
5. **Allowed events per step** — validate or return "stale UI"
6. **UI versioning** — ui_version in state + button values, prevents stale preview clicks
7. **3-button scope gate** — Review / Ticket / Not now
8. **"Remember for thread"** — reduces repeated scope gates
9. **Remember reset conditions** — 2h inactivity or workflow exit, `/maro forget` command
10. **pending_payload contract** — minimal refs only, large data in stores
11. **Freeze semantics** — ReviewArtifact with summary/kind/version
12. **Patch structure** — fixed format with 4 sections, max 12 bullets
13. **Structured salient_facts** — type/scope/source_ts/text/confidence/canonical_id
14. **Fact eviction policy** — max per scope (50/200/300), LRU by confidence
15. **Multi-ticket quantity latch** — >3 items requires confirmation
16. **Multi-ticket size latch** — >X chars → "Split into batches?"
17. **Dry-run validation** — validate Jira fields/permissions before create
18. **Stories linked to Epic** — not subtasks (configurable)
19. **Decision source reference** — thread link + issue keys in channel post
20. **Resume before review** — Wave 2 before Wave 4

## Out of Scope

- External integrations (Confluence, GitHub)
- Voice/audio input
- Mobile app
- Jira schema configuration UI (use project defaults)

## Core Principle

**Intent router should classify what user wants, not manage workflow state.**

The graph should be resumable. Pending actions should be explicit. Multi-ticket flows should be possible without hacking intent types.

Phase 20 is not just a refactor — it's a new stable platform for Phase 21+.

</notes>

---

*Phase: 20-brain-refactor*
*Context gathered: 2026-01-15*
*Updated: 2026-01-15 (v3: production-ready guardrails)*

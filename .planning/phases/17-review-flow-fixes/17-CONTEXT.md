# Phase 17: Review Flow and Event Fixes - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

When users have architecture discussions with MARO, the conversation should flow naturally without context loss or repetition:

### The Problems Found in Production

**Thread from production (2026-01-15 19:50-19:54):**
```
1. User: @Maro propose architecture for GitHub/Jira access orchestrator
2. MARO: [Detailed architecture review with open questions]
3. User: "I like architecture"
   → Bot says: "Do you have a specific system?" ✗ (lost context)
4. User: "Create Jira tickets that represent the architecture"
   → Bot asks: "What are acceptance criteria?" ✗ (ignored the architecture review)
5. User: "propose default, how you see it"
   → Bot generates SECOND full architecture review ✗ (unnecessary 11s LLM call)
6. User clicks "Create ticket" button → scope gate
7. User: "go ahead and create"
   → Bot detects DECISION_APPROVAL ✓
   → But NO architecture decision posted to channel ✗ (review_context lost)
```

**Also:** When bot joins new channel, welcome message not appearing in channel root (only seeing greeting hints in threads).

### Expected Behavior

**Same conversation should flow like:**
```
1. User: @Maro propose architecture
2. MARO: [Architecture review]
3. User: "I like architecture"
   → MARO: "Great! Should we proceed with this approach? Or would you like to create Jira tickets for implementation?"
4. User: "Create Jira tickets that represent the architecture"
   → MARO extracts tickets from the architecture review (Components, Risks, etc.)
   → Posts structured tickets without asking for criteria
5. User: "go ahead"
   → MARO posts Architecture Decision to CHANNEL (not thread):

   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   🏗️ Architecture Decision

   **Topic:** GitHub/Jira Access Orchestrator
   **Decision:** Build custom IAM orchestrator with worker-queue pattern
   [Key components and rationale...]

   📎 Discussion: [link to thread]
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Also:** When bot joins channel, pinned welcome message should appear in channel root.

</vision>

<essential>
## What Must Be Nailed

1. **Context-aware intent classification** - Pass `has_review_context` to classifier
2. **Thread context extraction** - "Create tickets for THE ARCHITECTURE" uses thread content
3. **Continuation detection** - "propose default" recognized as answering bot's question
4. **review_context lifecycle** - Preserved until decision posted, not overwritten
5. **Architecture decision posting** - Posts to CHANNEL when user approves
6. **Channel join welcome** - Verify event fires and message posts to channel root

</essential>

<specifics>
## Root Causes

### Bug #1: "I like architecture" misclassified as DISCUSSION
**File:** `src/slack/handlers.py`
```python
# Current:
intent_result = await classify_intent(message)

# Should be:
has_review_context = bool(state.get("review_context"))
intent_result = await classify_intent(message, has_review_context=has_review_context)
```

**Impact:** Lost review context, bot asks "Do you have a specific system?"

### Bug #2: "Create tickets for the architecture" ignored thread context
**File:** `src/graph/nodes/extraction.py`

Need to detect references like:
- "the architecture"
- "this review"
- "that analysis"

And pull content from `conversation_context` to use as extraction basis.

### Bug #3: "propose default" classified as NEW REVIEW
**File:** `src/graph/intent.py`

When bot asks a question and user says "you propose" or "you decide", this should be REVIEW_CONTINUATION, not new REVIEW.

Add pattern:
```python
REVIEW_CONTINUATION_PATTERNS = [
    # ... existing
    (r"\b(?:you\s+)?(?:propose|suggest|recommend|decide)\b.*(?:default|for\s+me)",
     "pattern: user deferring to bot"),
]
```

### Bug #4: Architecture decision NOT posted to channel
**Root cause:** Bug #3 overwrote `review_context` with second review
**When:** Second review replaced first → when user approved, no context existed
**Fix:** Don't allow new REVIEW to overwrite active review_context
**Also:** Add review_context state machine (ACTIVE → CONTINUATION → APPROVED → POSTED)

### Bug #5: Not a bug
Greeting hints work correctly (Phase 12-02).

### Bug #6: Welcome message not on channel join
**Possible causes:**
- Slack event `member_joined_channel` not configured in app manifest
- Event firing but handler failing silently
- Message posting to thread instead of channel root

**Files to check:**
- `src/slack/handlers.py` lines 2945-3003 (handler code)
- Slack app Event Subscriptions configuration
- Slack app Bot Token Scopes (channels:read, channels:history)

</specifics>

<notes>
## Additional Context

### Cascading Failure Chain
```
Review #1 posted → review_context SET
  ↓
Bug #1: "I like" → DISCUSSION (should be CONTINUATION)
  ↓
Bug #2: "Create tickets" → extraction ignores thread
  ↓
Bot asks: "What are acceptance criteria?"
  ↓
Bug #3: "propose default" → NEW REVIEW (overwrites review_context)
  ↓
Second review generated (11s)
  ↓
User clicks "Create ticket" → works with SECOND review
  ↓
Bug #4: "go ahead" → no review_context → NO decision posted
```

### Phase 14 Core Principle (Violated by Bug #4)
> **Thread = thinking process** (working table with blueprints)
> **Channel = system state** (board with approved decisions)

When user approves an architecture decision in thread, it MUST be posted to channel as permanent record.

### Out of Scope
- Multi-round Q&A beyond single continuation (Phase 18+)
- Partial answer handling ("I'll answer IdP later")
- Review modification requests ("Actually, change security analysis")
- Editing/amending decisions after posting

</notes>

---

*Phase: 17-review-flow-fixes*
*Context gathered: 2026-01-15*

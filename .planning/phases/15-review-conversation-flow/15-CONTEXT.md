# Phase 15: Review Conversation Flow - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

When user replies to a REVIEW with answers to open questions, MARO should continue the conversation - not start a new ticket flow.

### The Problem

Current behavior:
```
User: @Maro propose architecture
MARO: [Architecture review with 5 open questions]
User: Provisioning Type - Automatic, IdP - Okta, Granularity - system access, Security Loop - Employee
MARO: *creates ticket draft* → *finds duplicate* → "Linked to SCRUM-111"  ← WRONG
```

Expected behavior:
```
User: @Maro propose architecture
MARO: [Architecture review with 5 open questions]
User: Provisioning Type - Automatic, IdP - Okta...
MARO: "Thanks for the clarifications. Based on these choices:
       - Automatic provisioning → need robust retry/idempotency
       - Okta IdP → can leverage existing SSO, use Okta groups
       - System-level access → simpler UI, coarser permissions
       - Security loop to Employee → state machine: Draft → Manager → Security → Employee (if questions) → Provisioning

       Given these constraints, I recommend Option A (Custom Build) with Temporal for workflows.

       Should we proceed with this approach?"
User: "yes, let's go with this"
MARO: *posts Architecture Decision to channel* (Phase 14)
```

### Root Cause

The intent router is **stateless**. It doesn't know:
1. Previous message was a REVIEW
2. REVIEW had open questions
3. Current message is answering those questions

The LLM saw "Provisioning Type - Automatic, IdP - Okta..." and thought: "structured requirements = TICKET intent"

### Solution: Context-Aware Intent Classification

When `review_context` exists in state (set by Phase 14's review_node):
1. Check if message looks like answers to questions (not a new request)
2. Classify as `REVIEW_CONTINUATION` instead of TICKET
3. Route to review continuation flow

</vision>

<essential>
## What Must Be Nailed

1. **Context-aware intent classification** — If review_context exists, bias toward REVIEW_CONTINUATION
2. **Review continuation node** — Synthesize answers, update recommendations, ask for approval
3. **Smooth handoff to decision approval** — User says "yes" → Phase 14 posts to channel

</essential>

<specifics>
## Specific Ideas

### Intent Classification with Context

Add `review_context` check to `classify_intent()`:

```python
async def classify_intent(message: str, has_review_context: bool = False) -> IntentResult:
    """Classify user message intent.

    Args:
        message: User's message text
        has_review_context: True if thread has pending review (from state.review_context)
    """
    # If we have review context, check for continuation patterns first
    if has_review_context:
        continuation_result = _check_review_continuation(message)
        if continuation_result:
            return continuation_result

    # ... existing pattern matching and LLM classification
```

### Review Continuation Patterns

```python
REVIEW_CONTINUATION_PATTERNS = [
    # Direct answers (key-value style)
    (r"^[\w\s]+\s*[-:]\s*\w+", "pattern: key-value answer format"),
    # Numbered answers
    (r"^\d+[.)]\s*\w+", "pattern: numbered answer"),
    # Bullet answers
    (r"^[-•]\s*\w+", "pattern: bullet answer"),
]

# Also check negatively - these are NOT continuations
NOT_CONTINUATION_PATTERNS = [
    r"\bcreate\s+(?:a\s+)?ticket\b",
    r"\bnew\s+(?:ticket|task|story)\b",
    r"\bpropose\s+(?:new|another)\b",
]
```

### LLM Fallback with Context

Update LLM classification prompt when `has_review_context=True`:

```python
INTENT_PROMPT_WITH_REVIEW_CONTEXT = """
Classify this user message. IMPORTANT: This message is a reply in a thread
where the bot just provided an architecture review with open questions.

User message: "{message}"

If the message looks like answers to questions (e.g., "Option A", "Yes",
key-value pairs, bullet points), classify as REVIEW_CONTINUATION.

Only classify as TICKET if user explicitly asks for a new ticket.

Categories:
- REVIEW_CONTINUATION: Answering questions from previous review
- DECISION_APPROVAL: Approving the reviewed approach ("let's go with this")
- TICKET: Explicitly requesting a new Jira ticket
- DISCUSSION: General conversation
"""
```

### New IntentType

```python
class IntentType(str, Enum):
    TICKET = "TICKET"
    REVIEW = "REVIEW"
    DISCUSSION = "DISCUSSION"
    TICKET_ACTION = "TICKET_ACTION"
    DECISION_APPROVAL = "DECISION_APPROVAL"
    REVIEW_CONTINUATION = "REVIEW_CONTINUATION"  # NEW
```

### Review Continuation Node

```python
async def review_continuation_node(state: AgentState) -> dict[str, Any]:
    """Continue review conversation after user provides answers.

    1. Extract answers from user message
    2. Map answers to original open questions
    3. Update architecture recommendations
    4. Ask for approval to proceed
    """
    review_context = state.get("review_context")
    # ... get latest user message

    prompt = REVIEW_CONTINUATION_PROMPT.format(
        original_review=review_context["review_summary"],
        user_answers=latest_message,
        topic=review_context["topic"],
    )

    continuation = await llm.chat(prompt)

    return {
        "decision_result": {
            "action": "review_continuation",
            "message": continuation,
            "persona": review_context["persona"],
            "topic": review_context["topic"],
        },
        # Keep review_context for potential decision approval
        "review_context": {
            **review_context,
            "answers_received": True,
            "updated_recommendation": continuation,
        }
    }
```

### Review Continuation Prompt

```python
REVIEW_CONTINUATION_PROMPT = '''You are continuing an architecture discussion.

Original review topic: {topic}

Your previous analysis:
{original_review}

User's answers to your open questions:
{user_answers}

Based on these answers, provide:
1. Brief acknowledgment of their choices
2. How these choices affect the architecture (2-3 key implications)
3. Your updated recommendation (which option to proceed with)
4. A clear question asking if they want to proceed

Format for Slack:
- Bold: *text*
- Lists: Use bullet •
- Keep it concise (not as long as original review)
- End with a clear "Should we proceed with [approach]?" question
'''
```

### Graph Routing

```python
def route_after_intent(state: AgentState) -> str:
    intent_result = state.get("intent_result", {})
    intent = intent_result.get("intent")

    if intent == "REVIEW_CONTINUATION":
        return "review_continuation_flow"
    # ... existing routes
```

</specifics>

<notes>
## Additional Context

### DoD (Definition of Done):

- [ ] REVIEW_CONTINUATION intent type added
- [ ] Intent classification checks review_context before classifying
- [ ] Review continuation node synthesizes answers and asks for approval
- [ ] Handler posts continuation response to thread
- [ ] Decision approval (Phase 14) triggers on "yes" response
- [ ] Logs show: continuation detected, answers parsed, approval asked

### Integration Points:

- **Phase 14:** review_context already saved after review_node
- **Phase 13:** Intent router needs to accept has_review_context parameter
- **Handlers:** Need to pass review_context existence to intent classification

### State Flow:

```
1. REVIEW intent → review_node → sets review_context
2. User replies with answers
3. Intent classification sees review_context → REVIEW_CONTINUATION
4. review_continuation_node → updates review_context with answers
5. User says "yes, proceed"
6. Intent classification sees review_context → DECISION_APPROVAL
7. decision_approval_node → posts to channel, clears review_context
```

### Out of Scope:

- Multi-round Q&A (more than one continuation)
- Partial answers handling ("I'll answer IdP later")
- Review modification requests ("Actually, change the security analysis")

### Related: Ticket Update Stubs (Phase 13.1 deferred)

Phase 13.1 left "update" and "add_comment" as stubs:
```
User: @Maro update SCRUM-111 with our architectural decisions
MARO: "I can help with update for SCRUM-111. (Full implementation coming soon)"
```

**Options:**
1. Add to Phase 15 (if natural fit with review flow)
2. Create Phase 16 for Ticket Operations (update, comment, subtask creation)

**Recommendation:** Create Phase 16. Ticket update operations are orthogonal to review conversation flow. Mixing them would bloat Phase 15.

</notes>

---

*Phase: 15-review-conversation-flow*
*Context gathered: 2026-01-15*

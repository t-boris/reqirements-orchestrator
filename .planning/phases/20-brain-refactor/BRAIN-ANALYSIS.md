# MARO Bot Brain Analysis
## Current Thinking & Behavior Rules

**Purpose:** Comprehensive analysis of MARO's decision-making, behavior patterns, and intelligence systems to enable Phase 20 refactoring.

**Created:** 2026-01-15
**Status:** Pre-Phase 20 Analysis

---

## Table of Contents

1. [Intent Classification System](#intent-classification-system)
2. [Flow Routing Architecture](#flow-routing-architecture)
3. [Node Execution Logic](#node-execution-logic)
4. [Context Management](#context-management)
5. [LLM Prompting Strategy](#llm-prompting-strategy)
6. [Decision Points & Heuristics](#decision-points--heuristics)
7. [Known Issues & Limitations](#known-issues--limitations)
8. [Refactoring Priorities](#refactoring-priorities)

---

## Intent Classification System

### Overview
The bot uses a **two-tier classification system**:
1. **Pattern matching** (deterministic, fast, high confidence)
2. **LLM classification** (flexible, slower, handles ambiguity)

**Location:** `src/graph/intent.py`

### Intent Types (6 total)

```python
class IntentType(str, Enum):
    TICKET = "TICKET"                    # Create a Jira ticket
    REVIEW = "REVIEW"                    # Analysis/feedback without Jira
    DISCUSSION = "DISCUSSION"            # Casual greeting, simple question
    TICKET_ACTION = "TICKET_ACTION"      # Work with existing ticket
    DECISION_APPROVAL = "DECISION_APPROVAL"  # Approve review/architecture
    REVIEW_CONTINUATION = "REVIEW_CONTINUATION"  # Answer questions from review
```

### Pattern Matching Rules

**Priority Order:**
1. **NEGATION patterns** (highest) - "don't create ticket", "no ticket"
2. **REVIEW_CONTINUATION** (when `has_review_context=True`)
3. **NOT_CONTINUATION** (override continuation detection)
4. **TICKET_ACTION** - References to existing tickets (SCRUM-XXX)
5. **TICKET** - "create ticket", "draft ticket", "make ticket"
6. **REVIEW** - "review as security", "propose architecture", "help to design"
7. **DECISION_APPROVAL** (when `has_review_context=True`) - "approved", "let's go"
8. **DISCUSSION** - "hi", "hello", "help"

**Key Pattern Examples:**

```python
# REVIEW patterns
r"\bpropose\s+(?:an?\s+)?architecture\b"
r"\bhelp\s+(?:me\s+)?(?:to\s+)?(?:organize|design|architect)\s+(?:an?\s+)?architecture\b"
r"\barchitecture\s+review\b"

# REVIEW_CONTINUATION patterns
r"^[\w\s]+\s*[-:]\s*\w+"  # Key-value format
r"^\d+[.)]\s*\w+"          # Numbered answers
r"\b(?:you\s+)?(?:propose|suggest|decide).*(?:default|for\s+me)"  # User deferring

# TICKET patterns
r"\bcreate\s+(?:a\s+)?ticket\b"
r"\bjira\s+(?:story|ticket|issue)\b"
```

### LLM Classification

**When patterns don't match**, falls through to LLM with two different prompts:

#### With Review Context (`has_review_context=True`)
```
REVIEW_CONTINUATION applies to ANY message that continues the architecture discussion:
- Answering the bot's open questions
- Requesting to see the updated architecture
- Asking follow-up questions about the review
- Providing additional context or constraints

DEFAULT: When in doubt, if the message relates to the architecture review at all, choose REVIEW_CONTINUATION.
```

#### Without Review Context
```
TICKET: User wants to create a NEW Jira ticket
REVIEW: User wants analysis, feedback, or discussion without creating a Jira ticket
DISCUSSION: Casual greeting, simple question about the bot

If the user seems to want to work on something but it's unclear if they want a ticket, lean toward TICKET.
```

### Current Problems

1. **Ambiguity between TICKET and REVIEW**
   - "help to organize architecture" → Could be TICKET or REVIEW
   - Current: Pattern overrides LLM, forces REVIEW
   - Issue: User might actually want a ticket

2. **Multi-ticket requests not recognized**
   - "create epics and user stories" → Treated as single TICKET
   - No understanding of hierarchical structures

3. **Context window is binary**
   - Either `has_review_context=True` or `False`
   - No nuance: "How far into review are we?"

4. **No "meta" intent detection**
   - Can't detect: "I want to change my approach"
   - Can't detect: "Let's start over"
   - Can't detect: "Create multiple tickets from this discussion"

---

## Flow Routing Architecture

### Graph Structure

**Location:** `src/graph/graph.py`

```
START
  ↓
intent_router (classify intent)
  ↓
  ├─→ ticket_flow        → extraction → validation → decision → preview → END
  ├─→ review_flow        → review → END
  ├─→ discussion_flow    → discussion → END
  ├─→ ticket_action_flow → ticket_action → END
  ├─→ decision_approval_flow → decision_approval → END
  └─→ review_continuation_flow → review_continuation → END
```

### Flow Descriptions

#### 1. **ticket_flow** (Default)
- **Purpose:** Create a new Jira ticket
- **Nodes:** extraction → validation → decision → preview
- **Interrupts at:** preview (waits for user approval)
- **State:** Maintains `draft` object through entire flow

#### 2. **review_flow**
- **Purpose:** Provide analysis/feedback without Jira operations
- **Nodes:** review (single node)
- **Interrupts at:** review (returns immediately)
- **State:** Stores `review_context` for potential continuation

#### 3. **discussion_flow**
- **Purpose:** Simple conversational responses
- **Nodes:** discussion (single node)
- **Interrupts at:** discussion (returns immediately)
- **State:** No state persisted

#### 4. **ticket_action_flow**
- **Purpose:** Work with existing tickets (subtasks, updates, comments)
- **Nodes:** ticket_action (single node)
- **Interrupts at:** ticket_action (returns immediately)
- **State:** No draft, just executes action

#### 5. **decision_approval_flow**
- **Purpose:** Post approved architecture decision to channel
- **Nodes:** decision_approval (single node)
- **Interrupts at:** decision_approval (returns immediately)
- **State:** Clears `review_context` after posting

#### 6. **review_continuation_flow**
- **Purpose:** Continue review discussion after user provides answers
- **Nodes:** review_continuation (single node)
- **Interrupts at:** review_continuation (returns immediately)
- **State:** Updates `review_context` with answers

### Current Problems

1. **Single-path flows**
   - No branching within flows
   - Can't handle: "Actually, let me change that answer"

2. **No multi-ticket flow**
   - Each flow creates exactly ONE ticket
   - Can't handle: "Create epic + 5 user stories"

3. **No flow transitions**
   - Once in a flow, can't switch
   - Can't handle: "Turn this review into tickets"

4. **Interrupt points are endpoints**
   - Every interrupt goes back to START
   - No way to resume within a flow

---

## Node Execution Logic

### Node Types

#### 1. **Intent Router Node**
**Location:** `src/graph/intent.py` (function: `classify_intent`)

**Logic:**
```python
1. Check NEGATION patterns
2. If has_review_context:
   - Check REVIEW_CONTINUATION patterns
   - Check NOT_CONTINUATION overrides
3. Check TICKET_ACTION patterns
4. Check TICKET patterns
5. Check REVIEW patterns
6. If has_review_context:
   - Check DECISION_APPROVAL patterns
7. Check DISCUSSION patterns
8. If no match → LLM classification
```

**Issues:**
- Pattern priority is hardcoded
- No confidence thresholds for patterns (always 1.0 or 0.9)
- LLM fallback can contradict patterns

#### 2. **Extraction Node**
**Location:** `src/graph/nodes/extraction.py`

**Logic:**
```python
1. Detect if message references prior content:
   - "the architecture", "this review", "from above"
2. If references detected:
   - Include conversation_context in extraction prompt
3. Call LLM to extract fields:
   - title, problem, solution, acceptance_criteria
4. Return extracted fields as Draft
```

**Prompt Strategy:**
- Uses structured extraction with field descriptions
- Includes persona examples (PM, Security, Architect)
- Has EXTRACTION_PROMPT_WITH_REFERENCE variant

**Issues:**
- No multi-ticket extraction
- No epic/story hierarchy understanding
- Reference detection is pattern-based (fragile)

#### 3. **Review Node**
**Location:** `src/graph/nodes/review.py`

**Logic:**
```python
1. Select persona (architect, security, pm)
2. Build review prompt with topic and persona
3. Call LLM to generate analysis
4. Check if active review already exists:
   - If review_context.state in [ACTIVE, CONTINUATION]:
     - Log warning, don't overwrite
     - Return review without saving context
   - Else:
     - Save review_context with state=ACTIVE
5. Return review for posting
```

**Review Context Structure:**
```python
{
    "state": ReviewState.ACTIVE,
    "review_summary": review_message,
    "persona": persona,
    "topic": topic,
    "thread_ts": thread_ts,
    "channel_id": channel_id,
    "created_at": timestamp,
}
```

**Issues:**
- Active review check prevents new reviews (good!)
- But no way to explicitly end a review
- No way to have multiple active reviews in different threads

#### 4. **Review Continuation Node**
**Location:** `src/graph/nodes/review_continuation.py`

**Logic:**
```python
1. Check if review_context exists
   - If not → return error message
2. Get full conversation history:
   - conversation_context.messages (from Slack)
   - state.messages (from LangGraph)
3. Build conversation history string
4. Build prompt with:
   - Original review
   - Full conversation history
   - Request for COMPLETE updated architecture
5. Call LLM to generate continuation
6. Update review_context with answers
7. Return continuation for posting
```

**Prompt Strategy:**
```
Based on the FULL conversation above, provide a complete updated architecture incorporating all information:
1. Acknowledge user's answers
2. Present COMPLETE updated architecture:
   - High-level approach
   - Key components
   - Technical decisions based on answers
   - Implementation considerations
   - Risks and mitigations
   - Open questions (if any remain)
```

**Issues:**
- Generates full architecture every time (expensive)
- No summary/incremental update mode
- Can't extract multiple tickets from architecture

#### 5. **Decision Approval Node**
**Location:** `src/graph/nodes/decision_approval.py`

**Logic:**
```python
1. Get review_context
2. Extract decision summary
3. Mark review_context.state = POSTED
4. Format decision for channel posting
5. Return decision + clear review_context
```

**Issues:**
- No validation that decision makes sense
- No way to amend decision before posting

#### 6. **Validation Node**
**Location:** `src/graph/nodes/validation.py`

**Logic:**
```python
1. Check draft completeness (all required fields)
2. LLM validation:
   - Problem/solution consistency
   - Acceptance criteria quality
   - Scope appropriateness
3. Persona-specific validation
4. Return validation result + errors/warnings
```

**Issues:**
- Only validates single ticket
- No validation of epic/story relationships

---

## Context Management

### State Structure

**Location:** `src/schemas/state.py`

```python
class AgentState(TypedDict):
    messages: list[BaseMessage]          # LangGraph message history
    draft: TicketDraft                   # Current ticket being created
    phase: AgentPhase                    # COLLECTING | REVIEWING | READY
    decision_result: dict                # Action + data for handler
    review_context: Optional[dict]       # Active review state
    conversation_context: Optional[dict] # Thread history from Slack
    thread_ts: str                       # Slack thread identifier
    channel_id: str                      # Slack channel
    user_id: str                         # Current user
    # ... more fields
```

### Context Sources

#### 1. **LangGraph State** (`state`)
- Persisted in PostgreSQL via AsyncPostgresSaver
- Keyed by `thread_ts`
- Contains: draft, review_context, messages
- **Lifetime:** Entire thread/session

#### 2. **Conversation Context** (`conversation_context`)
- Fetched from Slack on-demand or from listening buffer
- Contains: messages array, summary, last_updated_at
- **Lifetime:** Injected per message, not persisted in state

#### 3. **Review Context** (`review_context`)
- Stored in LangGraph state
- Lifecycle: ACTIVE → CONTINUATION → APPROVED → POSTED
- **Lifetime:** From review start until decision posted

### Context Flow

```
User Message
  ↓
Fetch conversation_context from Slack
  ↓
Inject into state.conversation_context
  ↓
Run graph (nodes can access both state and conversation_context)
  ↓
Return result
  ↓
State persisted (WITHOUT conversation_context)
```

### Current Problems

1. **Conversation context not persisted**
   - Must refetch from Slack every message
   - Performance cost
   - Inconsistency if Slack data changes

2. **review_context is global per thread**
   - Can't have multiple reviews active
   - Can't switch between review topics

3. **No conversation threading**
   - Can't track: "This review", "That ticket", "The architecture from yesterday"

4. **State is append-only**
   - Old drafts accumulate
   - Old review contexts linger
   - No cleanup mechanism

---

## LLM Prompting Strategy

### LLM Usage Points

#### 1. **Intent Classification** (`src/graph/intent.py`)
**When:** Pattern matching fails
**Model:** Current default (Gemini)
**Context:** Just the current message + has_review_context flag
**Cost:** ~5 seconds, every message without pattern match

#### 2. **Ticket Extraction** (`src/graph/nodes/extraction.py`)
**When:** ticket_flow
**Model:** Current default
**Context:** User message + optional conversation_context
**Cost:** ~8 seconds per ticket

**Prompt Structure:**
```
Extract Jira ticket fields from this message:
[User message]

[Optional: Thread context if references detected]

Extract:
- title: Clear, specific title
- problem: What problem does this solve?
- solution: How will we solve it?
- acceptance_criteria: List of testable criteria
```

#### 3. **Architecture Review** (`src/graph/nodes/review.py`)
**When:** review_flow
**Model:** Current default
**Context:** User message + persona
**Cost:** ~14 seconds per review

**Prompt Structure:**
```
You are a [PERSONA] reviewing this proposal:
[User message]

Provide:
1. High-level assessment
2. Key considerations ([persona]-specific)
3. Risks and trade-offs
4. Alternatives to consider
5. Open questions for user
```

#### 4. **Review Continuation** (`src/graph/nodes/review_continuation.py`)
**When:** review_continuation_flow
**Model:** Current default
**Context:** Original review + full conversation history
**Cost:** ~16 seconds per continuation

**Prompt Structure:**
```
Original review: [review_summary]

FULL CONVERSATION HISTORY:
[conversation history]

Provide COMPLETE updated architecture incorporating all information:
1. Acknowledge answers
2. Present updated architecture with:
   - High-level approach
   - Components
   - Technical decisions
   - Risks and mitigations
   - Open questions
```

#### 5. **Validation** (`src/graph/nodes/validation.py`)
**When:** After extraction
**Model:** Current default
**Context:** Draft + persona context
**Cost:** ~7 seconds per validation

### Prompting Issues

1. **No prompt versioning**
   - Prompts are hardcoded strings
   - No A/B testing
   - No rollback mechanism

2. **Inconsistent prompt structure**
   - Some use triple quotes, some f-strings
   - Some have examples, some don't
   - No standard formatting

3. **Context window not optimized**
   - Full conversation history sent every time
   - No summarization
   - No token counting

4. **No caching**
   - Same context re-sent multiple times
   - Review summary sent on every continuation

5. **No streaming**
   - All responses wait for completion
   - User sees nothing until full response ready

---

## Decision Points & Heuristics

### Key Decision Rules

#### 1. **Should we create a ticket?**
**Location:** Intent classification
**Rule:**
```
IF explicit ticket pattern ("create ticket", "jira story")
   → TICKET
ELSE IF explicit review pattern ("propose architecture", "review as security")
   → REVIEW
ELSE IF has_review_context AND continuation pattern
   → REVIEW_CONTINUATION
ELSE → Ask LLM
   IF LLM unclear → Lean toward TICKET
```

**Issues:**
- "Lean toward TICKET" is aggressive
- No way to say "ask me which one"

#### 2. **Should we interrupt the graph?**
**Location:** `src/graph/runner.py`, line 147
**Rule:**
```python
if action in ["ask", "preview", "ready_to_create", "review", "discussion",
              "hint", "ticket_action", "review_continuation", "decision_approval"]:
    # Interrupt and return to handler
    return state
```

**Issues:**
- Hardcoded list
- No priority/ordering
- Can't have multi-step flows

#### 3. **Should we overwrite review_context?**
**Location:** `src/graph/nodes/review.py`
**Rule:**
```python
if review_context.state in [ACTIVE, CONTINUATION]:
    # Don't overwrite active review
    return review without saving context
else:
    # Save new review_context
```

**Issues:**
- No way to explicitly end review
- User must approve or it lingers forever

#### 4. **Should we use conversation context?**
**Location:** `src/graph/nodes/extraction.py`
**Rule:**
```python
if _detect_reference_to_prior_content(message):
    # Include conversation context in extraction
```

**Reference patterns:**
```python
r"\bthe\s+(?:architecture|review|analysis)\b"
r"\bthis\s+(?:architecture|review)\b"
r"\b(?:from|mentioned)\s+above\b"
```

**Issues:**
- Pattern-based detection is fragile
- Might miss: "based on our conversation", "like we discussed"

#### 5. **Should we post decision to channel?**
**Location:** `src/graph/nodes/decision_approval.py`
**Rule:**
```python
if DECISION_APPROVAL intent AND review_context exists:
    # Post to channel
    # Clear review_context
```

**Issues:**
- No preview of what will be posted
- No way to edit before posting

### Implicit Heuristics (Hidden in Code)

1. **One ticket per message**
   - No code path for multiple tickets
   - Extraction returns single Draft object

2. **Reviews don't create tickets**
   - review_flow and ticket_flow are separate
   - No transition between them

3. **Thread-scoped state**
   - All state keyed by thread_ts
   - No cross-thread awareness

4. **Synchronous execution**
   - One message → one graph run → one response
   - No background processing

---

## Known Issues & Limitations

### Critical Issues (Blocking User Goals)

#### 1. **No Multi-Ticket Creation**
**Problem:** Can't create epics + user stories in one request
**Example:** "create epics and user stories" → Creates 1 ticket
**Root Cause:** Flow is designed for single ticket
**Impact:** HIGH - Users manually create each ticket

#### 2. **No Review-to-Ticket Transition**
**Problem:** After architecture review, can't extract tickets from it
**Example:**
- Bot: [Architecture review with 5 components]
- User: "Create tickets for each component"
- Bot: Asks for acceptance criteria (ignores review)
**Root Cause:** No flow transition, no multi-ticket extraction
**Impact:** HIGH - Users repeat information

#### 3. **Review Context Confusion**
**Problem:** Bot doesn't know when review is "done"
**Example:**
- Review happens, user answers questions
- User says "thanks"
- Review context still active (CONTINUATION state)
- Later: User asks unrelated question
- Bot: Tries to continue review
**Root Cause:** No explicit review termination
**Impact:** MEDIUM - Confusing behavior

#### 4. **Intent Ambiguity**
**Problem:** "help to organize architecture" could mean review OR ticket
**Example:** User might want ticket but gets review
**Root Cause:** Pattern overrides LLM, no clarification
**Impact:** MEDIUM - User must rephrase

### Architectural Limitations

#### 1. **Single Flow Per Message**
- Can't do: Review → Approval → Ticket Creation in one flow
- Each step returns to user

#### 2. **No Hierarchical Understanding**
- Doesn't understand: Epic → User Story → Subtask
- Treats all tickets as flat

#### 3. **No Batch Operations**
- Can't create multiple tickets at once
- Each ticket requires separate message

#### 4. **Limited Memory**
- Only remembers current thread
- No cross-thread knowledge
- No learning from past interactions

#### 5. **Rigid State Machine**
- Phase is linear: COLLECTING → REVIEWING → READY
- Can't go backwards
- Can't branch

### Performance Issues

#### 1. **LLM Call Latency**
- Intent: ~5s
- Extraction: ~8s
- Review: ~14s
- Continuation: ~16s
- Total: Up to 40s for complex flows

#### 2. **Context Refetch**
- Fetches conversation_context from Slack every message
- Not cached, not persisted

#### 3. **No Streaming**
- User waits for full response
- No progress indication

---

## Refactoring Priorities

### Immediate (Phase 20)

#### 1. **Multi-Ticket Extraction**
**Goal:** "Create epics and user stories" → Creates epic + N stories
**Changes:**
- New intent: MULTI_TICKET
- New flow: multi_ticket_flow
- New extraction node variant: extract_multiple_tickets
- New prompt: "Extract multiple tickets with hierarchy"
- Handler: Create epic first, then stories with link

**Complexity:** HIGH
**Value:** HIGH
**Risk:** MEDIUM (new code paths)

#### 2. **Flow Transitions**
**Goal:** "Turn this review into tickets" works
**Changes:**
- Add transition edges in graph
- New intent: TRANSITION (meta-intent)
- Allow review_flow → ticket_flow
- Preserve context across transition

**Complexity:** MEDIUM
**Value:** HIGH
**Risk:** LOW (extends existing)

#### 3. **Explicit Review Termination**
**Goal:** User can say "end review" or "thanks, that's all"
**Changes:**
- New pattern: REVIEW_COMPLETE
- Update review_context.state = COMPLETE
- Clear context on completion
- Prevent continuation after completion

**Complexity:** LOW
**Value:** MEDIUM
**Risk:** LOW (small change)

### Medium Term (Phase 21-22)

#### 4. **Intent Clarification**
**Goal:** When ambiguous, ask user instead of guessing
**Changes:**
- New intent: AMBIGUOUS
- New flow: clarification_flow
- Post buttons: "Review" vs "Create Ticket"
- Resume after clarification

**Complexity:** MEDIUM
**Value:** HIGH
**Risk:** LOW (improves UX)

#### 5. **Hierarchical Ticket Understanding**
**Goal:** Bot understands Epic → Story → Subtask
**Changes:**
- Add ticket_type to Draft
- New field: parent_ticket_key
- Validation understands hierarchy
- Extraction can specify relationships

**Complexity:** HIGH
**Value:** MEDIUM
**Risk:** MEDIUM (changes data model)

#### 6. **Prompt Refactoring**
**Goal:** Consistent, versioned, testable prompts
**Changes:**
- Move prompts to separate module: `src/prompts/`
- Template system with variables
- Version tracking
- Unit tests for prompts

**Complexity:** MEDIUM
**Value:** LOW (internal quality)
**Risk:** LOW (refactoring)

### Long Term (Phase 23+)

#### 7. **Context Optimization**
**Goal:** Reduce LLM costs, improve latency
**Changes:**
- Summarize conversation instead of full history
- Cache LLM responses
- Token counting and limits
- Streaming responses

**Complexity:** HIGH
**Value:** MEDIUM
**Risk:** MEDIUM (changes behavior)

#### 8. **Multi-Round Flows**
**Goal:** Bot can have back-and-forth within a flow
**Changes:**
- Flows don't immediately interrupt
- Nodes can ask questions and wait for answers
- State machine becomes more complex

**Complexity:** VERY HIGH
**Value:** HIGH
**Risk:** HIGH (major rewrite)

#### 9. **Learning & Personalization**
**Goal:** Bot learns from user patterns
**Changes:**
- Track user preferences
- Adapt intent classification per user
- Remember past tickets for context

**Complexity:** VERY HIGH
**Value:** LOW (nice-to-have)
**Risk:** MEDIUM (privacy concerns)

---

## Recommended Phase 20 Scope

### Core Focus: Multi-Ticket Creation

**What to build:**

1. **Multi-Ticket Intent Detection**
   - Pattern: "create (epics|stories|tickets)" + plural indicators
   - LLM fallback for: "break this down into tickets"

2. **Hierarchical Extraction**
   - Extract: Epic + list of Stories
   - Parse architecture review into components
   - Generate ticket for each component

3. **Epic + Stories Flow**
   - Create epic first
   - Create stories with epic_link
   - Return summary: "Created EPIC-123 + 5 stories"

4. **Flow Transition Support**
   - "Turn this review into tickets"
   - "Create tickets from this architecture"
   - Carry context from review into ticket creation

**What to defer:**

- Subtask creation (too complex)
- Intent clarification (separate phase)
- Prompt refactoring (internal quality, not user-facing)
- Context optimization (performance, not functionality)

**Success Criteria:**

✅ User can say: "Create epics and user stories"
✅ Bot extracts epic + N stories from architecture discussion
✅ Bot creates epic first, then stories linked to epic
✅ User can transition from review to tickets: "Create tickets for this"

---

## Next Steps

1. ✅ **This document created** - Brain analysis complete
2. 🔄 **Review with user** - Confirm priorities
3. ⏭️ **Create Phase 20 CONTEXT.md** - Capture vision and requirements
4. ⏭️ **Create Phase 20 PLAN.md** - Detailed implementation plan
5. ⏭️ **Execute Phase 20** - Build multi-ticket + flow transition features

---

*Document version: 1.0*
*Last updated: 2026-01-15*
*Next review: Before Phase 20 planning*

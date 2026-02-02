# MARO 2.0 Bot Design: How It Thinks

This document explains the cognitive architecture of MARO — how it processes messages, makes decisions, and maintains state. A person reading this should understand the bot's "mental model."

---

## Table of Contents

1. [Core Philosophy](#core-philosophy)
2. [Mental Model: The Git Analogy](#mental-model-the-git-analogy)
3. [Two-Stage Intent Classification](#two-stage-intent-classification)
4. [Four SuperModes](#four-supermodes)
5. [Entity Lifecycle State Machine](#entity-lifecycle-state-machine)
6. [Decision-Making Rules](#decision-making-rules)
7. [Process Orchestration](#process-orchestration)
8. [Prompts Overview](#prompts-overview)
9. [Safety Guardrails](#safety-guardrails)

---

## Core Philosophy

**"Threads propose. Channels decide. Jira executes."**

MARO treats communication as the source of truth. The bot doesn't store work items — it stores *events* that describe what happened in conversations. Current state is derived by replaying these events.

### Key Principles

1. **Sum Types Over Optionals** — An entity is in exactly ONE state. There's no "maybe proposed" or "partially approved."

2. **Events Over State** — We never mutate. We append events and derive current state.

3. **Channel as Aggregate Root** — All mutations flow through the channel. The channel "owns" its entities.

4. **Facilitate, Don't Dictate** — The bot helps reach consensus. It doesn't force decisions.

5. **Explicit Over Implicit** — No magic. Every state transition is an event. Every decision is traceable.

---

## Mental Model: The Git Analogy

| Git Concept | MARO Equivalent |
|-------------|-----------------|
| Repository | Channel |
| Branch | Thread |
| Commit | Approval |
| HEAD | Canonical message |
| Push | Sync to Jira |
| Merge conflict | Decision conflict |

**Jira is not the source of truth** — it's a deployment artifact built from the source (conversation).

---

## Two-Stage Intent Classification

When a message arrives, MARO uses two stages to decide what to do:

### Stage 1: PreGates (Deterministic)

Fast, rule-based checks that short-circuit LLM calls:

```
Message arrives
    ↓
Is it a button click? → Handle button action
    ↓
Is it a slash command? → Handle command
    ↓
Is it in a known process thread? → Route to process
    ↓
Is it from the bot? → Ignore
    ↓
Pass to Stage 2
```

### Stage 2: LLM Router

For messages that pass PreGates, the LLM classifies intent:

```
Input: Message text + thread context + channel entities

Output: {
  mode: CREATE | MODIFY | RECORD | CONVERSE,
  confidence: 0.0-1.0,
  entity_type: work_item | decision | null,
  reasoning: "..."
}
```

**Confidence Threshold Rule:**
- If `confidence < 0.7` → Fall back to CONVERSE mode
- Never take action when uncertain

---

## Four SuperModes

Every message results in one of four modes:

### CREATE Mode
**Trigger:** User wants to define a new work item or decision
**Behavior:**
1. Extract structured content from conversation
2. Create Draft entity
3. Post formatted preview
4. Offer "Propose to channel" button

### MODIFY Mode
**Trigger:** User wants to change an existing entity
**Behavior:**
1. Identify target entity
2. Validate lifecycle allows modification (Draft or Proposed only)
3. Apply changes
4. Emit `EntityUpdated` event
5. Update canonical message

### RECORD Mode
**Trigger:** User made a decision that should be captured
**Behavior:**
1. Extract decision from context
2. Infer decision type (ARCHITECTURE, SCOPE, CONSTRAINT, etc.)
3. Create Decision entity
4. Link to affected entities
5. Post for approval

### CONVERSE Mode
**Trigger:** Casual conversation, questions, clarifications
**Behavior:**
1. Respond helpfully
2. DO NOT create entities
3. DO NOT emit events (except maybe `MessageReceived` for audit)
4. Maintain context for future intent detection

---

## Entity Lifecycle State Machine

Every entity (WorkItem or Decision) follows this lifecycle:

```
                    ┌─────────────┐
                    │    DRAFT    │
                    │  (thread)   │
                    └──────┬──────┘
                           │ propose()
                           ▼
                    ┌─────────────┐
                    │  PROPOSED   │◄──────────────┐
                    │  (channel)  │               │
                    └──────┬──────┘               │
                           │                      │
              ┌────────────┼────────────┐         │
              │            │            │         │
         objection()   approval()   withdraw()    │
              │            │            │         │
              ▼            ▼            │         │
        ┌─────────┐  ┌──────────┐      │         │
        │ BLOCKED │  │ APPROVED │      │         │
        │ (needs  │  │ (ready   │      │    modify()
        │ resolve)│  │ for Jira)│      │    (reopen)
        └────┬────┘  └────┬─────┘      │         │
             │            │            │         │
        resolve()    commit()          │         │
             │            │            │         │
             └────────────┼────────────┘         │
                          ▼                      │
                   ┌─────────────┐               │
                   │  COMMITTED  │───────────────┘
                   │  (in Jira)  │
                   └──────┬──────┘
                          │ deprecate() (decisions only)
                          ▼
                   ┌─────────────┐
                   │ DEPRECATED  │
                   │ (superseded)│
                   └─────────────┘
```

### Transition Rules

| Current State | Allowed Actions | Resulting State |
|---------------|-----------------|-----------------|
| DRAFT | propose, delete | PROPOSED, (deleted) |
| PROPOSED | approve, object, withdraw, modify | APPROVED, BLOCKED, DRAFT, PROPOSED |
| BLOCKED | resolve | PROPOSED |
| APPROVED | commit, modify | COMMITTED, PROPOSED |
| COMMITTED | deprecate (decisions) | DEPRECATED |
| DEPRECATED | (none) | (terminal) |

---

## Decision-Making Rules

### When to Create an Entity

**DO create** when:
- User explicitly asks ("create a story for...")
- User describes work with enough detail (title + some description)
- User states a decision with rationale

**DON'T create** when:
- User is asking questions
- User is brainstorming (no commitment)
- Confidence < 0.7
- Similar entity already exists in Draft

### When to Auto-Approve

**Never.** All approvals require human action via button click.

### When to Sync to Jira

Only when:
1. Entity is in APPROVED state
2. User clicks "Commit to Jira" button
3. No unresolved conflicts exist

### Conflict Detection

Check before commit:
1. **Overlapping decisions** — Two decisions affecting same entity/field
2. **Jira drift** — Entity changed in Jira since last sync
3. **Superseded decisions** — Decision references deprecated decision

---

## Process Orchestration

For complex workflows (like architecture review), MARO uses multi-stage processes:

### Process Structure

```
Process
  ├── Stage 1: Gather Context
  │     └── Questions, document review
  ├── Stage 2: Analysis
  │     └── LLM analysis, pattern matching
  ├── Stage 3: Recommendations
  │     └── Generate decision drafts
  └── Stage 4: Approval
        └── User reviews, approves/rejects
```

### Process Types

| Process | Trigger | Stages | Output |
|---------|---------|--------|--------|
| `work_item_creation` | CREATE mode for work item | Extract → Refine → Propose | WorkItem entity |
| `decision_creation` | RECORD mode | Capture → Contextualize → Propose | Decision entity |
| `architecture_review` | User requests review | Gather → Analyze → Recommend → Approve | Multiple decisions |

### Plan Execution

Within a process, plans execute specific actions:

```python
Plan:
  - create_entity(type=DECISION, content={...})
  - post_message(channel, formatted_preview)
  - wait_confirmation(timeout=24h)
  - on_approved: sync_to_jira()
```

---

## Slack Integration Layer

### Message Flow

```
Slack -> POST /slack/events -> Bolt AsyncApp -> Handler -> SlackClient -> Slack
```

**Inbound Flow:**
1. Slack sends events to `/slack/events` endpoint
2. Bolt handles signature verification automatically
3. Event routed to appropriate handler:
   - `@app.event("message")` - Message events
   - `@app.event("app_mention")` - @mentions
   - `@app.action(pattern)` - Button clicks
   - `@app.command("/maro")` - Slash commands
4. Handler processes event and responds via SlackClient

**Outbound Flow:**
1. Handler calls `SlackClient.send(message_type, channel_id, content)`
2. SlackClient routes based on `WRITE_TARGETS` mapping:
   - CHANNEL: Permanent, visible to all
   - THREAD: Conversation context
   - EPHEMERAL: Only visible to one user
3. Rate limiter ensures 1 msg/sec limit respected
4. Message posted to Slack

### Handler Types

| Handler | Trigger | Response Type |
|---------|---------|---------------|
| Message | User sends message | Thread (conversation_response) |
| App Mention | @MARO in message | Thread |
| Button Action | Approve/Object/Discuss click | Thread (ack + feedback) |
| Slash Command | /maro command | Ephemeral (command_help) |

### Critical Rules

1. **ack() First**: All action/command handlers MUST call `ack()` as first line. Slack times out after 3 seconds.

2. **Check bot_id**: Message handlers MUST check `event.get("bot_id")` to avoid infinite loops.

3. **Use thread_ts**: Always respond in the correct thread using `thread_ts` from the event.

4. **Rate Limiting**: All outbound messages go through RateLimiter (1/sec).

### Message Type Routing

| Message Type | Target | Example |
|--------------|--------|---------|
| entity_proposed | CHANNEL | "New story proposed: ..." |
| entity_approved | CHANNEL | "Story approved by @user" |
| question_asked | THREAD | "What's the priority?" |
| draft_preview | THREAD | "Here's the draft..." |
| command_help | EPHEMERAL | "/maro help output" |
| error_message | EPHEMERAL | "You don't have permission" |

### Dashboard

Each channel has a pinned status dashboard showing:
- Pending approvals (count + first 5)
- Committed items in Jira (count + first 5)
- Active decisions (count)
- Last updated timestamp

Dashboard is updated when entities change lifecycle state.

---

## Prompts Overview

### Intent Classification Prompt

```
You are classifying the user's intent in a Slack conversation about software development.

Context:
- Channel: {channel_name}
- Thread: {thread_summary}
- Recent messages: {messages}
- Existing entities: {entity_summaries}

Message to classify: "{message_text}"

Classify into one of:
- CREATE: User wants to define a new work item or decision
- MODIFY: User wants to change an existing entity
- RECORD: User made a decision that should be captured
- CONVERSE: Casual conversation, questions, clarifications

Output JSON:
{
  "mode": "CREATE|MODIFY|RECORD|CONVERSE",
  "confidence": 0.0-1.0,
  "entity_type": "work_item|decision|null",
  "target_entity_id": "uuid|null",
  "reasoning": "Brief explanation"
}

Rules:
- If uncertain, choose CONVERSE
- Never hallucinate entity IDs
- Consider thread context for intent
```

### Content Extraction Prompt (CREATE mode)

```
Extract structured work item content from this conversation.

Conversation:
{thread_messages}

Extract:
{
  "issue_type": "epic|story|task|bug|spike",
  "title": "Concise title (max 80 chars)",
  "description": "Detailed description",
  "acceptance_criteria": ["AC1", "AC2", ...],
  "constraints": ["Constraint1", ...]
}

Rules:
- Title should be actionable ("Add...", "Fix...", "Implement...")
- Stories require acceptance criteria
- Don't invent details not in conversation
- Mark uncertainty with [NEEDS CLARIFICATION]
```

### Decision Detection Prompt (RECORD mode)

```
Analyze if this message contains an architectural decision.

Context:
{thread_context}

Message: "{message_text}"

A decision is a CHOICE or COMMITMENT, not just information or opinion.

Output:
{
  "is_decision": true|false,
  "decision_type": "ARCHITECTURE|SCOPE|CONSTRAINT|PRIORITY|PROCESS|STRUCTURE",
  "title": "Decision title",
  "description": "What was decided",
  "rationale": "Why (from context)",
  "confidence": 0.0-1.0
}

Examples:
- "Let's use PostgreSQL" → Decision (ARCHITECTURE)
- "I think PostgreSQL might work" → NOT a decision (opinion)
- "We won't support IE11" → Decision (SCOPE/CONSTRAINT)
- "Should we support IE11?" → NOT a decision (question)
```

---

## Safety Guardrails

### What the Bot Will Never Do

1. **Create without confidence** — If confidence < 0.7, falls back to conversation
2. **Auto-approve** — All approvals require explicit human action
3. **Sync without approval** — Only APPROVED entities can go to Jira
4. **Delete without confirmation** — Destructive actions need explicit confirmation
5. **Override objections** — Objections block until resolved

### Safe Defaults

| Situation | Behavior |
|-----------|----------|
| LLM returns invalid JSON | Retry once with repair prompt, then CONVERSE |
| Unknown intent | CONVERSE mode |
| Entity not found | Report error, don't hallucinate |
| Jira sync fails | Mark CONFLICT, notify user |
| Rate limited | Back off, queue for retry |

### Audit Trail

Every action produces an event that captures:
- What happened
- Who did it
- When
- Why (correlation to triggering message)
- What changed

Events are immutable. The audit trail is complete.

---

## Summary

MARO thinks in terms of:

1. **Events** — What happened (immutable, append-only)
2. **Entities** — Current state (derived from events)
3. **Modes** — What to do with a message (CREATE/MODIFY/RECORD/CONVERSE)
4. **Lifecycle** — Where an entity is in its journey (Draft → Approved → Committed)
5. **Processes** — Multi-step workflows for complex actions

The bot's job is to:
- Listen to conversations
- Detect when decisions are being made
- Capture them as structured entities
- Guide them through approval
- Project them to Jira

It does this while staying out of the way — facilitating consensus, not forcing it.

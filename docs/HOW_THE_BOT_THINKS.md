# How MARO Thinks: Complete Bot Intelligence Guide

This document explains the complete decision-making logic, rules, prompts, and behavior patterns of the MARO (Managed Automated Requirements Orchestrator) Slack bot.

---

## Table of Contents

1. [Core Architecture](#1-core-architecture)
2. [Intent Classification](#2-intent-classification)
3. [Governance Rules](#3-governance-rules)
4. [LLM Prompts Reference](#4-llm-prompts-reference)
5. [State Machine & Workflows](#5-state-machine--workflows)
6. [Decision Logic](#6-decision-logic)
7. [Response Generation](#7-response-generation)
8. [Key Behavior Patterns](#8-key-behavior-patterns)

---

## 1. Core Architecture

### 1.1 High-Level Flow

```
User Message
    ↓
Event Router (pre-graph filtering)
    ↓
Intent Classification (LLM)
    ↓
Graph Routing (LangGraph)
    ├─→ Ticket Flow (extraction → validation → decision)
    ├─→ Review Flow (persona-based analysis)
    ├─→ Discussion Flow (brief conversational)
    ├─→ Scope Gate Flow (ambiguous → 3-button UI)
    ├─→ Jira Command Flow (field modifications)
    ├─→ Sync Flow (bulk channel sync)
    └─→ Jira Search Flow (search existing)
    ↓
Slack Response
```

### 1.2 Identity & State

**Canonical Identity:** `session_id = team:channel:thread_ts`

Every interaction is tracked per-thread with:
- Step count (loop protection, MAX_STEPS = 10)
- Phase (COLLECTING, AWAITING_USER, APPROVED, REJECTED)
- Draft state (accumulated requirements)
- Pending questions (for re-ask logic)
- Workflow step (for button validation)

### 1.3 Git Model

MARO follows a Git-like model for truth management:

| Git Concept | MARO Equivalent | Description |
|-------------|-----------------|-------------|
| Repository | Channel | Source of truth, owns work item registry |
| Working Tree | Thread | Exploration/drafting space |
| Commit | Approved Decision | Immutable truth entry in channel log |
| Remote | Jira | Deployment target (replica of truth) |
| Push | Sync/Publish | Propagate truth to Jira |

**Key insight:** Jira is not the source of truth. Jira is where truth gets *deployed* after being decided in the channel.

**Mantra:** "Threads propose. Channels decide. Jira executes."

```
Thread: "We need rate limiting"
    ↓ (draft)
Channel: "Approved as WORK-123"
    ↓ (sync)
Jira: "SCRUM-456 created"
```

### 1.4 LLM Providers

The bot uses a provider-agnostic adapter layer supporting:

| Provider | Default Model | Use Case |
|----------|--------------|----------|
| Gemini | `gemini-3-flash-preview` | Primary (default) |
| OpenAI | `gpt-4o-mini` | Backup |
| Anthropic | `claude-3-5-sonnet-latest` | Backup |

**Default Parameters:**
- Temperature: 0.7
- Max tokens: 4096
- Timeout: 30 seconds

---

## 2. Intent Classification

### 2.1 Intent Types

The bot classifies every message into one of 9 intent types:

| Intent | Description | Example |
|--------|-------------|---------|
| **TICKET** | Create NEW Jira ticket | "create a ticket for authentication" |
| **TICKET_ACTION** | Create items linked to existing ticket | "create stories for SCRUM-123" |
| **JIRA_COMMAND** | Modify existing ticket fields | "change priority to high" |
| **SYNC_REQUEST** | Bulk sync channel with Jira | "update Jira issues" |
| **JIRA_SEARCH** | Search Jira for existing issues | "check if we have a ticket for this" |
| **REVIEW** | Analysis/feedback without Jira ops | "help me design the API" |
| **DISCUSSION** | Greeting or simple question | "hi", "thanks" |
| **META** | Questions about the bot | "what can you do?" |
| **AMBIGUOUS** | Truly unclear intent (rare) | Shows scope gate UI |

### 2.2 Intent Classification Prompt

```
You are classifying user intent for a Slack bot that helps with Jira tickets
and architecture discussions.

CONVERSATION CONTEXT:
{summary + last 15 messages}

CURRENT USER MESSAGE: "{message}"

Classify the user's intent into ONE category:

- SYNC_REQUEST: User wants to SYNC channel decisions with Jira (bulk update)
  Key phrases: "update Jira issues", "sync Jira", "sync tickets"

- JIRA_COMMAND: User wants to CHANGE/MODIFY an existing Jira ticket's field values
  Key verbs: change, update, set, modify, edit, delete, remove, close, mark
  Key fields: priority, status, assignee, description, summary, labels

- TICKET_ACTION: User wants to CREATE NEW items linked to an existing ticket
  Examples: "create stories for SCRUM-123", "add subtasks"

- TICKET: User wants to create a NEW Jira ticket (no existing ticket referenced)

- JIRA_SEARCH: User wants to SEARCH Jira for existing issues
  Key phrases: "check Jira", "do we have a ticket", "similar issue"

- REVIEW: User wants help, analysis, discussion, or feedback
  This is the DEFAULT for most help/discussion requests!

- DISCUSSION: Pure greeting with no actionable request

- META: Questions about the bot itself

- AMBIGUOUS: ONLY when truly unclear (should be RARE)

IMPORTANT RULES:
1. "Help me with X" or "I need help with X" = REVIEW (not AMBIGUOUS)
2. When in doubt between REVIEW and AMBIGUOUS, choose REVIEW
3. TICKET requires EXPLICIT new ticket creation language
4. For contextual references ("that ticket"), extract from CONVERSATION CONTEXT

Respond in this exact format:
INTENT: <...>
CONFIDENCE: <0.0-1.0>
PERSONA: <pm|architect|security|none>
TICKET_KEY: <SCRUM-123 or "none">
ACTION_TYPE: <create_stories|create_subtask|update|add_comment|none>
COMMAND_TYPE: <update|delete|none>
COMMAND_FIELD: <priority|status|assignee|none>
COMMAND_VALUE: <value or "none">
SEARCH_QUERY: <query or "none">
REASON: <brief explanation>
```

### 2.3 Classification Rules

1. **Default to REVIEW** - When uncertain, classify as REVIEW (not AMBIGUOUS)
2. **Context-aware** - Extracts ticket keys from conversation history for contextual references
3. **Persona detection** - Captures PM/Architect/Security hints for review personas
4. **Metadata extraction** - Extracts command fields, search queries, action types

---

## 3. Governance Rules

### 3.1 Core Model (Phase 23 - Current)

#### Channel = Source of Truth
> Channel owns a registry of WorkItems, not just Epics

The model shifted from "thread binds to Epic" to "Channel owns WorkItems":

- **Channel** contains a registry of WorkItems (0..N): Epics, Stories, Bugs, Tasks, Spikes
- **Thread** is a working branch where exploration/drafting happens
- **Jira** is a projection/replica of channel truth (not the source)

| Entity | Role |
|--------|------|
| Channel | Source of truth, owns WorkItem registry |
| Thread | Working session, drafts committed to channel |
| Jira | Execution replica, receives "deployments" |

#### Rule 1: WorkItem Registry (replaces Epic binding)
> Contribution binds to WorkItem (any type), not just Epic

- WorkItem types: Epic, Story, Bug, Task, Spike
- Each has: local_id, jira_key (nullable), status (draft/active/done), summary, facts
- **Drafts are first-class citizens** - live in registry, sync to Jira only on explicit action
- No orphan contributions - everything lands in a WorkItem or Untriaged Inbox
- Status: **IMPLEMENTED** (WorkItemStore)

#### Rule 2: Traffic Cop / Dedup
> Suggest similar threads without blocking workflow

- Only triggers on extremely high similarity (0.85+ threshold)
- Non-blocking suggestions: "Related thread exists; want me to link it?"
- Logs similarity score and rationale
- Status: **NON-BLOCKING**

#### Rule 3: Explicit Approval (Commit Semantics)
> Nothing becomes channel truth without explicit approval

- MARO detects "significant events" (decision approved, ticket created)
- Shows commit preview with summary
- User clicks "Approve & Commit"
- Entry added to Channel Work Board log
- **No silent auto-commits**
- Status: **ENFORCED**

#### Rule 4: Aggregation
> Write to Epic description in batches with full changelog

- Batch writes (per N decisions or manual command)
- Every write includes changelog entry + source thread links
- Status: **BATCH WRITES**

### 3.2 Duplicate Handling Rules (Phase 23)

#### Rule 6: Blocking Duplicate Detection
> Block ticket creation on EXACT_MATCH duplicates until user explicitly chooses

| Match State | Confidence | Behavior |
|-------------|------------|----------|
| EXACT_MATCH | >85% | **Blocks creation** until user chooses |
| LIKELY_DUPLICATE | 60-85% | Shows warning, allows creation |
| NO_MATCH | <60% | Proceeds normally |

**Confidence Scoring:**
```python
score = 0.0
# Title word overlap (up to 0.5)
# Problem description overlap (up to 0.3)
# Active ticket boost (up to 0.2)
```

#### Rule 7: Explicit Choice Buttons
> Force explicit user decision with 3 choices

For EXACT_MATCH:
- **Link to existing** (Primary, Recommended)
- **Update existing with new info**
- **Create new anyway** (Danger, requires confirmation)

For LIKELY_DUPLICATE:
- Same buttons, equal weight (no recommendation)

### 3.3 Registry Rules

#### Rule 8: Channel Jira Registry
> Channel explicitly owns list of Jira issues (central to new model)

This is the **key implementation** of the "Channel = Source of Truth" model:

| Link Type | Description |
|-----------|-------------|
| `owned` | Created from this channel (primary owner) |
| `tracked` | Explicitly tracked via `/maro track` command |
| `mentioned` | Referenced in discussions (passive) |

**Key Properties:**
- Central, queryable registry per channel
- Not scattered across multiple stores
- Includes both synced (has jira_key) and draft (no jira_key) items
- Supports WorkItems of any type: Epic, Story, Bug, Task, Spike

### 3.4 Context Rules

#### Rule 15: Complete Channel Snapshot
> Include ALL active work items in context, not just last 10

Enhanced snapshot includes:
- All active epics with child counts
- Work items grouped by status
- Item counts by type (epic: 5, story: 12, bug: 3)
- Up to 50 recent tickets (increased from 10)

### 3.5 Commit Semantics

#### What is a Commit?

A **commit** is an approved decision that becomes channel truth. Commits are:
- Immutable once created
- Linked to source thread
- Optionally synced to Jira

#### Commit Triggers

| Event | Creates Commit? |
|-------|-----------------|
| Draft approved | Yes |
| WorkItem created | Yes |
| Decision approved | Yes |
| Review approved | Yes (as artifact) |
| Jira field updated | Yes (change record) |
| Discussion message | No |

#### Commit Structure

```python
class Commit:
    commit_id: str
    channel_id: str
    source_thread_ts: str
    commit_type: Literal["workitem", "decision", "artifact", "change"]
    summary: str
    details: dict
    created_at: datetime
    created_by: str
    jira_synced: bool
    jira_key: Optional[str]
```

#### Commit Log

Each channel maintains a commit log (append-only):

```
[2026-01-22 10:30] WORKITEM: Created "Rate limiting API" (draft)
[2026-01-22 10:45] DECISION: Approved rate limiting approach
[2026-01-22 11:00] WORKITEM: Published to Jira as SCRUM-456
[2026-01-22 14:00] CHANGE: Updated priority High → Critical
```

#### Relation to Jira Sync

- Commits exist independently of Jira
- `jira_synced=false` means local-only truth
- Sync is explicit: "Publish to Jira" or `/maro sync`
- Jira updates flow back as CHANGE commits

---

## 4. LLM Prompts Reference

### 4.1 System Identity

```
You are a requirements orchestrator. Your role is to:
1. Capture decisions from conversations
2. Build complete, unambiguous work items
3. Maintain channel truth (the registry of work items)
4. Sync truth to external systems (Jira) on explicit request

Core principle: Chat is the source of truth. Jira is where truth gets deployed.

You work with these work item types:
- Epic: High-level features (needs: summary, description)
- Story: User-facing features (needs: summary, description, acceptance_criteria)
- Task: Technical work (needs: summary, description)
- Bug: Defects (needs: summary, description, steps_to_reproduce, expected/actual behavior)
- Spike: Research/exploration (needs: summary, question to answer)

Be conversational, not robotic. Ask one question at a time when possible.
Never create half-baked items. Never auto-sync without explicit approval.
```

### 4.2 Extraction Prompt

```
You are extracting requirements from a conversation to build a Jira ticket draft.

Current draft state:
{draft_json}

{conversation_context}

New message to process:
{message}

Extract any new information that should update the draft. Return a JSON object
with ONLY the fields that have new information. Do not repeat existing values.

Fields you can update:
- title: Clear, concise ticket title
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria
- constraints: List of {"key", "value"} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks

Return empty object {} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message. Do not invent or assume.
```

### 4.3 Validation Prompt

```
You are a Jira ticket validator. Review this draft for completeness and conflicts.

Current draft:
{draft_json}

Channel context:
{channel_context}

Validate the draft and return:
1. is_valid: boolean - Does it meet MINIMUM requirements?
2. missing_fields: list - What's still needed?
3. conflicts: list - Any logical contradictions?
4. suggestions: list - Optional improvements
5. quality_score: 0-100

MINIMUM REQUIREMENTS (must ALL be present for is_valid=true):
- title: Clear, concise (not empty)
- problem: Describes what needs solving (not empty)
- acceptance_criteria: At least 1 testable criterion

DO NOT require:
- proposed_solution (optional - user may want team to decide)
- constraints/dependencies/risks (optional extras)

Return JSON matching the ValidationReport schema.
```

### 4.4 Review Prompt (Persona-Based)

```
You are an experienced {persona} reviewing a software architecture or design proposal.

Topic: {topic}
User's question/request: {message}

Provide a thoughtful analysis covering:

1. **Understanding** - Confirm what you understand about the proposal
2. **Components & Flows** - Key elements and how they interact
3. **Risks** - Technical, operational, or business concerns
4. **Alternatives** - Other approaches worth considering
5. **Open Questions** - What needs clarification?

Keep your response focused and actionable. Use bullet points.

FORMATTING RULES (for Slack):
- Use *single asterisks* for bold (not **double**)
- Use - for bullet points
- Keep sections short (2-4 bullets each)
```

### 4.5 Question Generation

```
Generate 1-2 clarifying questions to gather the missing information.

Questions should be:
- Specific and actionable
- Prioritized by importance
- Natural and conversational

Focus on: {missing_fields}
```

### 4.6 Answer Matching

```
Match the user's response to the numbered questions that were asked.

Questions asked:
{questions_with_numbers}

User's response:
{response}

For each question, determine:
- Did the user answer it? (yes/partial/no)
- What was their answer?
- Confidence (0.0-1.0)

Special signals:
- "you decide" / "propose something" = [GENERATE] delegation
- "not sure" / "don't know" = [SKIP] acknowledgment
```

### 4.7 Discussion Response

```
You are a helpful Slack bot. The user has sent a casual message or greeting.

Message: {message}

Respond briefly (1-2 sentences max). Be friendly and helpful.
If they seem to want something specific, ask what you can help with.
```

### 4.8 Story Generation

```
You are breaking down a Jira Epic into User Stories.

Epic:
{epic_summary}
{epic_description}

Create {count} independent user stories. Each story should:
- Follow "As a [user], I want [goal], so that [benefit]" format
- Be independently deliverable
- Have clear acceptance criteria

Return as JSON array:
[
  {"summary": "...", "description": "...", "acceptance_criteria": ["...", "..."]}
]
```

### 4.9 Duplicate Explanation

```
Explain in 1 sentence (max 80 chars) why this draft matches the existing ticket.

Draft title: {draft_title}
Draft problem: {draft_problem}

Existing ticket:
Key: {existing_key}
Summary: {existing_summary}
Status: {existing_status}

Focus on: What makes them similar? Be specific and concise.
```

---

## 5. State Machine & Workflows

### 5.1 Main Graph Structure (LangGraph)

```
START
  → intent_router (LLM classification)
  → [conditional routing]
    ├─ ticket_flow
    │    → extraction (update draft from message)
    │    → [should_continue?]
    │    │   ├─ extraction (loop for more info)
    │    │   ├─ validation (have enough data)
    │    │   └─ end (max steps or intro action)
    │    → validation (check completeness)
    │    → decision (route to ask/preview/preflight)
    │    → END
    │
    ├─ review_flow
    │    → review (persona-based analysis)
    │    → END
    │
    ├─ discussion_flow
    │    → discussion (brief response)
    │    → END
    │
    ├─ scope_gate_flow
    │    → scope_gate (show 3-button UI)
    │    → END
    │
    ├─ ticket_action_flow
    │    → ticket_action (create stories/subtasks)
    │    → END
    │
    ├─ jira_command_flow
    │    → jira_command (modify fields)
    │    → END
    │
    ├─ jira_search_flow
    │    → jira_search (search existing)
    │    → END
    │
    └─ sync_flow
         → sync_trigger (bulk sync)
         → END
```

### 5.2 Ticket Flow Detail

```
extraction
    ↓
should_continue? ──→ Loop back to extraction if:
    │                 - Just intro/nudge (no real content yet)
    │                 - Pending questions answered
    │                 - More context needed
    │
    ↓ (have enough data)
validation
    ↓
decision ──→ Routes to:
    │         - ASK (need more questions)
    │         - PREVIEW (draft ready for approval)
    │         - PREFLIGHT (exact duplicate found)
    │         - READY (approved, create in Jira)
    ↓
END (Slack handler sends response)
```

### 5.3 Workflow Steps (Button Validation)

Each workflow step has allowed actions:

| Step | Allowed Actions |
|------|-----------------|
| DRAFT_PREVIEW | approve, reject, edit, duplicate_use, duplicate_new |
| MULTI_TICKET_PREVIEW | approve, edit_story, cancel, confirm_quantity |
| DECISION_PREVIEW | approve, edit, cancel |
| REVIEW_ACTIVE | show_full, approve_decision, turn_into_ticket |
| REVIEW_FROZEN | *No actions allowed* |
| SCOPE_GATE | select_review, select_ticket, dismiss, remember |
| UPDATE_PREVIEW | update_preview_apply, update_preview_edit, update_preview_cancel |

---

## 6. Decision Logic

### 6.1 Decision Node Flow

```python
def decision_node(state):
    # 1. Check thread binding first
    if thread_bound_to_ticket:
        skip_duplicate_detection()

    # 2. Check re-ask logic
    if unanswered_questions and reask_count < MAX_REASK_COUNT:
        return ASK (re-ask unanswered questions)

    # 3. If max re-asks reached
    if reask_count >= MAX_REASK_COUNT:
        proceed_with_partial_info()  # → PREVIEW

    # 4. Validate draft
    if conflicts_exist:
        return ASK (resolve conflicts first)

    if missing_required_fields:
        return ASK (batch questions, max 3)

    # 5. Draft is valid - check duplicates
    duplicates, confidence = search_for_duplicates(draft)
    preflight = PreflightResult.from_search_results(duplicates, confidence)

    if preflight.should_block_creation():  # >85% confidence
        return PREFLIGHT_REQUIRED (block until user chooses)

    if preflight.should_warn():  # 60-85% confidence
        return PREVIEW (with duplicate warning)

    return PREVIEW (normal, no duplicates)
```

### 6.2 Extraction Continuation Logic

```python
def should_continue(state):
    action = state.get("extraction_action")
    step_count = state.get("step_count", 0)

    # Stop conditions
    if step_count >= MAX_STEPS:
        return "validation"

    if action in ("intro", "nudge", "hint"):
        return "end"  # Don't loop on contextual hints

    # Continue conditions
    if action == "extract":
        return "validation"  # Have content, validate it

    if action == "generate":
        return "validation"  # Generated content, validate it

    return "extraction"  # Loop for more info
```

### 6.3 Question Batching

Questions are batched and prioritized:

```python
def batch_questions(questions):
    # Priority order:
    # 1. Conflicts (highest priority)
    # 2. Missing required fields (title, problem, acceptance_criteria)
    # 3. Optional improvements (suggestions)

    # Batch size: max 3 questions per ask
    return questions[:3]
```

---

## 7. Response Generation

### 7.1 Dispatch Actions

| Action | Handler | Response Type |
|--------|---------|---------------|
| `ask` | `SkillDispatcher.ask_user` | Questions in modal/blocks |
| `preview` | `SkillDispatcher.show_draft` | Draft blocks + approve/reject |
| `preflight` | `build_preflight_blocks` | Duplicate UI + 3 choice buttons |
| `ready` | Simple message | "Ticket approved and ready" |
| `review` | Chunked blocks | Analysis + approve/edit buttons |
| `discussion` | Simple message | Brief conversational response |
| `scope_gate` | Blocks | 3-button choice UI |
| `jira_command` | Command confirmation | Preview + confirm button |

### 7.2 Slack Block Chunking

Long responses are chunked for Slack's 2900 char limit:

```python
def chunk_response(text, max_chars=2900):
    # Priority: paragraph breaks > line breaks > word breaks
    chunks = []
    # Action buttons only on last chunk
    return chunks
```

### 7.3 Preflight UI (EXACT_MATCH)

```
┌─────────────────────────────────────────────────┐
│ ⚠️ *EXACT MATCH FOUND* (92% confident)          │
│ This appears to be an existing task.            │
├─────────────────────────────────────────────────┤
│ *SCRUM-123*: Similar title                      │
│ Status: *In Progress* | Assignee: @user         │
├─────────────────────────────────────────────────┤
│ 💡 *Match reason:* Both address auth flow       │
├─────────────────────────────────────────────────┤
│ *What would you like to do?*                    │
│                                                 │
│ [Link to SCRUM-123 (Recommended)]  [primary]    │
│ [Update SCRUM-123 with new info]               │
│ [Create new anyway ⚠️]             [danger]     │
└─────────────────────────────────────────────────┘
```

---

## 8. Key Behavior Patterns

### 8.1 Context Injection

Context is injected at multiple points:
- **Intent classification** - Last 15 messages + summary
- **Extraction** - Channel context (epics, conventions, rules)
- **Validation** - Channel constraints and naming conventions
- **Review** - Prior discussion and review artifacts

### 8.2 Conversation-Aware Extraction

```python
# Answer matching
if pending_questions:
    matches = await match_answers(user_response, pending_questions)
    # Correlates responses to numbered questions
    # Detects [GENERATE] delegation signals
    # Detects [SKIP] acknowledgments

# Reference detection
if references_prior_content(message, ["the architecture", "this review"]):
    use_extraction_with_reference_prompt()
```

### 8.3 Human-in-the-Loop Interrupts

Graph interrupts at key points for human decision:
- **ASK** - Need more information
- **PREVIEW** - Draft ready for approval
- **PREFLIGHT** - Duplicate found, need choice
- **SCOPE_GATE** - Ambiguous intent, need clarification

State is persisted via checkpointer for resume.

### 8.4 Idempotency & Stale UI

```python
# Event deduplication
if event_id in processed_events:
    reject_duplicate()

# Workflow step validation
if button_action not in allowed_actions[current_step]:
    show_stale_ui_error()

# Version checking
if action_version != state_version:
    show_outdated_error()
```

### 8.5 Persona-Based Responses

Review intents route to personas with different perspectives:

| Persona | Focus Areas |
|---------|-------------|
| **PM** | Requirements, user value, scope |
| **Architect** | System design, scalability, patterns |
| **Security** | Vulnerabilities, auth, data protection |

Persona is detected from message content or explicitly specified.

### 8.6 Smart Duplicate Detection

```python
def compute_confidence(draft, duplicate):
    score = 0.0

    # Title word overlap (up to 0.5)
    overlap = title_words & dup_words
    score += (overlap / max_words) * 0.5

    # Problem description overlap (up to 0.3)
    if problem_overlaps:
        score += 0.3

    # Active ticket boost (up to 0.2)
    if status in ("To Do", "In Progress"):
        score += 0.2
    elif status in ("Done", "Closed"):
        score += 0.05  # Lower for closed tickets

    return min(score, 1.0)
```

---

## Summary

MARO's intelligence is built on:

1. **LLM-powered intent classification** with 9 distinct types
2. **Rule-based governance** ensuring consistent behavior
3. **Graph-based workflows** with conditional routing
4. **Smart duplicate detection** preventing redundant work
5. **Human-in-the-loop** interrupts for critical decisions
6. **Context-aware extraction** building understanding progressively
7. **Persona-based analysis** for different perspectives

The system is designed to be **conversational**, **non-blocking**, and **transparent** - always explaining its reasoning and giving users explicit choices.

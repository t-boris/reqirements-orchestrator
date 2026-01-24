# Proactive Jira Analyst Bot

## What This Is

A Slack bot that acts as a collective thinking system where communication is the source of truth. Drives conversations in threads to gather complete requirements, creates Jira tickets when information is sufficient, and maintains bidirectional sync between Slack discussions and Jira issues.

## How the Bot Thinks

### The Git Mental Model

MARO treats communication like source control:

| Concept | Git | MARO |
|---------|-----|------|
| Repository | Codebase | Channel |
| Branch | Feature branch | Thread |
| Commit | Code commit | Approval (draft → WorkItem) |
| HEAD | Current state | Canonical message |
| Push | Deploy to remote | Sync to Jira |

**Key insight:** Jira is not the source of truth — it's a *projection* of what became truth in communication. Like a build artifact from source code.

### Three Layers of Truth

```
Channel (Workspace)     ← Source of Truth
    ↓
Thread (Working Branch) ← Where decisions form
    ↓
Jira (Projection)       ← Execution artifact
```

**Threads propose. Channels decide. Jira executes.**

### Decision Lifecycle

Decisions flow through four psychological states:

1. **Idea** → Compact card in discussion (lightweight, tentative)
2. **Proposal** → Full block for approval ("are you sure?" moment)
3. **Law** → Authoritative reference (infrastructure, not conversation)
4. **Record** → Commit log entry (pure signal, audit trail)

Same object, four visual identities. The channel becomes a live state board.

### Canonical Message Pattern

Each Decision has ONE message in the channel — like HEAD in git:
- Always reflects current version
- Never deleted, only updated or marked deprecated
- Thread underneath = working area for discussion
- Channel shows "what is true now", not "what happened"

### Draft as Design Object

Drafts are not text containers. They are typed data structures:

```
StructuredDraft
  ├── kind: SINGLE_ITEM | PLAN
  ├── scope: SINGLE | EPICS_ONLY | FULL_PLAN
  ├── lifecycle: EMPTY → SINGLE_ITEM → PLAN → APPROVED → COMMITTED
  └── items: [DraftItem with status, type, fields]
```

User choices mutate the structure (split, merge, elevate, decompose), not just append text.

### Multi-Intent Task Orchestration

The bot parses the full universe of user intent, not just top-1 classification:

```
User: "create stories from the decisions and check for duplicates"
       ↓
TaskPlan:
  ├── Task 1: Check duplicates (OPERATE, auto-execute)
  ├── Task 2: Create stories (BUILD, requires approval)
  └── depends_on: [1 → 2]
```

**Canonical UX response:**
```
I see 2 actions:
1. Check Jira duplicates
2. Create stories from decisions

Executing 1 now. For 2 — OK?
```

**Safety Classification:**

| Mode | Safety Level | Side Effects |
|------|--------------|--------------|
| THINK, CHAT | AUTO_EXECUTE | None, Slack only |
| BUILD, OPERATE, DECIDE | REQUIRES_CONFIRMATION | Jira, Registry |

Safe tasks run immediately. Dangerous tasks block for approval. Version-bound buttons prevent stale clicks.

**Status Card:** Single editable message showing all tasks with live status updates (throttled to 1.5s to avoid Slack rate limits).

### Preflight as Universal Guardrail

Every write operation goes through preflight — no exceptions:

| Conflict Type | Meaning | Action |
|---------------|---------|--------|
| IDEMPOTENT | Already done in Jira | Auto-succeed, sync local |
| SAFE_DRIFT | Changes don't overlap | Proceed with warning |
| REAL_CONFLICT | Same fields changed | Block, require choice |
| STRUCTURAL | Invalid operation | Block, explain why |

Decisions don't get "privileges". Same rules as regular sync.

## Core Value

**Chat is the source of truth.** The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.

## Current State (v1.2 in progress)

**Latest:** 2026-01-24

**Tech stack:** Python 3.11, LangGraph, Slack Bolt, PostgreSQL, Docker

**Codebase:** 150+ Python files, 38,000+ LOC

**Deployed to:** GCE VM with Docker Compose

**What shipped in v1.1:**
- Conversation history with two-layer context (raw + compressed)
- Intent routing: TICKET/REVIEW/DISCUSSION with LLM-only classification
- Architecture decision auto-detection and channel posting
- Brain refactor: new AgentState, WorkflowStep, PendingAction architecture
- Multi-ticket creation from reviews (Epic + Stories)
- Communication as Source of Truth: WorkItem registry, channel modes, commit semantics
- Bidirectional Jira sync with field ownership and conflict detection

**v1.2 completed phases:**
- Phase 24: Debug mode (`/maro debug on/off/status/state`)
- Phase 25: WorkItem-centric architecture (WORKITEM_CREATE, OPS intent, CHANGE_REQUEST)
- Phase 26: Context-aware intent classification (DRAFT_REFINE, issue_type extraction)
- Phase 27: Multi-user support (attribution, conflict detection, state-bound approvals)
- Phase 28: Structured Draft Evolution
  - **Core shift:** Draft is now a typed design object, not text container
  - `StructuredDraft` with DraftKind, DraftScope, DraftLifecycle, DraftItem
  - `DRAFT_TRANSFORM` intent for structural mutations (split, merge, elevate, decompose)
  - User input classification (CHOICE/OPINION/QUESTION/ANSWER routing)
  - Form-dependent validation (Epic doesn't require AC, Story does)
  - Lifecycle-aware questions (PLAN stage asks decomposition, not AC)
  - Version-bound approvals (stale button detection)
  - Structure visualization after every mutation
- Phase 29: Sync on Demand
  - **Preflight sync:** Automatic safety layer before Jira operations
  - **`/maro sync`:** Diagnostic command for reconciliation
  - 4-type conflict classification (IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL)
  - JiraRegistryStore with sync tracking (status, assignee, timestamps)
  - "Distributed version control for meaning" — never auto-fix, always human choice
- Phase 30: Decision as First-Class Entity
  - **Core shift:** Decisions are versioned, Jira is a projection
  - Decision entity with 6 types (ARCH, SCOPE, CONSTRAINT, PRIORITY, STRUCTURE, PROCESS)
  - DecisionLink for decision-to-Jira field mapping with sync tracking
  - Canonical message pattern (one message per decision, updated in place)
  - Four visual states matching psychological weight (idea → proposal → law → record)
  - Managed sections for safe Jira writes (MARO never overwrites user content)
  - Decision preflight with same 4-type conflict classification
  - `/maro decisions`, `/maro decision show/change/deprecate` commands
  - DECISION intent with pattern-based detection
- Phase 31: Architecture Hardening
  - SuperMode enum (BUILD, OPERATE, DECIDE, THINK, CHAT) for user-facing simplicity
  - MANAGED_SECTION_ONLY invariant for decision projection safety
  - Slack as UI pattern (message failures don't block state updates)
- Phase 32: Product Invariants
  - 5 enforced invariants (SuperMode UI, Slack separation, Commit log, Managed sections, Draft lifecycle)
  - CI gate for managed section enforcement
- Phase 33: Anchor Message Architecture
  - Object-centric design (threads exist to manage objects, not for conversation)
  - Thread bindings inherit object context automatically
  - Implicit commands default to anchor's object
- Phase 34: File Attachment Processing
  - Attachments as first-class entities with lifecycle states
  - Intent-scoped inclusion rules (CHAT offers, THINK retrieves, BUILD extracts structure)
  - Pin/unpin mechanics with transparency UI
- Phase 35: Multi-Intent Task Orchestration
  - **Core shift:** Parse full universe of user intent, not just top-1 classification
  - TaskPlan model with tasks, dependencies, safety levels
  - Two-stage classification (single-intent first, multi-intent if signals detected)
  - Task executor with dependency-aware execution and cascade cancel
  - Status card UI with throttled updates (1.5s minimum)
  - Version-bound button handlers for idempotency

## Requirements

### Validated

**v1.0:**
- ✓ **Thread-first architecture** — One discussion = one thread = one session = one Jira ticket
- ✓ **Cyclic agent loop** — LangGraph ReAct pattern with extraction → validation → decision
- ✓ **Proactive questioning** — Bot asks clarifying questions via ask_user skill
- ✓ **Type-specific ticket schemas** — TicketDraft with title, problem, solution, ACs, constraints
- ✓ **AgentState** — messages, draft, phase, pending_questions, validation_report
- ✓ **Global State** — Channel context from pins with knowledge extraction
- ✓ **Dynamic personas** — PM/Architect/Security with policy-based validators
- ✓ **Skills as tools** — ask_user, preview_ticket, jira_create, jira_search
- ✓ **Slack Bolt integration** — Socket Mode, thread detection, approval buttons
- ✓ **PostgreSQL checkpointer** — AsyncPostgresSaver for state persistence
- ✓ **Direct Atlassian API** — atlassian-python-api with retry/backoff
- ✓ **Configurable LLM** — Gemini, OpenAI, Anthropic adapters
- ✓ **Docker deployment** — Bot + PostgreSQL with one-command deploy

**v1.1:**
- ✓ **Conversation history fetching** — Two-layer context (raw messages + compressed summary)
- ✓ **Improved onboarding** — Channel join handler, hesitation detection, interactive /maro help
- ✓ **Intent routing** — TICKET/REVIEW/DISCUSSION classification with LLM-only
- ✓ **Architecture decision records** — Auto-detect decisions, post to channel
- ✓ **Review conversation flow** — Continue after review without misclassification
- ✓ **Full ticket operations** — update_issue(), add_comment(), create_subtask()
- ✓ **Multi-ticket from review** — Create Epic + Stories from architecture analysis
- ✓ **WorkItem registry** — First-class drafts with 5 types (Epic/Story/Bug/Task/Spike)
- ✓ **Channel mode** — project/feature/bugs/ops with thread overrides
- ✓ **Commit semantics** — Git-log style Channel Work Board with explicit approval
- ✓ **Bidirectional Jira sync** — Field ownership, section fingerprints, conflict detection

### Active

(None — planning next milestone)

### Out of Scope

- Multi-language support — English only
- Zep memory server — using PostgreSQL for all persistence
- MCP server for Jira — direct API calls via atlassian-python-api
- Mobile app — web/Slack first
- Real-time collaborative editing — async communication model

## Context

**v1.2 in progress.** Evolution from collective thinking system to decision management platform.

**Key architectural patterns:**
- WorkItem as first-class citizen (drafts exist before Jira sync)
- Decision as first-class entity (versioned, linked, projected to Jira)
- Channel = Source of Truth (workspace), Thread = Working Branch (session)
- Jira = Execution Replica (projection of communication truth)
- Canonical message pattern (one message per entity, updated in place)
- Field ownership: Jira-owned, Slack-owned, Shared (conflict-detect)
- Managed sections for safe Jira writes (never overwrite user content)
- Preflight as universal guardrail (every write goes through conflict check)

**Technical foundation:**
- WorkItemStore for work item lifecycle
- DecisionStore for versioned decisions with approval workflow
- DecisionLinkStore for decision-to-Jira mappings with sync tracking
- ChannelModeStore for mode configuration
- CommitStore for git-log style commit history
- JiraSyncService for bidirectional sync
- PreflightService for conflict detection before operations
- DecisionSyncService for decision → Jira projection

## Constraints

- **Language**: Python 3.11+
- **Core libraries**: langgraph, langchain-google-genai, slack_bolt, pydantic, atlassian-python-api, psycopg
- **Deployment**: Docker container + PostgreSQL database on GCE VM
- **LLM default**: Gemini (configurable to other providers)
- **Response language**: English only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Thread-scoped sessions | One thread = one ticket simplifies state management | ✓ Good |
| ReAct loop over phases | Flexible agent behavior vs rigid pipeline | ✓ Good |
| PostgreSQL only | Eliminate Zep dependency, reduce infrastructure | ✓ Good |
| Direct Atlassian API | Remove MCP server complexity | ✓ Good |
| Fresh personas | Tailored to ticket-focused workflow | ✓ Good |
| Gemini default | User preference, cost-effective | ✓ Good |
| Type-specific schemas | Different issue types have different required fields | ✓ Good |
| Async in sync handlers | Persistent background event loop for Bolt compatibility | ✓ Good |
| Socket Mode over HTTP | No public endpoint needed, simpler deployment | ✓ Good |
| Two-layer context | Raw messages + compressed summary balances detail vs tokens | ✓ Good |
| LLM-only intent routing | Full context analysis for accurate classification | ✓ Good |
| WorkItem as first-class | Drafts before Jira, explicit sync control | ✓ Good |
| Field ownership classification | Clear rules for bidirectional sync | ✓ Good |
| Section fingerprinting | Granular conflict detection without full diff | ✓ Good |
| SessionStore deprecated | Migrate to WorkItemStore, keep for backward compat | — Pending cleanup |
| Context-aware intent | Pass draft state to LLM classifier for DRAFT_REFINE detection | ✓ Good |
| Structured issue types | IssueType/RequestedScope enums instead of "Epic:" title prefixes | ✓ Good |
| StructuredDraft design object | Draft as typed data structure with lifecycle states (Phase 28) | ✓ Good |
| Draft lifecycle state machine | EMPTY → SINGLE_ITEM → PLAN → APPROVED → COMMITTED | ✓ Good |
| Form-dependent validation | Epic validates goal/scope, Story validates AC (Phase 28) | ✓ Good |
| DRAFT_TRANSFORM intent | Structural mutations via semantic triggers (Phase 28) | ✓ Good |
| User input classification | CHOICE/OPINION/QUESTION/ANSWER routing (Phase 28) | ✓ Good |
| Version-bound approvals | Button payloads include version, reject stale clicks (Phase 28) | ✓ Good |
| Preflight as universal guardrail | Every Jira write goes through conflict check, no exceptions (Phase 29) | ✓ Good |
| 4-type conflict classification | IDEMPOTENT/SAFE_DRIFT/REAL_CONFLICT/STRUCTURAL for clear handling (Phase 29) | ✓ Good |
| Never auto-fix conflicts | Human choice required for any conflict resolution (Phase 29) | ✓ Good |
| Decision as first-class entity | Versioned decisions with lifecycle, Jira as projection (Phase 30) | ✓ Good |
| Canonical message pattern | One message per decision, updated in place (Phase 30) | ✓ Good |
| Managed sections in Jira | MARO writes only to its block, preserves user content (Phase 30) | ✓ Good |
| Deterministic decision mapping | Decision type → known Jira field, no LLM guessing (Phase 30) | ✓ Good |
| Decision approval = commit + sync | Approval triggers immediate Jira projection (Phase 30) | ✓ Good |
| SuperMode as sole UI contract | Users see 5 modes, 13 intents hidden (Phase 31) | ✓ Good |
| Commit log = append-only | Event-sourced history, canonical messages rebuildable (Phase 32) | ✓ Good |
| Anchor message architecture | Threads exist to manage objects, not for conversation (Phase 33) | ✓ Good |
| Attachments as first-class entities | Lifecycle states, pinning, intent-scoped retrieval (Phase 34) | ✓ Good |
| Multi-intent task orchestration | Parse full universe of user intent, not just top-1 (Phase 35) | ✓ Good |
| Two-stage intent classification | Single-intent first, re-classify if multi-intent signals detected (Phase 35) | ✓ Good |
| Safety-based auto-execution | THINK/CHAT auto-execute, BUILD/OPERATE/DECIDE require approval (Phase 35) | ✓ Good |

---
*Last updated: 2026-01-24 after Phase 35 (v1.2)*

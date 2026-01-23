# Proactive Jira Analyst Bot

## What This Is

A Slack bot that acts as a collective thinking system where communication is the source of truth. Drives conversations in threads to gather complete requirements, creates Jira tickets when information is sufficient, and maintains bidirectional sync between Slack discussions and Jira issues.

## Core Value

**Chat is the source of truth.** The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.

## Current State (v1.2 in progress)

**Latest:** 2026-01-23

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

**v1.1 shipped.** Major transformation from ticket-creation bot to collective thinking system.

**Key architectural patterns:**
- WorkItem as first-class citizen (drafts exist before Jira sync)
- Channel = Source of Truth (workspace), Thread = Working Branch (session)
- Jira = Execution Replica (projection of communication truth)
- Field ownership: Jira-owned, Slack-owned, Shared (conflict-detect)
- Section-level fingerprinting for conflict detection

**Technical foundation:**
- WorkItemStore replaces SessionStore
- ChannelModeStore for mode configuration
- CommitStore for git-log style commit history
- JiraSyncService for bidirectional sync

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

---
*Last updated: 2026-01-23 after Phase 28 (v1.2)*

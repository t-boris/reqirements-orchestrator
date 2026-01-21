# Proactive Jira Analyst Bot

## What This Is

A Slack bot that acts as a collective thinking system where communication is the source of truth. Drives conversations in threads to gather complete requirements, creates Jira tickets when information is sufficient, and maintains bidirectional sync between Slack discussions and Jira issues.

## Core Value

**Chat is the source of truth.** The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets. Jira is a projection of what became truth in communication.

## Current State (v1.1)

**Shipped:** 2026-01-20

**Tech stack:** Python 3.11, LangGraph, Slack Bolt, PostgreSQL, Docker

**Codebase:** 146 Python files, 34,567 LOC

**Deployed to:** GCE VM with Docker Compose

**What shipped in v1.1:**
- Conversation history with two-layer context (raw + compressed)
- Intent routing: TICKET/REVIEW/DISCUSSION with pattern matching + LLM fallback
- Architecture decision auto-detection and channel posting
- Brain refactor: new AgentState, WorkflowStep, PendingAction architecture
- Multi-ticket creation from reviews (Epic + Stories)
- Communication as Source of Truth: WorkItem registry, channel modes, commit semantics
- Bidirectional Jira sync with field ownership and conflict detection

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
- ✓ **Intent routing** — TICKET/REVIEW/DISCUSSION classification with pattern + LLM
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
| Pattern-first intent routing | Fast for obvious cases, LLM for ambiguous | ✓ Good |
| WorkItem as first-class | Drafts before Jira, explicit sync control | ✓ Good |
| Field ownership classification | Clear rules for bidirectional sync | ✓ Good |
| Section fingerprinting | Granular conflict detection without full diff | ✓ Good |
| SessionStore deprecated | Migrate to WorkItemStore, keep for backward compat | — Pending cleanup |

---
*Last updated: 2026-01-20 after v1.1 milestone*

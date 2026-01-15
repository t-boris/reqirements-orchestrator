# Proactive Jira Analyst Bot

## What This Is

A Slack bot that acts as a proactive business analyst, driving conversations in threads to gather complete requirements and create Jira tickets when information is sufficient. Uses a cyclic agent model (ReAct loop) where state is defined by ticket readiness, not workflow phase.

## Core Value

**Chat is the source of truth.** The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.

## Current State (v1.0)

**Shipped:** 2026-01-14

**Tech stack:** Python 3.11, LangGraph, Slack Bolt, PostgreSQL, Docker

**Codebase:** 84 Python files, 13,248 LOC

**Deployed to:** GCE VM with Docker Compose

## Requirements

### Validated

- ✓ **Thread-first architecture** — v1.0: One discussion = one thread = one session = one Jira ticket
- ✓ **Cyclic agent loop** — v1.0: LangGraph ReAct pattern with extraction → validation → decision
- ✓ **Proactive questioning** — v1.0: Bot asks clarifying questions via ask_user skill
- ✓ **Type-specific ticket schemas** — v1.0: TicketDraft with title, problem, solution, ACs, constraints
- ✓ **AgentState** — v1.0: messages, draft, phase, pending_questions, validation_report
- ✓ **Global State** — v1.0: Channel context from pins with knowledge extraction
- ✓ **Dynamic personas** — v1.0: PM/Architect/Security with policy-based validators
- ✓ **Skills as tools** — v1.0: ask_user, preview_ticket, jira_create, jira_search
- ✓ **Slack Bolt integration** — v1.0: Socket Mode, thread detection, approval buttons
- ✓ **PostgreSQL checkpointer** — v1.0: AsyncPostgresSaver for state persistence
- ✓ **Direct Atlassian API** — v1.0: atlassian-python-api with retry/backoff
- ✓ **Configurable LLM** — v1.0: Gemini, OpenAI, Anthropic adapters
- ✓ **Docker deployment** — v1.0: Bot + PostgreSQL with one-command deploy

### Active

- [ ] **Conversation history fetching** — Read channel messages before @mention for context
- [ ] **Improved onboarding** — Better intro messages and command discoverability

### Out of Scope

- Multi-language support — English only for v1
- Zep memory server — using PostgreSQL for all persistence
- MCP server for Jira — direct API calls via atlassian-python-api
- Complex hierarchy creation (Epic→Story→Task trees) — focus on single ticket per thread
- Admin dashboard with D3.js visualization — manage via Slack commands

## Context

**v1.0 MVP shipped.** Bot is deployed and operational on GCE VM.

**Key architectural patterns:**
- Router/Dispatcher handles Slack events, routes to agent
- Analyst Agent runs extraction → validation → decision loop
- Skills are async functions with explicit dependency injection
- Persistent background event loop for async operations in sync Bolt handlers

**Known limitations:**
- Bot only sees the @mention message, not prior conversation
- `/help` command requires Slack app configuration

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

---
*Last updated: 2026-01-14 after v1.0 milestone*

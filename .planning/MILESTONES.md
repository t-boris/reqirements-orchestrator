# Project Milestones: Proactive Jira Analyst Bot

## v1.1 Communication as Source of Truth (Shipped: 2026-01-20)

**Delivered:** Transformed MARO from a "Jira ticket creation bot" into a "collective thinking system" where communication is the source of truth and Jira is a projection of that truth.

**Phases completed:** 11-23.5 (63 plans total)

**Key accomplishments:**

- Conversation history with two-layer context (raw messages + compressed summary)
- Intent routing: TICKET/REVIEW/DISCUSSION with pattern matching + LLM fallback
- Architecture decision auto-detection and channel posting
- Brain refactor: new AgentState, WorkflowStep, PendingAction architecture
- Multi-ticket creation from reviews (Epic + linked Stories)
- WorkItem registry: first-class drafts with 5 types (Epic/Story/Bug/Task/Spike)
- Channel mode system (project/feature/bugs/ops) with thread overrides
- Git-log style Channel Work Board with explicit approval
- Bidirectional Jira sync with field ownership and conflict detection

**Stats:**

- 146 Python files (62 new)
- 34,567 lines of Python (21,319 new)
- 18 phases, 63 plans
- 6 days from v1.0 to v1.1 (Jan 14 → Jan 20)
- 379 new commits (615 total)

**Git range:** `05821b2` → `6cf0636`

**What's next:** Planning next milestone

---

## v1.0 MVP (Shipped: 2026-01-14)

**Delivered:** A Slack bot that drives thread-based conversations to gather requirements and creates Jira tickets when information is complete.

**Phases completed:** 1-10 (43 plans total)

**Key accomplishments:**

- Thread-first Slack bot with Socket Mode and conversation-scoped sessions
- LangGraph ReAct agent with extraction → validation → decision cycle
- Multi-provider LLM abstraction (Gemini, OpenAI, Anthropic)
- Skills system: ask_user, preview_ticket, jira_create, jira_search
- Channel context system with knowledge extraction from pins
- Dynamic personas (PM/Architect/Security) with policy-based validators
- Docker deployment to GCE VM with one-command deploy

**Stats:**

- 84 Python files created
- 13,248 lines of Python
- 10 phases, 43 plans
- 24 days from start to ship (Dec 22 → Jan 14)
- 236 commits

**Git range:** Initial commit → `05821b2`

**What's next:** v1.1 will add conversation history fetching (read messages before @mention) and improved onboarding.

---

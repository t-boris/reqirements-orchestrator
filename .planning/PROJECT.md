# Proactive Jira Analyst Bot

## What This Is

A Slack bot that acts as a proactive business analyst, driving conversations in threads to gather complete requirements and create Jira tickets when information is sufficient. Replaces the rigid 11-phase MARO v2 pipeline with a cyclic agent model (ReAct loop) where state is defined by ticket readiness, not workflow phase.

## Core Value

**Chat is the source of truth.** The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] **Thread-first architecture**: One discussion = one thread = one session = one Jira ticket
- [ ] **Cyclic agent loop**: LangGraph ReAct pattern instead of fixed phases
- [ ] **Proactive questioning**: Bot asks clarifying questions until requirements complete
- [ ] **JiraTicketSchema**: summary, description, acceptance_criteria[], priority, type
- [ ] **AgentState**: messages, draft, missing_info[], status (collecting/ready_to_sync/synced)
- [ ] **Global State**: Channel context from root messages, pinned content, and Jira history
- [ ] **Dynamic personas**: PM/Architect/Security switch based on conversation topic (fresh prompts)
- [ ] **Conflict detection**: Check against Global State within channel scope
- [ ] **Skills as tools**: ask_user, preview_ticket, jira_create, jira_search
- [ ] **Slack Bolt integration**: Socket Mode, thread detection, approval buttons
- [ ] **PostgreSQL checkpointer**: State persistence per thread session
- [ ] **Direct Atlassian API**: Python SDK instead of MCP server
- [ ] **Configurable LLM**: Support multiple providers, default to Gemini
- [ ] **Docker deployment**: Bot container + PostgreSQL

### Out of Scope

- Multi-language support — English only for v1
- Zep memory server — using PostgreSQL for all persistence
- MCP server for Jira — direct API calls via atlassian-python-api
- Complex hierarchy creation (Epic→Story→Task trees) — focus on single ticket per thread
- Admin dashboard with D3.js visualization — manage via Slack commands

## Context

**Evolution from MARO v2:**
- MARO had 23 nodes, 11 phases, Zep memory, MCP for Jira
- This bot simplifies to 3 components: Router, Analyst Agent, Skills
- State is ticket-readiness, not workflow phase
- Session scoped to thread, not channel

**Key architectural patterns:**
- Router/Dispatcher handles Slack events, routes to agent
- Analyst Agent runs extraction → validation → decision loop
- Skills are LangGraph tools (@tool decorated functions)

**Data schema:**
```python
class JiraTicketSchema(BaseModel):
    summary: str
    description: str
    acceptance_criteria: List[str]
    priority: Literal['Highest', 'High', 'Medium', 'Low']
    type: Literal['Epic', 'Story', 'Task', 'Bug']

class AgentState(TypedDict):
    messages: List[BaseMessage]
    draft: Optional[JiraTicketSchema]
    missing_info: List[str]
    status: Literal['collecting', 'ready_to_sync', 'synced']
```

**Reference implementation:** See `docs/architecture.md` for MARO v2 patterns that can be adapted.

## Constraints

- **Language**: Python 3.10+
- **Core libraries**: langgraph, langchain-google-genai, slack_bolt, pydantic, atlassian-python-api, psycopg2
- **Deployment**: Docker container + PostgreSQL database
- **LLM default**: Gemini (configurable to other providers)
- **Response language**: English only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Thread-scoped sessions | One thread = one ticket simplifies state management | — Pending |
| ReAct loop over phases | Flexible agent behavior vs rigid pipeline | — Pending |
| PostgreSQL only | Eliminate Zep dependency, reduce infrastructure | — Pending |
| Direct Atlassian API | Remove MCP server complexity | — Pending |
| Fresh personas | Tailored to ticket-focused workflow vs reusing MARO personas | — Pending |
| Gemini default | User preference for initial LLM provider | — Pending |

---
*Last updated: 2026-01-14 after initialization*

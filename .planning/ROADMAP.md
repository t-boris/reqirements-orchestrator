# Roadmap: Proactive Jira Analyst Bot

## Overview

Build a Slack bot that acts as a proactive business analyst, driving thread-based conversations to gather requirements and create Jira tickets. The journey moves from infrastructure (database, LLM) through core agent logic (ReAct loop, skills) to integrations (Slack, Jira) and finally deployment.

## Domain Expertise

None

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Foundation** - Project setup, config, core schemas
- [x] **Phase 2: Database Layer** - PostgreSQL models, LangGraph checkpointer
- [ ] **Phase 3: LLM Integration** - Gemini client, configurable providers
- [ ] **Phase 4: Slack Router** - Event handlers, thread detection, message routing
- [ ] **Phase 5: Agent Core** - ReAct loop, AgentState, extraction/validation/decision
- [ ] **Phase 6: Skills** - ask_user, preview_ticket, tool implementations
- [ ] **Phase 7: Jira Integration** - Atlassian API, create/search operations
- [ ] **Phase 8: Global State** - Channel context from messages, pinned, Jira history
- [ ] **Phase 9: Personas** - Dynamic PM/Architect/Security prompt switching
- [ ] **Phase 10: Deployment** - Docker container, environment config

## Phase Details

### Phase 1: Foundation
**Goal**: Set up project structure, configuration system, and core Pydantic schemas (JiraTicketSchema, AgentState)
**Depends on**: Nothing (first phase)
**Research**: Unlikely (project setup, established patterns)
**Plans**: TBD

Plans:
- [x] 01-01: Project structure and pyproject.toml
- [x] 01-02: Configuration system with settings.py
- [x] 01-03: Core schemas (JiraTicketSchema, AgentState)

### Phase 2: Database Layer
**Goal**: PostgreSQL connection, models for project_context and thread state, LangGraph checkpointer
**Depends on**: Phase 1
**Research**: Unlikely (PostgreSQL + LangGraph checkpointer patterns established)
**Plans**: TBD

Plans:
- [x] 02-01: PostgreSQL connection and base models
- [x] 02-02: LangGraph checkpointer integration
- [x] 02-03: Project context and session tables

### Phase 3: LLM Integration
**Goal**: Multi-provider LLM abstraction (Gemini, OpenAI, Anthropic) with unified interface and prompt system
**Depends on**: Phase 1
**Research**: Complete (discussed architecture decisions)
**Architecture**: 3-layer (Factory -> UnifiedClient -> ProviderAdapters), capability matrix, provider overlays

Plans:
- [ ] 03-01: Core interfaces & types (LLMProvider, Message, LLMResult, CapabilityMatrix)
- [ ] 03-02: Gemini adapter with langchain-google-genai
- [ ] 03-03: OpenAI adapter with langchain-openai
- [ ] 03-04: Anthropic adapter with langchain-anthropic
- [ ] 03-05: UnifiedChatClient + LLMFactory
- [ ] 03-06: Prompt system (base templates + provider overlays)

### Phase 4: Slack Router
**Goal**: Slack Bolt integration, Socket Mode, thread detection, message event routing
**Depends on**: Phase 1
**Research**: Unlikely (Slack Bolt Socket Mode is documented)
**Plans**: TBD

Plans:
- [ ] 04-01: Slack Bolt app setup with Socket Mode
- [ ] 04-02: Message event handlers with thread detection
- [ ] 04-03: Session initialization and routing logic

### Phase 5: Agent Core
**Goal**: LangGraph ReAct agent loop, AgentState management, extraction/validation/decision cycle
**Depends on**: Phase 2, Phase 3, Phase 4
**Research**: Likely (LangGraph ReAct pattern, tool-calling architecture)
**Research topics**: LangGraph ReAct agent pattern, tool binding, state transitions
**Plans**: TBD

Plans:
- [ ] 05-01: LangGraph graph definition with ReAct pattern
- [ ] 05-02: Extraction node (update draft from messages)
- [ ] 05-03: Validation node (check completeness, detect conflicts)
- [ ] 05-04: Decision node (ask question vs preview ticket)

### Phase 6: Skills
**Goal**: Implement LangGraph tools: ask_user, preview_ticket for agent to call
**Depends on**: Phase 5
**Research**: Unlikely (LangGraph tool patterns established)
**Plans**: TBD

Plans:
- [ ] 06-01: ask_user skill (send message to thread)
- [ ] 06-02: preview_ticket skill (show draft with approval buttons)
- [ ] 06-03: Tool binding and agent integration

### Phase 7: Jira Integration
**Goal**: Atlassian Python API client, jira_create and jira_search skills
**Depends on**: Phase 6
**Research**: Unlikely (atlassian-python-api is standard, documented)
**Plans**: TBD

Plans:
- [ ] 07-01: Atlassian API client setup
- [ ] 07-02: jira_create skill with priority mapping
- [ ] 07-03: jira_search skill for duplicate detection

### Phase 8: Global State
**Goal**: Channel context system from root messages, pinned content, and Jira history
**Depends on**: Phase 7
**Research**: Unlikely (internal patterns, PostgreSQL queries)
**Plans**: TBD

Plans:
- [ ] 08-01: Channel context model and storage
- [ ] 08-02: Root message and pinned content analysis
- [ ] 08-03: Jira history integration for channel context

### Phase 9: Personas
**Goal**: Dynamic persona switching (PM/Architect/Security) based on conversation topic
**Depends on**: Phase 5
**Research**: Unlikely (prompt engineering, internal patterns)
**Plans**: TBD

Plans:
- [ ] 09-01: Persona definitions and system prompts
- [ ] 09-02: Topic detection for persona switching
- [ ] 09-03: Persona integration with agent extraction/validation

### Phase 10: Deployment
**Goal**: Docker container configuration, environment setup, production deployment
**Depends on**: All previous phases
**Research**: Unlikely (Docker + PostgreSQL is established)
**Plans**: TBD

Plans:
- [ ] 10-01: Dockerfile and docker-compose
- [ ] 10-02: Environment configuration and secrets
- [ ] 10-03: Production deployment scripts

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-01-14 |
| 2. Database Layer | 3/3 | Complete | 2026-01-14 |
| 3. LLM Integration | 0/6 | Not started | - |
| 4. Slack Router | 0/3 | Not started | - |
| 5. Agent Core | 0/4 | Not started | - |
| 6. Skills | 0/3 | Not started | - |
| 7. Jira Integration | 0/3 | Not started | - |
| 8. Global State | 0/3 | Not started | - |
| 9. Personas | 0/3 | Not started | - |
| 10. Deployment | 0/3 | Not started | - |

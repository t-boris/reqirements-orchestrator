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
- [x] **Phase 3: LLM Integration** - Multi-provider LLM abstraction, prompt system
- [x] **Phase 4: Slack Router** - Event handlers, thread detection, message routing
- [x] **Phase 5: Agent Core** - ReAct loop, AgentState, extraction/validation/decision
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
- [x] 03-01: Core interfaces & types (LLMProvider, Message, LLMResult, CapabilityMatrix)
- [x] 03-02: Gemini adapter with langchain-google-genai
- [x] 03-03: OpenAI adapter with langchain-openai
- [x] 03-04: Anthropic adapter with langchain-anthropic
- [x] 03-05: UnifiedChatClient + LLMFactory
- [x] 03-06: Prompt system (base templates + provider overlays)

### Phase 4: Slack Router
**Goal**: Full Hub & Spoke architecture - Slack integration with Epic binding, Zep memory, Knowledge Graph, and PM behaviors
**Depends on**: Phase 1, Phase 2, Phase 3
**Research**: Complete (discussed architecture in detail)
**Architecture**: 3 sub-phases (4A: Slack Spine, 4B: Memory Plumbing, 4C: PM Behaviors)

**Key Decisions:**
- Explicit triggers only (no ambient LLM classification)
- Separate ingestion from decisioning
- Structured constraints (subject/value/status) not free-form text
- Non-blocking dedup suggestions (high threshold only)

Plans:
- [x] 04-01: Slack Bolt setup + Socket Mode (Wave 1)
- [x] 04-02: Message router - mentions + slash commands (Wave 2)
- [x] 04-03: Session model + dedup store + serialization (Wave 2)
- [x] 04-04: Epic binding flow with session card UI (Wave 3)
- [x] 04-05: Zep integration - storage + search API (Wave 1)
- [x] 04-06: Knowledge Graph schema + constraint storage (Wave 1)
- [x] 04-07: Document processing - PDF, DOCX, MD, TXT (Wave 1)
- [x] 04-08: Dedup suggestions - high-confidence, non-blocking (Wave 4)
- [x] 04-09: Contradiction detector - structured matching (Wave 4)

### Phase 5: Agent Core
**Goal**: LangGraph ReAct agent loop, AgentState management, extraction/validation/decision cycle
**Depends on**: Phase 2, Phase 3, Phase 4
**Research**: Likely (LangGraph ReAct pattern, tool-calling architecture)
**Research topics**: LangGraph ReAct agent pattern, tool binding, state transitions
**Plans**: TBD

Plans:
- [x] 05-01: State & Draft schemas (Wave 1)
- [x] 05-02: Graph & Extraction node (Wave 2)
- [x] 05-03: Validation & Decision nodes (Wave 3)
- [x] 05-04: Runner Integration (Wave 4)

### Phase 6: Skills
**Goal**: Implement skills: ask_user, preview_ticket for agent to call with interrupt/resume pattern
**Depends on**: Phase 5
**Research**: Complete (discussed architecture in detail)
**Architecture**: Skills as async functions with explicit parameters, Decision node controls "when", skills handle "how"

**Key Decisions:**
- Skills are async functions (not graph nodes) with explicit dependency injection
- Dedup key: (session_id, state_version) for idempotency
- Approval records: PostgreSQL table with unique constraint on (session_id, draft_hash)
- Question matching: semantic (LLM-based), re-ask limit 2x max
- Edit modal: full draft fields, client-side validation, replace preview after submit

Plans:
- [x] 06-01: ask_user skill + interrupt/resume + semantic answer matching (Wave 1)
- [ ] 06-02: preview_ticket skill + version checking + approval records (Wave 2)
- [ ] 06-03: Edit modal + skill dispatcher + tool binding (Wave 3)

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
| 3. LLM Integration | 6/6 | Complete | 2026-01-14 |
| 4. Slack Router | 9/9 | Complete | 2026-01-14 |
| 5. Agent Core | 4/4 | Complete | 2026-01-14 |
| 6. Skills | 1/3 | In progress | - |
| 7. Jira Integration | 0/3 | Not started | - |
| 8. Global State | 0/3 | Not started | - |
| 9. Personas | 0/3 | Not started | - |
| 10. Deployment | 0/3 | Not started | - |

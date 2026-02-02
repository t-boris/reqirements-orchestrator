# Roadmap: MARO 2.0

## Overview

Complete rewrite of MARO from v1.x to an event-sourced architecture. The journey takes us from foundation (domain model, event store) through Slack integration, intent classification, entity lifecycle management, process orchestration, and finally Jira projection. Each phase builds on the previous, culminating in a deployable system that transforms conversations into work items.

## Domain Expertise

None

## Phases

- [x] **Phase 1: Foundation** - Project setup, domain model, event store
- [ ] **Phase 2: Slack Integration** - Bolt app, message routing, handlers
- [ ] **Phase 3: Intent & Modes** - PreGates, Router, 4 SuperModes
- [ ] **Phase 4: Entity Lifecycle** - Unified entity, state transitions, approvals
- [ ] **Phase 5: Process Orchestration** - Process/Plan/Workflow patterns
- [ ] **Phase 6: Jira Projection** - Sync engine, conflict detection
- [ ] **Phase 7: Polish & Deploy** - Testing, deployment, documentation

## Phase Details

### Phase 1: Foundation
**Goal**: Establish project structure, implement domain model and event store
**Depends on**: Nothing (first phase)
**Research**: Complete (01-RESEARCH.md)
**Plans**: 5 (01-01 through 01-05, all complete)

Key deliverables:
- Python project scaffolding (FastAPI, Pydantic)
- Core domain types (EntityId, ChannelId, ThreadTs, etc.)
- Entity types (WorkItemContent, DecisionContent)
- Event base classes and entity events
- EventStore with PostgreSQL backend
- Projection infrastructure

### Phase 2: Slack Integration
**Goal**: Working Slack bot with message handling and routing
**Depends on**: Phase 1
**Research**: Unlikely (Bolt SDK, v1.x patterns exist)
**Plans**: TBD

Key deliverables:
- Slack Bolt app setup
- Message event handlers
- Button action handlers
- SlackClient wrapper with rate limiting
- Message routing (channel/thread/ephemeral)
- Basic response posting

### Phase 3: Intent & Modes
**Goal**: 2-stage intent classification with 4 SuperModes
**Depends on**: Phase 2
**Research**: Unlikely (spec defines approach)
**Plans**: TBD

Key deliverables:
- PreGates (deterministic routing)
- LLM Router
- SuperMode enum (CREATE, MODIFY, RECORD, CONVERSE)
- Mode handlers skeleton
- LLM abstraction layer (Gemini default)

### Phase 4: Entity Lifecycle
**Goal**: Unified entity model with full lifecycle support
**Depends on**: Phase 3
**Research**: Unlikely (sum types defined in spec)
**Plans**: TBD

Key deliverables:
- Entity sum types (Draft, Proposed, Approved, Committed, Deprecated)
- Channel aggregate root
- Entity projections
- Approval/Objection handling
- Canonical message management
- Multi-user attribution

### Phase 5: Process Orchestration
**Goal**: Multi-stage process, plan execution, workflow coordination
**Depends on**: Phase 4
**Research**: Likely (statechart library selection)
**Research topics**: Python statechart libraries, xstate patterns in Python, process executor design
**Plans**: TBD

Key deliverables:
- Process definitions (architecture_review, work_item_creation)
- ProcessExecutor with stage handling
- Plan generation and execution
- Workflow orchestration (Process → Plan flow)
- Stage iteration and completion logic

### Phase 6: Jira Projection
**Goal**: Sync approved entities to Jira, handle conflicts
**Depends on**: Phase 5
**Research**: Likely (current Jira API, webhook patterns)
**Research topics**: Jira REST API v3, webhook handling, conflict resolution patterns
**Plans**: TBD

Key deliverables:
- JiraLink model
- Sync service
- Issue creation/update
- Decision projection to Jira fields
- Conflict detection
- Sync status tracking

### Phase 7: Polish & Deploy
**Goal**: Production-ready system deployed to existing infrastructure
**Depends on**: Phase 6
**Research**: Unlikely (existing GCE infrastructure)
**Plans**: TBD

Key deliverables:
- Integration tests
- Property-based tests (hypothesis)
- Deployment configuration
- Health checks
- Logging and monitoring
- Documentation

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 5/5 | Complete | 2026-02-02 |
| 2. Slack Integration | 0/TBD | Not started | - |
| 3. Intent & Modes | 0/TBD | Not started | - |
| 4. Entity Lifecycle | 0/TBD | Not started | - |
| 5. Process Orchestration | 0/TBD | Not started | - |
| 6. Jira Projection | 0/TBD | Not started | - |
| 7. Polish & Deploy | 0/TBD | Not started | - |

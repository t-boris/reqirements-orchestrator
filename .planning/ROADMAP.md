# Roadmap: MARO 2.0

## Overview

Complete rewrite of MARO from v1.x to an event-sourced architecture. The journey takes us from foundation (domain model, event store) through Slack integration, intent classification, entity lifecycle management, process orchestration, and finally Jira projection. Each phase builds on the previous, culminating in a deployable system that transforms conversations into work items.

## Domain Expertise

None

## Phases

- [x] **Phase 1: Foundation** - Project setup, domain model, event store
- [x] **Phase 2: Slack Integration** - Bolt app, message routing, handlers
- [x] **Phase 3: Intent & Modes** - PreGates, Router, 4 SuperModes
- [x] **Phase 4: Entity Lifecycle** - Unified entity, state transitions, approvals
- [x] **Phase 5: Process Orchestration** - Process/Plan/Workflow patterns
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
**Research**: Complete (02-RESEARCH.md)
**Plans**: 5 (02-01 through 02-05, all complete)

Key deliverables:
- Slack Bolt AsyncApp with FastAPI adapter
- SlackClient wrapper with rate limiting (1 msg/sec)
- Message type routing (CHANNEL/THREAD/EPHEMERAL)
- Event handlers (message, app_mention) with bot_id filtering
- Button action handlers (approve/object/discuss)
- /maro slash command with help
- Block Kit builders for common messages
- DashboardManager for pinned channel status
- Complete documentation in BOT_DESIGN.md

### Phase 3: Intent & Modes
**Goal**: 2-stage intent classification with 4 SuperModes
**Depends on**: Phase 2
**Research**: Complete (03-RESEARCH.md)
**Plans**: 6 (03-01 through 03-06)

Key deliverables:
- LLM abstraction layer (LiteLLM + Instructor for provider-agnostic access)
- PreGates (deterministic routing for commands, actions, approvals)
- LLM Router with structured output and confidence thresholds
- Safety Evaluator (lifecycle checks, permissions, confirmation requirements)
- SuperMode enum (CREATE, MODIFY, RECORD, CONVERSE)
- Mode handler skeletons with dispatcher
- Architecture documentation update

### Phase 4: Entity Lifecycle
**Goal**: Unified entity model with full lifecycle support
**Depends on**: Phase 3
**Research**: None (sum types already defined in spec)
**Plans**: 7 (04-01 through 04-07)

Key deliverables:
- Approval/Objection lifecycle events (04-01)
- Entity lifecycle transition functions (04-02)
- Channel aggregate root (04-03)
- Updated projections for approval/objection (04-04)
- Mode handler integration with entities (04-05)
- SafetyEvaluator with entity state checks (04-06)
- Architecture documentation update (04-07)

### Phase 5: Process Orchestration
**Goal**: Task-based workflow orchestration (evolved from spec's linear ProcessExecutor)
**Depends on**: Phase 4
**Research**: Complete (05-RESEARCH.md, 05-MODEL-PROPOSAL.md)
**Plans**: 7 (05-01 through 05-07)

Key deliverables:
- Task/Workspace/Orchestrator models (Task-based, not linear stages)
- FlowTemplate definitions (create_work_item, batch_create, architecture_review)
- Task events for event sourcing
- Orchestrator routing and task lifecycle
- PreGates integration (WORKSPACE result)
- WorkspaceProjection for read model
- Architecture documentation update

### Phase 6: Jira Projection
**Goal**: Sync approved entities to Jira, handle conflicts
**Depends on**: Phase 5
**Research**: Complete (06-RESEARCH.md)
**Plans**: 5 (06-01 through 06-05)

Wave structure:
- Wave 1: 06-01 (JiraClient, models)
- Wave 2: 06-02 (PreflightService, JiraSyncService)
- Wave 3: 06-03, 06-04 (CommitHandler, /maro sync command) - parallel
- Wave 4: 06-05 (Documentation update)

Key deliverables:
- JiraClient async wrapper (atlassian-python-api + tenacity)
- Field ownership model (JIRA_OWNED, SLACK_OWNED, SHARED)
- PreflightService for mandatory duplicate detection
- JiraSyncService for commit and reconcile
- CommitHandler for commit flow orchestration
- ReconciliationService for sync status
- /maro sync command with conflict resolution UI
- BOT_DESIGN.md Jira section

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
| 2. Slack Integration | 5/5 | Complete | 2026-02-02 |
| 3. Intent & Modes | 6/6 | Complete | 2026-02-02 |
| 4. Entity Lifecycle | 7/7 | Complete | 2026-02-02 |
| 5. Process Orchestration | 7/7 | Complete | 2026-02-02 |
| 6. Jira Projection | 1/5 | In progress | - |
| 7. Polish & Deploy | 0/TBD | Not started | - |

# MARO - Implementation Plan

**Overall Progress: 100%** ✅

---

## Phase 1: Project Infrastructure ✅

- [x] 1.1 Project Initialization
  - [x] Create directory structure (hexagonal)
  - [x] Configure pyproject.toml (Python 3.11+, FastAPI, AutoGen, NetworkX)
  - [x] Configure Docker Compose (PostgreSQL, Redis)
  - [x] Create .env.example

---

## Phase 2: Core Domain ✅

- [x] 2.1 Graph Models
  - [x] Node types (GOAL, EPIC, STORY, SUBTASK, COMPONENT, CONSTRAINT, RISK, QUESTION, CONTEXT)
  - [x] Edge types (DECOMPOSES_TO, DEPENDS_ON, REQUIRES_COMPONENT, CONSTRAINED_BY, CONFLICTS_WITH, MITIGATES, BLOCKS)
  - [x] Graph wrapper over NetworkX

- [x] 2.2 Event Store
  - [x] Event models (NodeCreated, NodeUpdated, EdgeCreated, EdgeDeleted, etc.)
  - [x] Event repository (PostgreSQL)
  - [x] Graph replay from events

- [x] 2.3 Graph Service
  - [x] CRUD operations via events
  - [x] Validation (orphans, cycles, conflicts)
  - [x] Metrics (completeness, orphan count, conflict ratio)

---

## Phase 3: LLM Adapters ✅

- [x] 3.1 LLM Protocol (interface)
  - [x] Base protocol for chat completion
  - [x] Model configuration

- [x] 3.2 OpenAI Adapter
  - [x] GPT-5 Mini (main)
  - [x] GPT-5 Nano (summarization)

- [x] 3.3 Summarization Service
  - [x] Trigger at >80% context window
  - [x] Summarize old nodes
  - [x] Save originals in DB

---

## Phase 4: AutoGen Agents ✅

- [x] 4.1 Graph Admin (UserProxy)
  - [x] Tools: add_node, add_edge, update_node, delete_node
  - [x] Tool: get_graph_state

- [x] 4.2 Software Architect (Assistant)
  - [x] System prompt (NFR, components, conflicts)
  - [x] REQUIRES_COMPONENT check logic
  - [x] CONFLICTS_WITH detection

- [x] 4.3 Product Manager (Assistant)
  - [x] System prompt (business value, AC, hierarchy)
  - [x] ACTOR validation, acceptance criteria
  - [x] Status management (DRAFT → APPROVED)

- [x] 4.4 GroupChat Orchestrator
  - [x] GroupChat configuration (AutoGen)
  - [x] Context Injector (graph-to-text)
  - [x] Session management

---

## Phase 5: Slack Adapter ✅

- [x] 5.1 Slack Bot Setup
  - [x] Slack Bolt SDK integration
  - [x] Bot Token auth
  - [x] Event subscriptions (messages)

- [x] 5.2 Message Handler
  - [x] Channel → Graph mapping (config)
  - [x] Channel → Jira project mapping (config)
  - [x] Route messages to AutoGen

- [x] 5.3 Commands
  - [x] /req-status (graph summary)
  - [x] /req-nfr (add constraint)
  - [x] /req-clean (delete graph)
  - [x] /req-reset (clear and recreate knowledge base)

- [x] 5.4 Response Formatter
  - [x] Brief responses in Slack
  - [x] Links to Dashboard

---

## Phase 6: Jira Adapter ✅

- [x] 6.1 IssueTracker Protocol
  - [x] create_issue, update_issue, get_issue, link_issues

- [x] 6.2 Jira Implementation
  - [x] REST API client
  - [x] Mapping (EPIC→Epic, STORY→Story, SUBTASK→Sub-task)
  - [x] Issue links (Blocks, Relates)

- [x] 6.3 Sync Service
  - [x] Graph → Jira sync
  - [x] Jira → Graph read (statuses)
  - [x] Partial sync handling (mark as partially_synced)
  - [x] Rollback logic

- [x] 6.4 Rate Limiting
  - [x] Leaky bucket implementation
  - [x] 3 retries with backoff

---

## Phase 7: Persistence ✅

- [x] 7.1 PostgreSQL
  - [x] Schema (events, graphs, configs, audit_log)
  - [x] Repository layer
  - [x] Periodic save (configurable interval)

- [x] 7.2 Redis
  - [x] Cache layer (graph snapshots)
  - [x] Task queue (background jobs)

- [x] 7.3 Audit Log
  - [x] Log all mutations
  - [x] User actions tracking

---

## Phase 8: Web Dashboard ✅

- [x] 8.1 Backend API
  - [x] GET /api/channels (channel list)
  - [x] GET /api/graphs/{channel_id} (graph)
  - [x] GET /api/graphs/{channel_id}/history (history)
  - [x] GET /api/graphs/{channel_id}/metrics (metrics)

- [x] 8.2 Frontend Setup
  - [x] React + Vite
  - [x] TailwindCSS
  - [x] React Flow

- [x] 8.3 Graph Visualization
  - [x] Interactive graph (zoom, pan, drag)
  - [x] Color coding (Synced/Draft/Error)
  - [x] Node details sidebar

- [x] 8.4 Metrics Panel
  - [x] Completeness %
  - [x] Orphan count
  - [x] Session cost ($)

- [x] 8.5 Navigation
  - [x] Channel list
  - [x] Change history

- [x] 8.6 Polling
  - [x] Configurable interval
  - [x] Auto-refresh

---

## Phase 9: Testing ✅

- [x] 9.1 Unit Tests
  - [x] Graph operations
  - [x] Event store
  - [x] LLM adapters (mocked)

- [x] 9.2 Integration Tests
  - [x] AutoGen agents
  - [x] Slack → Graph flow
  - [x] Graph → Jira sync

- [x] 9.3 Coverage
  - [x] Achieve 65%

---

## Phase 10: Deployment ✅

- [x] 10.1 Docker
  - [x] Dockerfile (backend)
  - [x] Dockerfile (frontend)
  - [x] docker-compose.yml (full stack)

- [x] 10.2 Cloud Run
  - [x] cloudbuild.yaml
  - [x] Service configuration
  - [x] Environment variables

- [x] 10.3 Database Migrations
  - [x] Alembic configuration
  - [x] Initial schema migration

---

## Directory Structure

```
maro/
├── src/
│   ├── core/                    # Domain layer
│   │   ├── graph/               # NetworkX wrapper, models
│   │   ├── events/              # Event store, event models
│   │   ├── agents/              # AutoGen agents
│   │   │   └── prompts/         # Agent system prompts
│   │   └── services/            # Graph service, sync service
│   │
│   ├── adapters/
│   │   ├── llm/                 # LLM protocol + implementations
│   │   ├── slack/               # Slack Bolt adapter
│   │   ├── jira/                # Jira REST adapter
│   │   └── persistence/         # PostgreSQL, Redis
│   │
│   ├── api/                     # FastAPI routes
│   │
│   └── config/                  # Settings, env loading
│
├── web/                         # React dashboard
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   └── ...
│
├── alembic/                     # Database migrations
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── docker-compose.yml
├── Dockerfile
├── cloudbuild.yaml
├── alembic.ini
└── pyproject.toml
```

---

## Configuration (env vars)

```
# LLM
OPENAI_API_KEY=
LLM_MODEL_MAIN=gpt-5-mini
LLM_MODEL_SUMMARIZE=gpt-5-nano

# Slack
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

# Jira
JIRA_URL=
JIRA_USER=
JIRA_API_TOKEN=

# Database
DATABASE_URL=postgresql://...
REDIS_URL=redis://...

# App
GRAPH_SAVE_INTERVAL_SECONDS=30
CONTEXT_THRESHOLD_PERCENT=80
POLLING_INTERVAL_MS=5000
```

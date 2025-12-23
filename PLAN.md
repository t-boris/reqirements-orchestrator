# MARO v2 Implementation Plan

**Overall Progress: 100%**

---

## Phase 1: Project Foundation ✅
> Infrastructure, dependencies, basic structure

- [x] **1.1 Project Setup**
  - [x] Create `pyproject.toml` with dependencies (langgraph, langchain, zep-python, slack-bolt, langchain-mcp-adapters)
  - [x] Create `.env.example` with required variables
  - [x] Create `docker-compose.yml` (app, zep, postgres)
  - [x] Create basic folder structure

- [x] **1.2 Configuration System**
  - [x] Create `config/settings.py` (pydantic-settings)
  - [x] Create `config/jira_fields.json` (field mappings per issue type)
  - [x] Create `personas/` folder structure with example markdown

- [x] **1.3 LangSmith Integration**
  - [x] Configure LangSmith tracing in settings
  - [ ] Verify traces appear in LangSmith UI

---

## Phase 2: Core LangGraph Workflow ✅
> State machine with nodes and edges

- [x] **2.1 State Schema**
  - [x] Define `RequirementState` TypedDict
  - [x] Define state fields (message, context, draft, conflicts, approval status)

- [x] **2.2 Graph Nodes**
  - [x] `memory_node` - Zep retrieval
  - [x] `intent_classifier_node` - LLM classification with confidence
  - [x] `conflict_detection_node` - Check against existing requirements
  - [x] `draft_node` - Create requirement draft
  - [x] `critique_node` - Reflexion critique (max 2-3 iterations)
  - [x] `human_approval_node` - HITL with interrupt_before
  - [x] `jira_write_node` - MCP call to create/update issue
  - [x] `memory_update_node` - Save to Zep

- [x] **2.3 Graph Edges & Routing**
  - [x] Conditional edge: intent confidence routing (≥60% main, ≥95% persona)
  - [x] Conditional edge: conflict detected → notify user
  - [x] Cycle edge: draft ↔ critique (max 3 iterations)
  - [x] Conditional edge: human decision routing (approve/edit/reject)

- [x] **2.4 Checkpointer**
  - [x] Configure PostgreSQL checkpointer for state persistence
  - [x] Map Slack thread_ts → LangGraph thread_id

---

## Phase 3: Memory (Zep) ✅
> Long-term memory with temporal knowledge graph

- [x] **3.1 Zep Client Setup**
  - [x] Initialize Zep client
  - [x] Configure per-channel session isolation

- [x] **3.2 Memory Operations**
  - [x] Store messages with user metadata
  - [x] Store extracted requirements as facts
  - [x] Retrieve relevant context for current message
  - [x] Invalidate outdated facts on requirement update

---

## Phase 4: Jira Integration (MCP) ✅
> Using cosmix/jira-mcp

- [x] **4.1 MCP Server Setup**
  - [x] Add jira-mcp to docker-compose (Node.js container)
  - [x] Configure Jira credentials in MCP server

- [x] **4.2 MCP Client Integration**
  - [x] Connect LangGraph to MCP server via langchain-mcp-adapters
  - [x] Implement tools: `create_issue`, `update_issue`, `search_issues`, `get_issue`

- [x] **4.3 Bidirectional Sync**
  - [x] On-demand issue fetch (natural language: "re-read JIRA-123")
  - [x] Update Zep memory when Jira issue refetched

- [x] **4.4 Field Mapping**
  - [x] Load `jira_fields.json` configuration
  - [x] Map requirement fields to Jira fields per issue type

---

## Phase 5: Slack Integration ✅
> Bot handlers and UI

- [x] **5.1 Slack Bolt Setup**
  - [x] Initialize AsyncApp with Socket Mode
  - [x] FastAPI lifespan integration

- [x] **5.2 Message Handling**
  - [x] Handle all messages (not just @mentions)
  - [x] Route to LangGraph with channel_id + thread_ts
  - [x] Parse attachments and include in message context

- [x] **5.3 Attachment Processing**
  - [x] Detect attachments in messages
  - [x] Read/parse attachment content
  - [x] Check if goal/context is established before processing

- [x] **5.4 HITL UI (Block Kit)**
  - [x] Approval message with buttons: Approve / Approve Always / Edit / Reject
  - [x] Handle button clicks, resume graph execution

- [x] **5.5 Slash Commands**
  - [x] `/req-status` - Show graph state and metrics
  - [x] `/req-config` - Channel configuration modal
  - [x] `/req-clean` - Clear memory and graph for channel
  - [x] `/req-approve list` - List permanent approvals
  - [x] `/req-approve delete <id>` - Remove approval

- [x] **5.6 Response Formatting**
  - [x] Format LLM responses with Block Kit
  - [x] Include metrics context

---

## Phase 6: Personas ✅
> Specialized agents with knowledge bases

- [x] **6.1 Persona System**
  - [x] Load persona configs from `personas/<name>/`
  - [x] Read markdown files as system prompt additions
  - [x] Support personality parameters (humor, emoji, formality %)

- [x] **6.2 Persona Routing**
  - [x] Route to persona when confidence ≥ 95%
  - [x] Personas: Architect, Product Manager, Security Analyst
  - [x] Each persona uses configured LLM model

- [x] **6.3 Default Personas**
  - [x] Create `personas/architect/` with placeholder docs
  - [x] Create `personas/product_manager/` with placeholder docs
  - [x] Create `personas/security_analyst/` with placeholder docs

---

## Phase 7: Approval System ✅
> Permanent approval management

- [x] **7.1 Approval Storage**
  - [x] Store approvals in PostgreSQL (channel_id, command_pattern, created_at)

- [x] **7.2 Approval Logic**
  - [x] Check permanent approvals before HITL interrupt
  - [x] Skip interrupt if matching approval exists

- [x] **7.3 Approval Management**
  - [x] Implement `/req-approve list`
  - [x] Implement `/req-approve delete <id>`

---

## Phase 8: Deployment ✅
> GCP VM setup

- [x] **8.1 Docker Configuration**
  - [x] Finalize `Dockerfile`
  - [x] Finalize `docker-compose.prod.yml`

- [x] **8.2 GCP VM Scripts**
  - [x] Update `deploy/setup-vm.sh`
  - [x] Test deployment on VM

- [x] **8.3 Environment Configuration**
  - [x] Create `deploy/.env.production` template

---

## File Structure

```
maro-v2/
├── src/
│   ├── graph/
│   │   ├── state.py          # State schema
│   │   ├── nodes.py          # All graph nodes
│   │   ├── graph.py          # Graph definition
│   │   └── checkpointer.py   # PostgreSQL checkpointer
│   ├── memory/
│   │   └── zep_client.py     # Zep operations
│   ├── jira/
│   │   └── mcp_client.py     # MCP client wrapper
│   ├── slack/
│   │   ├── bot.py            # Slack Bolt app
│   │   ├── handlers.py       # Message/command handlers
│   │   ├── approval.py       # HITL and approval logic
│   │   └── formatter.py      # Block Kit formatting
│   ├── personas/
│   │   └── loader.py         # Load persona configs
│   ├── config/
│   │   └── settings.py       # Pydantic settings
│   └── main.py               # FastAPI + Slack entrypoint
├── personas/
│   ├── architect/
│   │   └── knowledge.md
│   ├── product_manager/
│   │   └── knowledge.md
│   └── security_analyst/
│       └── knowledge.md
├── config/
│   └── jira_fields.json
├── deploy/
│   ├── setup-vm.sh
│   └── .env.production
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## Dependencies

```toml
[dependencies]
langgraph = ">=0.2"
langchain = ">=0.3"
langchain-openai = ">=0.2"
langchain-anthropic = ">=0.2"
langchain-google-genai = ">=2.0"
langchain-mcp-adapters = ">=0.1"
zep-python = ">=2.0"
slack-bolt = ">=1.18"
fastapi = ">=0.109"
uvicorn = ">=0.27"
asyncpg = ">=0.29"
pydantic-settings = ">=2.0"
structlog = ">=24.0"
```

---

## Environment Variables

```bash
# LLM
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

# Slack
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_SIGNING_SECRET=

# Jira (for MCP server)
JIRA_URL=
JIRA_USER=
JIRA_API_TOKEN=

# Zep
ZEP_API_URL=http://zep:8000

# Database
DATABASE_URL=postgresql+asyncpg://...

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=maro-v2

# App
DEFAULT_LLM_MODEL=gpt-4o
CONFIDENCE_THRESHOLD_MAIN=0.6
CONFIDENCE_THRESHOLD_PERSONA=0.95
MAX_REFLEXION_ITERATIONS=3
```

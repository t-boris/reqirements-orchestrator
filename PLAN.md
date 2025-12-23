# MARO v2 Implementation Plan

**Overall Progress: 0%**

---

## Phase 1: Project Foundation
> Infrastructure, dependencies, basic structure

- [ ] **1.1 Project Setup**
  - [ ] Create `pyproject.toml` with dependencies (langgraph, langchain, zep-python, slack-bolt, langchain-mcp-adapters)
  - [ ] Create `.env.example` with required variables
  - [ ] Create `docker-compose.yml` (app, zep, postgres)
  - [ ] Create basic folder structure

- [ ] **1.2 Configuration System**
  - [ ] Create `config/settings.py` (pydantic-settings)
  - [ ] Create `config/jira_fields.json` (field mappings per issue type)
  - [ ] Create `personas/` folder structure with example markdown

- [ ] **1.3 LangSmith Integration**
  - [ ] Configure LangSmith tracing in settings
  - [ ] Verify traces appear in LangSmith UI

---

## Phase 2: Core LangGraph Workflow
> State machine with nodes and edges

- [ ] **2.1 State Schema**
  - [ ] Define `RequirementState` TypedDict
  - [ ] Define state fields (message, context, draft, conflicts, approval status)

- [ ] **2.2 Graph Nodes**
  - [ ] `memory_node` - Zep retrieval
  - [ ] `intent_classifier_node` - LLM classification with confidence
  - [ ] `conflict_detection_node` - Check against existing requirements
  - [ ] `draft_node` - Create requirement draft
  - [ ] `critique_node` - Reflexion critique (max 2-3 iterations)
  - [ ] `human_approval_node` - HITL with interrupt_before
  - [ ] `jira_write_node` - MCP call to create/update issue
  - [ ] `memory_update_node` - Save to Zep

- [ ] **2.3 Graph Edges & Routing**
  - [ ] Conditional edge: intent confidence routing (≥60% main, ≥95% persona)
  - [ ] Conditional edge: conflict detected → notify user
  - [ ] Cycle edge: draft ↔ critique (max 3 iterations)
  - [ ] Conditional edge: human decision routing (approve/edit/reject)

- [ ] **2.4 Checkpointer**
  - [ ] Configure PostgreSQL checkpointer for state persistence
  - [ ] Map Slack thread_ts → LangGraph thread_id

---

## Phase 3: Memory (Zep)
> Long-term memory with temporal knowledge graph

- [ ] **3.1 Zep Client Setup**
  - [ ] Initialize Zep client
  - [ ] Configure per-channel session isolation

- [ ] **3.2 Memory Operations**
  - [ ] Store messages with user metadata
  - [ ] Store extracted requirements as facts
  - [ ] Retrieve relevant context for current message
  - [ ] Invalidate outdated facts on requirement update

---

## Phase 4: Jira Integration (MCP)
> Using cosmix/jira-mcp

- [ ] **4.1 MCP Server Setup**
  - [ ] Add jira-mcp to docker-compose (Node.js container)
  - [ ] Configure Jira credentials in MCP server

- [ ] **4.2 MCP Client Integration**
  - [ ] Connect LangGraph to MCP server via langchain-mcp-adapters
  - [ ] Implement tools: `create_issue`, `update_issue`, `search_issues`, `get_issue`

- [ ] **4.3 Bidirectional Sync**
  - [ ] On-demand issue fetch (natural language: "re-read JIRA-123")
  - [ ] Update Zep memory when Jira issue refetched

- [ ] **4.4 Field Mapping**
  - [ ] Load `jira_fields.json` configuration
  - [ ] Map requirement fields to Jira fields per issue type

---

## Phase 5: Slack Integration
> Bot handlers and UI

- [ ] **5.1 Slack Bolt Setup**
  - [ ] Initialize AsyncApp with Socket Mode
  - [ ] FastAPI lifespan integration

- [ ] **5.2 Message Handling**
  - [ ] Handle all messages (not just @mentions)
  - [ ] Route to LangGraph with channel_id + thread_ts
  - [ ] Parse attachments and include in message context

- [ ] **5.3 Attachment Processing**
  - [ ] Detect attachments in messages
  - [ ] Read/parse attachment content
  - [ ] Check if goal/context is established before processing

- [ ] **5.4 HITL UI (Block Kit)**
  - [ ] Approval message with buttons: Approve / Approve Always / Edit / Reject
  - [ ] Handle button clicks, resume graph execution

- [ ] **5.5 Slash Commands**
  - [ ] `/req-status` - Show graph state and metrics
  - [ ] `/req-config` - Channel configuration modal
  - [ ] `/req-clean` - Clear memory and graph for channel
  - [ ] `/req-approve list` - List permanent approvals
  - [ ] `/req-approve delete <id>` - Remove approval

- [ ] **5.6 Response Formatting**
  - [ ] Format LLM responses with Block Kit
  - [ ] Include metrics context

---

## Phase 6: Personas
> Specialized agents with knowledge bases

- [ ] **6.1 Persona System**
  - [ ] Load persona configs from `personas/<name>/`
  - [ ] Read markdown files as system prompt additions
  - [ ] Support personality parameters (humor, emoji, formality %)

- [ ] **6.2 Persona Routing**
  - [ ] Route to persona when confidence ≥ 95%
  - [ ] Personas: Architect, Product Manager, Security Analyst
  - [ ] Each persona uses configured LLM model

- [ ] **6.3 Default Personas**
  - [ ] Create `personas/architect/` with placeholder docs
  - [ ] Create `personas/product_manager/` with placeholder docs
  - [ ] Create `personas/security_analyst/` with placeholder docs

---

## Phase 7: Approval System
> Permanent approval management

- [ ] **7.1 Approval Storage**
  - [ ] Store approvals in PostgreSQL (channel_id, command_pattern, created_at)

- [ ] **7.2 Approval Logic**
  - [ ] Check permanent approvals before HITL interrupt
  - [ ] Skip interrupt if matching approval exists

- [ ] **7.3 Approval Management**
  - [ ] Implement `/req-approve list`
  - [ ] Implement `/req-approve delete <id>`

---

## Phase 8: Deployment
> GCP VM setup

- [ ] **8.1 Docker Configuration**
  - [ ] Finalize `Dockerfile`
  - [ ] Finalize `docker-compose.prod.yml`

- [ ] **8.2 GCP VM Scripts**
  - [ ] Update `deploy/setup-vm.sh`
  - [ ] Test deployment on VM

- [ ] **8.3 Environment Configuration**
  - [ ] Create `deploy/.env.production` template

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

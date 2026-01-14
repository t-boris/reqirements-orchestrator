# MARO Architecture Documentation

**Multi-Agent Requirements Orchestrator (MARO) v2**

A sophisticated AI-powered system that transforms natural language conversations into structured, validated Jira issues through an 11-phase LangGraph workflow with human-in-the-loop approval.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [The Brain: LangGraph Orchestration](#the-brain-langgraph-orchestration)
3. [State Management](#state-management)
4. [Workflow Phases](#workflow-phases)
5. [Node Architecture](#node-architecture)
6. [Routing Logic](#routing-logic)
7. [Memory System](#memory-system)
8. [Entity Extraction & Knowledge Graph](#entity-extraction--knowledge-graph)
9. [Persona System](#persona-system)
10. [Slack Integration](#slack-integration)
11. [Jira Integration](#jira-integration)
12. [Admin Dashboard](#admin-dashboard)
13. [Configuration](#configuration)
14. [Data Flow Diagrams](#data-flow-diagrams)

---

## System Overview

MARO is built on the following technology stack:

| Component | Technology |
|-----------|------------|
| **Orchestration** | LangGraph StateGraph with PostgreSQL checkpointer |
| **Memory** | Zep Community Edition (long-term memory with semantic search) |
| **Chat Interface** | Slack Bolt (async, Socket Mode) |
| **Issue Tracking** | Jira via MCP (Model Context Protocol) |
| **LLM Providers** | OpenAI, Anthropic, Google (configurable per channel) |
| **Database** | PostgreSQL (state persistence, approvals, config) |
| **Admin UI** | FastAPI + D3.js visualizations |

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Slack Interface                          │
│  (Messages, @mentions, Commands, Approval Buttons)               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph "Brain"                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │ Memory  │→ │ Intake  │→ │ Phases  │→ │ Approval│            │
│  │  Node   │  │  Node   │  │ (1-10)  │  │  Node   │            │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘            │
│       │                                       │                  │
│       ▼                                       ▼                  │
│  ┌─────────┐                           ┌─────────┐              │
│  │   Zep   │                           │  Jira   │              │
│  │ Memory  │                           │  Write  │              │
│  └─────────┘                           └─────────┘              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL                                  │
│  (Checkpoints, Approvals, Channel Config, Knowledge Files)       │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Brain: LangGraph Orchestration

The "brain" of MARO is a **LangGraph StateGraph** that orchestrates requirement processing through multiple specialized nodes. It implements:

- **Actor Model**: Independent nodes processing messages
- **Reflexion Pattern**: Critique loop for self-improvement
- **Human-in-the-Loop**: Interrupt before critical decisions
- **Multi-turn Conversation**: Checkpointing enables resumption
- **State Machine**: Explicit phases with clear transitions

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/graph/state.py` | 419 | State schema (RequirementState, enums) |
| `src/graph/graph.py` | 455 | StateGraph builder, invoke/resume functions |
| `src/graph/routers.py` | 345 | 16 conditional edge routing functions |
| `src/graph/checkpointer.py` | 498 | PostgreSQL persistence |
| `src/graph/nodes/*.py` | 4,238 | 13 node implementation files |

### Graph Compilation

```python
graph = StateGraph(RequirementState)

# Add 23 nodes
graph.add_node("memory", memory_node)
graph.add_node("intake", intake_node)
# ... 21 more nodes

# Add conditional edges with routers
graph.add_conditional_edges("intake", intake_router, {...})

# Compile with checkpointer and interrupt
compiled = graph.compile(
    checkpointer=postgres_checkpointer,
    interrupt_before=["human_approval"]  # HITL pause point
)
```

---

## State Management

The `RequirementState` TypedDict flows through all nodes, containing:

### Input Context
```python
channel_id: str              # Slack channel
thread_ts: str | None        # Thread timestamp
user_id: str                 # Requesting user
message: str                 # Current message
attachments: list[dict]      # Parsed file attachments
is_mention: bool             # Bot was @mentioned
```

### Memory Integration
```python
zep_facts: list[dict]        # Retrieved context from Zep
zep_session_id: str          # Session identifier
related_jira_issues: list    # Cross-referenced issues
messages: Annotated[list, add_messages]  # Conversation history
```

### Intent & Persona
```python
intent: IntentType           # REQUIREMENT, MODIFICATION, QUESTION, JIRA_*
intent_confidence: float     # 0.0-1.0
persona_matches: list        # Matched personas with confidence
active_persona: str | None   # Currently active persona
```

### Workflow Progress
```python
current_phase: WorkflowPhase # Current phase enum
phase_history: list[str]     # Completed phases
progress_steps: list[dict]   # Phase status for UI
```

### Hierarchical Structure
```python
epics: list[dict]            # Epic definitions
stories: list[dict]          # User stories with epic refs
tasks: list[dict]            # Technical tasks with story refs
```

### Analysis & Estimation
```python
architecture_options: list   # 2-3 architecture proposals
chosen_architecture: str     # Selected architecture
total_story_points: int      # Aggregated points
total_hours: float           # Effort estimate
risk_buffer_percent: float   # Risk buffer
validation_report: dict      # Validation results
```

### Human-in-the-Loop
```python
awaiting_human: bool         # Graph paused for decision
human_decision: HumanDecision  # APPROVE, EDIT, REJECT, PENDING
human_feedback: str | None   # Edit feedback from user
```

### Jira Operations
```python
jira_action: str | None      # create, update, link, search
jira_issue_key: str | None   # Created/updated issue
jira_items: list[dict]       # Tracked items with status
```

### Output
```python
response: str                # Message to send
should_respond: bool         # Bot should generate response
response_target: str         # "thread", "channel", "broadcast"
error: str | None            # Error message if failed
```

---

## Workflow Phases

MARO processes requirements through 11 distinct phases:

| Phase | Node | Description |
|-------|------|-------------|
| 1. INTAKE | `intake` | Intent classification, confidence scoring |
| 2. DISCOVERY | `discovery` | Generate clarifying questions if needed |
| 3. ARCHITECTURE | `architecture` | Propose 2-3 architecture options |
| 4. SCOPE | `scope` | Define epics, in/out of scope |
| 5. STORIES | `stories` | Break down into user stories |
| 6. TASKS | `tasks` | Decompose into technical tasks |
| 7. ESTIMATION | `estimation` | Story points, hours, risk buffer |
| 8. SECURITY | `security` | Security review (OWASP Top 10) |
| 9. VALIDATION | `validation` | Check for gaps, conflicts |
| 10. REVIEW | `final_review` | Summary before approval |
| 11. JIRA_SYNC | `jira_write` | Create issues in Jira |

### Phase Flow Diagram

```
User Message
    │
    ▼
┌─────────┐    ┌───────────┐    ┌──────────────┐
│ MEMORY  │───▶│  INTAKE   │───▶│  DISCOVERY   │
└─────────┘    └───────────┘    └──────────────┘
                                       │
                    ┌──────────────────┘
                    ▼
            ┌──────────────┐    ┌─────────┐    ┌──────────┐
            │ ARCHITECTURE │───▶│  SCOPE  │───▶│ STORIES  │
            └──────────────┘    └─────────┘    └──────────┘
                                                    │
                    ┌───────────────────────────────┘
                    ▼
            ┌─────────┐    ┌────────────┐    ┌──────────┐
            │  TASKS  │───▶│ ESTIMATION │───▶│ SECURITY │
            └─────────┘    └────────────┘    └──────────┘
                                                   │
                    ┌──────────────────────────────┘
                    ▼
            ┌────────────┐    ┌────────────┐
            │ VALIDATION │───▶│   REVIEW   │
            └────────────┘    └────────────┘
                                    │
                                    ▼
                           ┌────────────────┐
                           │ HUMAN APPROVAL │ ◀── INTERRUPT POINT
                           └────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌───────────┐   ┌──────────┐
              │ APPROVE  │   │   EDIT    │   │  REJECT  │
              └──────────┘   └───────────┘   └──────────┘
                    │               │               │
                    ▼               ▼               ▼
              ┌──────────┐   ┌───────────┐   ┌──────────┐
              │JIRA WRITE│   │ DISCOVERY │   │ RESPONSE │
              └──────────┘   └───────────┘   └──────────┘
```

---

## Node Architecture

### Node Categories (23 total nodes)

```
src/graph/nodes/
├── common.py (272 lines)     # Shared helpers, LLM utilities
├── intake.py (637 lines)     # Intent classification, initial processing
├── architecture.py (241)     # Phase 3: Architecture exploration
├── planning.py (540 lines)   # Phase 4-6: Scope, stories, tasks
├── analysis.py (630 lines)   # Phase 7-9: Estimation, security, validation
├── review.py (141 lines)     # Phase 10: Final review
├── drafting.py (346 lines)   # Conflict detection, draft/critique loop
├── approval.py (76 lines)    # Human approval, decision processing
├── jira.py (660 lines)       # Jira CRUD operations
├── memory.py (203 lines)     # Zep memory retrieval/update
├── impact.py (210 lines)     # Impact analysis for modifications
├── response.py (150 lines)   # Response generation
└── __init__.py (132 lines)   # Re-exports all nodes
```

### Key Node Descriptions

| Node | Purpose |
|------|---------|
| `memory` | Retrieve Zep context, extract entities, store messages |
| `intake` | LLM classifies intent, identifies matching personas |
| `discovery` | Generates clarifying questions based on knowledge gaps |
| `architecture` | Proposes 2-3 architecture options with trade-offs |
| `scope` | Creates epic definitions, in/out of scope |
| `stories` | Breaks epics into user stories with acceptance criteria |
| `tasks` | Decomposes stories into technical tasks |
| `estimation` | Calculates story points, hours, risk buffer |
| `security` | Security review against OWASP Top 10 |
| `validation` | Checks for gaps, conflicts, completeness |
| `final_review` | Summarizes artifacts before approval |
| `human_approval` | **INTERRUPT POINT** - Pauses for user decision |
| `process_decision` | Routes based on approve/edit/reject |
| `jira_write` | Creates Epic→Story→Task hierarchy in Jira |
| `impact_analysis` | Analyzes modification impact, determines restart phase |

---

## Routing Logic

### 16 Conditional Edge Routers

Each router examines state and returns the next node:

```python
def intake_router(state: RequirementState) -> str:
    if not state.get("should_respond"):
        return "no_response"

    intent = state.get("intent")
    if intent == "JIRA_READ":
        return "jira_read"
    if intent == "REQUIREMENT" and state.get("clarifying_questions"):
        return "discovery"
    if intent == "REQUIREMENT":
        return "architecture"
    # ... more routing logic
```

### Router Summary

| Router | Examines | Routes To |
|--------|----------|-----------|
| `should_respond_router` | `should_respond` flag | response or no_response |
| `intent_router` | `intent` type | Various based on intent |
| `intake_router` | Intent, questions | discovery/architecture/jira |
| `discovery_router` | Has questions? | response or architecture |
| `architecture_router` | Has response? | response or scope |
| `scope_router` | Phase complete? | response or stories |
| `story_router` | Phase complete? | response or tasks |
| `task_router` | Phase complete? | response or estimation |
| `human_decision_router` | `human_decision` | jira_write/discovery/response |
| `impact_router` | `impact_level` | Restart from appropriate phase |

---

## Memory System

### Zep Integration

MARO uses Zep Community Edition for long-term memory with semantic search.

**Location**: `src/memory/zep_client.py`

```python
class ZepMemoryClient:
    async def ensure_session(channel_id, user_id)  # Create/get session

class MemoryOperations:
    async def add(session_id, messages)    # Store messages
    async def get(session_id, limit=10)    # Retrieve recent
    async def search(session_id, text)     # Semantic search
    async def clear(session_id)            # Delete all

class FactOperations:
    async def get_facts(session_id)        # Get extracted facts
    async def add_fact(session_id, fact)   # Add fact manually
```

### Session Management

- **Session ID Format**: `channel-{channel_id}`
- **Storage**: Messages with metadata (user_id, entities, relationships)
- **Retrieval**: Semantic search + recent history

### Memory Node Workflow

```
1. Ensure Session exists in Zep
        │
        ▼
2. Search for relevant past memories
        │
        ▼
3. Extract knowledge from current message (LLM)
   ├── Entities
   ├── Relationships
   ├── Knowledge gaps
   └── Suggested questions
        │
        ▼
4. Merge into Knowledge Graph
        │
        ▼
5. Store message with metadata to Zep
        │
        ▼
6. Return context to workflow
   └── zep_facts, clarifying_questions
```

---

## Entity Extraction & Knowledge Graph

### Entity Types (14 domain-specific)

| Type | Description |
|------|-------------|
| `requirement` | Functional/non-functional requirement |
| `constraint` | Limitations or restrictions |
| `acceptance_criteria` | Conditions for acceptance |
| `risk` | Potential problems/threats |
| `dependency` | System dependencies |
| `stakeholder` | People/roles involved |
| `component` | System components/modules |
| `integration` | External systems/APIs |
| `data_entity` | Database objects |
| `user_action` | User-performable actions |
| `business_rule` | Business logic policies |
| `priority` | Priority levels |
| `timeline` | Deadlines/time constraints |
| `technology` | Technologies/frameworks |

### Relationship Types (10)

| Type | Meaning |
|------|---------|
| `requires` | Entity A requires B to function |
| `implements` | Entity A implements B |
| `depends_on` | Entity A depends on B |
| `conflicts_with` | Contradiction between entities |
| `refines` | Entity A refines/details B |
| `belongs_to` | Hierarchical ownership |
| `affects` | A impacts B |
| `validates` | A validates B |
| `uses` | A uses B |
| `owned_by` | A managed by stakeholder B |

### Knowledge Graph Class

```python
class KnowledgeGraph:
    session_id: str
    entities: dict[str, dict]      # name → entity data
    relationships: list[dict]       # All relationships
    knowledge_gaps: list[dict]      # Identified gaps
    message_count: int              # Messages processed

    def merge_knowledge(knowledge) -> dict  # Merge extracted data
    def get_suggested_questions() -> list   # Generate questions
    def to_dict() / from_dict()             # Serialization
```

### Extraction Output

```json
{
  "entities": [
    {
      "name": "User Authentication",
      "type": "component",
      "description": "OAuth2-based login system",
      "attributes": {"priority": "high"},
      "is_update": false
    }
  ],
  "relationships": [
    {
      "source": "User Authentication",
      "target": "User Database",
      "type": "depends_on"
    }
  ],
  "knowledge_gaps": [
    {
      "entity": "User Authentication",
      "gap_type": "missing_criteria",
      "description": "No acceptance criteria defined"
    }
  ],
  "suggested_questions": [
    "What authentication methods should be supported?"
  ]
}
```

---

## Persona System

### Available Personas

| Persona | Focus Areas | Personality |
|---------|-------------|-------------|
| **Architect** | System design, components, scalability | Formal, low humor, detailed |
| **Product Manager** | User stories, acceptance criteria, priority | Moderate formality, balanced |
| **Security Analyst** | OWASP, compliance, vulnerabilities | Very formal, no humor, thorough |

### Persona Structure

```
personas/
├── architect/
│   └── knowledge.md       # Architecture patterns, design decisions
├── product_manager/
│   └── knowledge.md       # User story formats, INVEST principles
└── security_analyst/
    └── knowledge.md       # Security checklists, OWASP Top 10
```

### PersonaConfig

```python
@dataclass
class PersonaConfig:
    name: str                    # Internal name
    display_name: str            # "Solution Architect"
    description: str             # Role description
    system_prompt: str           # Full LLM system prompt
    knowledge_base: str          # Loaded markdown content
    model: str                   # Preferred LLM model
    personality: PersonalityConfig
    triggers: list[str]          # Activation keywords

@dataclass
class PersonalityConfig:
    humor: float        # 0.0-1.0
    emoji_usage: float  # 0.0-1.0
    formality: float    # 0.0-1.0
    verbosity: float    # 0.0-1.0
```

### Persona Usage in Workflow

| Phase | Persona Used |
|-------|--------------|
| Architecture | Architect |
| Scope | Product Manager |
| Stories | Product Manager |
| Tasks | Architect |
| Estimation | Architect |
| Security | Security Analyst |
| Response | Active persona (from intent) |

---

## Slack Integration

### Event Handling

**Location**: `src/slack/handlers/`

```python
@app.event("message")
async def handle_message(event, say, client):
    # 1. Skip bot messages, edits, deletes
    # 2. Detect @mentions
    # 3. Process file attachments
    # 4. Load channel configuration
    # 5. Initialize progress reporter
    # 6. Create/restore thread state
    # 7. Invoke LangGraph workflow
    # 8. Handle result (approval request or response)
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/req-status` | Show current workflow state |
| `/req-clean` | Clear memory, state, config |
| `/req-config` | Open channel configuration modal |
| `/req-approve list` | List permanent approvals |
| `/req-approve delete <id>` | Delete approval pattern |

### Approval Workflow

```
Graph reaches human_approval node
           │
           ▼
Approval Request Posted (Block Kit UI)
├── Draft Preview (title, type, criteria)
├── Conflicts (if any)
└── Action Buttons:
    ├── [Approve] - One-time approval
    ├── [Approve Always] - Permanent pattern
    ├── [Edit] - Open edit modal
    └── [Reject] - Cancel requirement
           │
           ▼
User clicks button
           │
           ▼
resume_graph(thread_id, decision, feedback)
           │
           ▼
Graph continues from interrupt point
```

### Channel Configuration

Stored per-channel in PostgreSQL:

```python
@dataclass
class ChannelConfig:
    channel_id: str
    jira_project_key: str | None
    jira_default_issue_type: str   # Story/Task/Bug/Epic
    default_model: str             # LLM model selection
    personality: PersonalityConfig # Bot personality traits
    persona_knowledge: dict        # Custom knowledge per persona
```

### Progress Tracking

Real-time Slack message updates as workflow progresses:

```
☐ Analyzing request
☐ Discovery & clarification
☐ Architecture options
☐ Scope definition
☐ Story breakdown
☐ Task breakdown
☐ Estimation
☐ Security review
☐ Validation
☐ Ready for approval
```

Status indicators: `☐` (pending) → `🔄` (in progress) → `✅` (complete)

---

## Jira Integration

### MCP Client

**Location**: `src/jira/mcp_client.py`

```python
class JiraMCPClient:
    async def create_issue(project_key, issue_type, summary,
                          description, priority, labels, parent_key)
    async def update_issue(issue_key, fields)
    async def get_issue(issue_key)
    async def search_issues(jql, max_results)
    async def add_comment(issue_key, body)
    async def delete_issue(issue_key)
    async def link_issues(inward_key, outward_key, link_type)
```

### Hierarchy Creation

```
Epic (created first)
├── Story 1 (linked via Epic Link field)
│   ├── Task 1.1 (parent = Story 1)
│   └── Task 1.2
├── Story 2
│   ├── Task 2.1
│   └── Task 2.2
└── Story 3
```

### Jira Command Nodes

| Node | Trigger | Action |
|------|---------|--------|
| `jira_write` | Approval | Create hierarchy |
| `jira_read` | "re-read PROJ-123" | Fetch latest data |
| `jira_status` | "show status" | Display tracked items |
| `jira_add` | "add story to EPIC-1" | Create linked item |
| `jira_update` | "update PROJ-123" | Modify fields |
| `jira_delete` | "delete PROJ-123" | Remove issue |

### Priority Mapping

| Workflow Priority | Jira Priority |
|-------------------|---------------|
| Must / Critical | Highest |
| Should / High | High |
| Could / Medium | Medium |
| Won't / Low | Low |

---

## Admin Dashboard

### Routes Overview

**Location**: `src/admin/routes/`

| Route | Description |
|-------|-------------|
| `/admin/dashboard` | System health, stats, config |
| `/admin/zep/sessions` | List memory sessions |
| `/admin/zep/sessions/{id}` | Session details, messages, facts |
| `/admin/zep/knowledge-graph` | D3.js knowledge graph |
| `/admin/graph/threads` | List workflow threads |
| `/admin/graph/threads/{id}` | Thread state inspection |
| `/admin/graph/mermaid` | Workflow diagram (Mermaid) |
| `/admin/graph/visualize` | Interactive workflow graph |

### Knowledge Graph Visualization

Interactive D3.js force-directed graph showing:

- **Entity nodes**: Color-coded by type
- **Relationship edges**: Labeled with type
- **Knowledge gaps**: Dashed orange nodes
- **Session selector**: View one session at a time
- **Filtering**: By entity type
- **Zoom controls**: In, out, reset

### API Endpoints

```
GET  /admin/api/zep/sessions          # List sessions (JSON)
GET  /admin/api/graph/threads         # List threads (JSON)
DELETE /admin/api/zep/sessions/{id}   # Delete session
DELETE /admin/api/graph/threads/{id}  # Delete thread
GET  /admin/api/knowledge-graph       # Knowledge graph data
GET  /admin/api/graph/data            # Workflow structure
```

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/maro

# Zep Memory
ZEP_API_URL=http://localhost:8001

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

# Jira
JIRA_URL=https://company.atlassian.net
JIRA_USER=user@company.com
JIRA_API_TOKEN=...
JIRA_MCP_URL=http://localhost:3000/sse

# LLM Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...

# Observability
LANGCHAIN_PROJECT=maro
LANGCHAIN_API_KEY=...
```

### Settings Class

**Location**: `src/config/settings.py`

```python
class Settings(BaseSettings):
    environment: str = "development"
    default_llm_model: str = "gpt-4o"

    # Database
    database_url: str

    # Zep
    zep_api_url: str = "http://localhost:8001"

    # Slack
    slack_bot_token: str
    slack_app_token: str

    # Jira
    jira_url: str
    jira_user: str
    jira_api_token: str
    jira_mcp_url: str = "http://localhost:3000/sse"

    # LLM
    openai_api_key: str
    anthropic_api_key: str
    google_api_key: str
```

---

## Data Flow Diagrams

### Complete Message Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      User sends message                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Slack Handler (src/slack/handlers/main.py)                       │
│ ├── Skip bot messages, edits, deletes                           │
│ ├── Detect @mentions and remove mention text                    │
│ ├── Process file attachments                                    │
│ ├── Load channel config from PostgreSQL                         │
│ ├── Initialize ProgressReporter                                 │
│ └── Create/restore thread state                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ LangGraph Workflow (src/graph/)                                  │
│                                                                  │
│ memory ─▶ intake ─▶ discovery ─▶ architecture ─▶ scope ─▶       │
│ stories ─▶ tasks ─▶ estimation ─▶ security ─▶ validation ─▶     │
│ final_review ─▶ HUMAN_APPROVAL (interrupt)                       │
│                       │                                          │
│         ┌─────────────┼─────────────┐                           │
│         ▼             ▼             ▼                           │
│     APPROVE         EDIT        REJECT                          │
│         │             │             │                           │
│         ▼             ▼             ▼                           │
│    jira_write    discovery     response                         │
│         │                                                        │
│         ▼                                                        │
│   memory_update ─▶ response                                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ External Systems                                                 │
│ ├── Zep: Store messages, extract entities, semantic search      │
│ ├── Jira: Create Epic→Story→Task hierarchy                      │
│ └── PostgreSQL: Checkpoints, config, approvals                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Response sent to Slack thread                                    │
└─────────────────────────────────────────────────────────────────┘
```

### Checkpointing Flow

```
Graph Execution
      │
      ▼
┌─────────────────────┐
│  Node completes     │
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Checkpoint saved    │──▶ PostgreSQL langgraph_checkpoints
│ to PostgreSQL       │    ├── thread_id
└─────────────────────┘    ├── checkpoint_id
      │                    ├── parent_checkpoint_id
      ▼                    ├── checkpoint (JSONB state)
┌─────────────────────┐    └── metadata
│ Next node or        │
│ INTERRUPT           │
└─────────────────────┘
      │
      ▼ (if interrupt)
┌─────────────────────┐
│ Graph pauses        │
│ State persisted     │
└─────────────────────┘
      │
      ▼ (user decision)
┌─────────────────────┐
│ resume_graph()      │
│ loads checkpoint    │
│ continues execution │
└─────────────────────┘
```

---

## Summary

MARO v2 is a production-ready requirements orchestration system featuring:

- **Sophisticated LangGraph brain** with 23 nodes and 16 routers
- **11-phase workflow** from intake to Jira creation
- **Human-in-the-loop approval** with edit and rejection paths
- **Long-term memory** via Zep with semantic search
- **LLM-based entity extraction** building knowledge graphs
- **Three specialized personas** (Architect, PM, Security)
- **Full Slack integration** with commands and approval UI
- **Jira MCP integration** for issue hierarchy creation
- **Comprehensive admin dashboard** with D3.js visualizations
- **PostgreSQL persistence** for state, config, and approvals

The architecture follows best practices for:
- Async/await throughout for scalability
- State isolation per conversation thread
- Graceful error handling and degradation
- Streaming support for progress updates
- Modular design with clear separation of concerns

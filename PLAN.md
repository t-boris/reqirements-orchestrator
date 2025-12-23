# MARO v2 - Requirements Workflow Redesign

## Total Progress: 49/53 tasks (92%)

---

## Problem Statement

Current implementation is too simplistic: `message → draft → approve`.

New workflow must be **conversational, multi-phase, and interactive** with:
- Real-time progress indication
- Discovery phase with clarifying questions
- Architecture exploration before committing to scope
- Proper breakdown: Epic → Stories → Tasks
- Estimation and validation
- All personas engaged at right moments

---

## New Workflow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER MESSAGE RECEIVED                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: INTAKE & CLASSIFICATION                                │
│  - Show: "🔄 Analyzing your request..."                          │
│  - Classify intent                                               │
│  - Extract initial entities                                      │
│  - Check if enough context exists                                │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     [Need more info]                [Have enough context]
              │                               │
              ▼                               │
┌─────────────────────────┐                   │
│  PHASE 2: DISCOVERY     │                   │
│  - Ask clarifying Q's   │                   │
│  - Gather requirements  │                   │
│  - Understand goals     │                   │
│  - Loop until complete  │                   │
└─────────────────────────┘                   │
              │                               │
              └───────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: ARCHITECTURE EXPLORATION (Architect Persona)           │
│  - Show: "🏗️ Exploring architecture options..."                  │
│  - Analyze technical feasibility                                 │
│  - Propose 2-3 architecture options with trade-offs              │
│  - ASK USER to choose or discuss further                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: SCOPE DEFINITION                                       │
│  - Show: "📋 Defining project scope..."                          │
│  - Define Epic(s) based on chosen architecture                   │
│  - Set boundaries (in/out of scope)                              │
│  - CONFIRM with user                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: STORY BREAKDOWN (Product Manager Persona)              │
│  - Show: "📝 Breaking down into stories..."                      │
│  - Create user stories from Epic                                 │
│  - Define acceptance criteria                                    │
│  - Prioritize (MoSCoW)                                           │
│  - Show list, ASK for feedback                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 6: TASK BREAKDOWN (Architect Persona)                     │
│  - Show: "🔧 Creating technical tasks..."                        │
│  - Break stories into tasks                                      │
│  - Technical dependencies                                        │
│  - Implementation order                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 7: ESTIMATION                                             │
│  - Show: "⏱️ Estimating effort..."                               │
│  - Story points for stories                                      │
│  - Hours/complexity for tasks                                    │
│  - Total project estimate + risk buffer                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 8: SECURITY REVIEW (Security Analyst Persona)             │
│  - Show: "🔒 Security review..."                                 │
│  - Identify security requirements                                │
│  - Compliance check (SOC2, GDPR, etc.)                           │
│  - Add security stories/tasks if needed                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 9: VALIDATION & COMPLETENESS                              │
│  - Show: "✅ Validating completeness..."                         │
│  - Check for gaps                                                │
│  - Verify INVEST criteria                                        │
│  - Check dependencies resolved                                   │
│  - Generate validation report                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 10: FINAL REVIEW & APPROVAL                               │
│  - Show full summary: Epics → Stories → Tasks                    │
│  - Show estimates                                                │
│  - Approval buttons: Approve All / Edit / Reject                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 11: JIRA SYNC                                             │
│  - Show: "📤 Syncing with Jira..."                               │
│  - Create/Update Epic(s)                                         │
│  - Create/Update Stories linked to Epic                          │
│  - Create/Update Tasks linked to Stories                         │
│  - Report results with links                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 12: CONTINUOUS MONITORING (Always Active)                 │
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     │
│  │ Slack Thread │ ←→  │   MARO Bot   │ ←→  │    Jira      │     │
│  └──────────────┘     └──────────────┘     └──────────────┘     │
│                                                                  │
│  Triggers:                                                       │
│  - New message in thread → Update requirements                   │
│  - "re-read JIRA-123" → Fetch latest from Jira                  │
│  - Jira webhook → Notify about external changes                  │
│  - "@maro add story" → Add to existing Epic                      │
│  - "@maro update JIRA-123" → Modify specific issue               │
│  - "@maro status" → Show current state of all items              │
│  - Daily digest → Summary of changes                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────────────────────┐
              │         DYNAMIC ROUTING ON UPDATES                  │
              │                                                     │
              │  Analyze update impact → Route to appropriate phase │
              │                                                     │
              │  Examples:                                          │
              │  ┌─────────────────────────────────────────────────┐│
              │  │ "Change auth from Okta to Azure AD"            ││
              │  │ → Impact: Architecture change                   ││
              │  │ → Route to: Phase 3 (Architecture)              ││
              │  │ → Then: Re-evaluate scope, stories, tasks       ││
              │  └─────────────────────────────────────────────────┘│
              │  ┌─────────────────────────────────────────────────┐│
              │  │ "Update EPIC-123 description to mention GDPR"  ││
              │  │ → Impact: Minor text change                     ││
              │  │ → Route to: Direct Jira update                  ││
              │  │ → No re-flow needed                             ││
              │  └─────────────────────────────────────────────────┘│
              │  ┌─────────────────────────────────────────────────┐│
              │  │ "Add new role: Auditor with read-only access"  ││
              │  │ → Impact: New functionality                     ││
              │  │ → Route to: Phase 5 (Stories) or Phase 4 (Scope)││
              │  │ → Add stories, tasks, re-estimate               ││
              │  └─────────────────────────────────────────────────┘│
              │  ┌─────────────────────────────────────────────────┐│
              │  │ "Actually we need 10x more users"              ││
              │  │ → Impact: Scale requirement change              ││
              │  │ → Route to: Phase 3 (Architecture)              ││
              │  │ → May change entire approach                    ││
              │  └─────────────────────────────────────────────────┘│
              │  ┌─────────────────────────────────────────────────┐│
              │  │ "Re-estimate after team feedback"              ││
              │  │ → Impact: Estimation only                       ││
              │  │ → Route to: Phase 7 (Estimation)                ││
              │  │ → Update points, no structural changes          ││
              │  └─────────────────────────────────────────────────┘│
              └───────────────────────────────────────────────────┘
```

---

## Progress Indication System

### Immediate Response (within 1 second)
```
🔄 **Processing your request...**

┌────────────────────────────────────────┐
│ ☐ Analyzing request                    │
│ ☐ Discovery & clarification            │
│ ☐ Architecture options                 │
│ ☐ Scope definition                     │
│ ☐ Story breakdown                      │
│ ☐ Task breakdown                       │
│ ☐ Estimation                           │
│ ☐ Security review                      │
│ ☐ Validation                           │
│ ☐ Ready for approval                   │
└────────────────────────────────────────┘
```

### Real-time Updates (edit same message)
```
🔄 **Processing your request...**

┌────────────────────────────────────────┐
│ ✅ Analyzing request                   │
│ ✅ Discovery complete                  │
│ 🔄 Exploring architecture options...   │
│ ☐ Scope definition                     │
│ ...                                    │
└────────────────────────────────────────┘

**Current:** Analyzing microservices vs monolith trade-offs...
```

### Pause for User Input
```
🏗️ **Architecture Options**

Based on your requirements:

**Option A: Monolith** ⭐ Recommended
├─ Single Django app
├─ Pros: Simple, fast to build
├─ Cons: Harder to scale
└─ Estimate: 4-6 weeks

**Option B: Microservices**
├─ Separate services: Auth, Core, Integrations
├─ Pros: Scalable, independent deploy
├─ Cons: Complex, needs K8s
└─ Estimate: 8-10 weeks

Which approach? Reply with A, B, or ask questions.
```

---

## Implementation Checklist

### Phase 0: Infrastructure (5/5) ✅
- [x] Add `WorkflowPhase` enum to state.py
- [x] Add progress tracking fields to state
- [x] Create `src/slack/progress.py` - ProgressReporter class
- [x] Implement Slack message edit for live updates
- [x] Add workflow session persistence (via graph checkpointer)

### Phase 1: Intake Node (4/4) ✅
- [x] Refactor intent_classifier → intake_node
- [x] Add entity extraction (systems, users, requirements)
- [x] Add context sufficiency scoring
- [x] Send immediate progress message

### Phase 2: Discovery Node (3/5)
- [x] Create discovery_node with question generation
- [ ] Implement conversation loop (question → answer → more questions?)
- [x] Store discovered requirements in state
- [x] Add "enough info gathered" detection
- [ ] Update progress on each discovery step

### Phase 3: Architecture Node (5/5) ✅
- [x] Create architecture_exploration_node
- [x] Load full Architect persona knowledge
- [x] Generate 2-3 architecture options with trade-offs
- [x] Format options for Slack with recommendations
- [x] Handle user choice / follow-up questions

### Phase 4: Scope Node (4/4) ✅
- [x] Create scope_definition_node
- [x] Generate Epic(s) from chosen architecture
- [x] Define in-scope / out-of-scope boundaries
- [x] User confirmation with edit option

### Phase 5: Story Breakdown Node (5/5) ✅
- [x] Create story_breakdown_node
- [x] Load Product Manager persona
- [x] Generate user stories with acceptance criteria
- [x] Apply MoSCoW prioritization
- [x] Present stories for user feedback

### Phase 6: Task Breakdown Node (4/4) ✅
- [x] Create task_breakdown_node
- [x] Break stories into technical tasks
- [x] Map dependencies between tasks
- [x] Suggest implementation order

### Phase 7: Estimation Node (4/4) ✅
- [x] Create estimation_node
- [x] Story point estimation (Fibonacci)
- [x] Task hour estimation
- [x] Calculate total + risk buffer

### Phase 8: Security Review Node (4/4) ✅
- [x] Create security_review_node
- [x] Load Security Analyst persona
- [x] Generate security checklist
- [x] Add security stories/tasks if needed

### Phase 9: Validation Node (5/5) ✅
- [x] Create validation_node
- [x] Gap analysis (missing requirements)
- [x] INVEST criteria verification
- [x] Dependency completeness check
- [x] Generate validation report

### Phase 10: Final Review (4/4) ✅
- [x] Create final_review_node
- [x] Build comprehensive summary (tree view)
- [x] Multi-item approval UI (via existing approval system)
- [x] Handle partial approval / edits

### Phase 11: Jira Sync Enhancement (4/4) ✅
- [x] Enhance jira_write_node for hierarchy
- [x] Create Epic first, get key
- [x] Create Stories with Epic link
- [x] Create Tasks with Story link

### Phase 12: Continuous Sync & Impact Analysis (11/12)
- [ ] Implement Jira webhook receiver
- [ ] Handle external Jira updates (notify in Slack)
- [x] "re-read JIRA-XXX" command to fetch latest (jira_read_node)
- [x] "@maro add story to EPIC-XXX" - add to existing Epic (jira_add_node)
- [x] "@maro update JIRA-XXX" - modify specific issue (jira_update_node)
- [x] "@maro status" - show current state of thread items (jira_status_node)
- [x] "@maro delete JIRA-XXX" - delete issue (jira_delete_node)
- [x] **Impact analysis node** - classify update type (impact_analysis_node)
- [x] Route to correct phase based on impact:
  - [x] Architecture impact → Phase 3
  - [x] Scope impact → Phase 4
  - [x] Story/Task impact → Phase 5/6
  - [x] Estimation impact → Phase 7
  - [x] Minor text change → Direct response
- [ ] Cascade updates (arch change → re-eval scope → re-eval stories)
- [ ] Conflict detection on external changes
- [ ] Daily/weekly digest of changes (optional)

### Phase 13: Graph Restructure (6/6) ✅
- [x] Redesign graph.py with phase-based flow (intake → discovery → architecture → scope → stories → tasks → estimation → security → validation → final_review)
- [x] Add conditional edges between phases (all routers added)
- [x] Add all phase nodes with proper routing
- [x] Implement interrupt points for user input (final_review → human_approval)
- [x] Handle conversation continuity (via checkpointer)
- [ ] Test full workflow end-to-end (remaining)

---

## State Schema Updates

```python
class WorkflowPhase(str, Enum):
    INTAKE = "intake"
    DISCOVERY = "discovery"
    ARCHITECTURE = "architecture"
    SCOPE = "scope"
    STORIES = "stories"
    TASKS = "tasks"
    ESTIMATION = "estimation"
    SECURITY = "security"
    VALIDATION = "validation"
    REVIEW = "review"
    JIRA_SYNC = "jira_sync"
    COMPLETE = "complete"

# New state fields
class RequirementState(TypedDict, total=False):
    # ... existing fields ...

    # Workflow tracking
    current_phase: str  # WorkflowPhase value
    phase_history: list[str]  # Completed phases

    # Progress indication
    progress_message_ts: str  # Slack message to update
    progress_steps: list[dict]  # [{name, status, detail}]

    # Discovery
    clarifying_questions: list[str]
    user_answers: list[dict]  # {question, answer}
    discovered_requirements: list[dict]

    # Architecture
    architecture_options: list[dict]  # [{name, description, pros, cons, estimate}]
    chosen_architecture: str

    # Hierarchy
    epics: list[dict]
    stories: list[dict]  # with epic_index
    tasks: list[dict]  # with story_index

    # Estimation
    total_story_points: int
    total_hours: int
    risk_buffer_percent: int

    # Validation
    validation_report: dict  # {gaps, warnings, passed}

    # Jira Sync State
    jira_items: list[dict]  # [{type, key, title, status, last_synced}]
    pending_jira_updates: list[dict]  # Changes to push
    external_changes: list[dict]  # Changes from Jira webhooks
    last_full_sync: str  # ISO timestamp
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/graph/state.py` | Modify | Add WorkflowPhase, new fields |
| `src/graph/nodes.py` | Major | Add 12+ new phase nodes |
| `src/graph/graph.py` | Rewrite | Multi-phase cyclical graph |
| `src/slack/progress.py` | **Create** | Progress indication system |
| `src/slack/handlers.py` | Modify | Integrate progress |
| `src/slack/approval.py` | Modify | Multi-item approval |
| `src/jira/webhook.py` | **Create** | Jira webhook handler |
| `src/jira/sync.py` | **Create** | Bidirectional sync logic |
| `personas/architect/` | Enhance | Architecture patterns |
| `personas/product_manager/` | Enhance | Story templates |
| `personas/security_analyst/` | Enhance | Security checklist |

---

## Example Conversation Flow

```
USER: We want an internal web portal for access requests to GitHub, Jira, GDrive.
      4 roles: Employee, Manager, Security, Admin. Must be SOC2 compliant.

BOT:  🔄 Processing your request...
      ┌──────────────────────────────┐
      │ 🔄 Analyzing request...      │
      │ ☐ Discovery                  │
      │ ☐ Architecture               │
      └──────────────────────────────┘

BOT:  [updates message]
      🔄 Processing your request...
      ┌──────────────────────────────┐
      │ ✅ Analyzing request         │
      │ 🔄 Clarifying requirements...│
      └──────────────────────────────┘

      I have a few questions to ensure I capture everything:

      1. Expected number of users?
      2. How many access requests per day typically?
      3. Existing identity provider (Okta, Azure AD, etc.)?
      4. Timeline constraints?

USER: 500 users, maybe 20-30 requests/day, we use Okta, need MVP in 6 weeks.

BOT:  [updates message]
      🔄 Processing your request...
      ┌──────────────────────────────┐
      │ ✅ Analyzing request         │
      │ ✅ Discovery complete        │
      │ 🔄 Exploring architecture... │
      └──────────────────────────────┘

BOT:  🏗️ **Architecture Options**

      Given: 500 users, 20-30 req/day, Okta, 6-week MVP, SOC2

      **Option A: Django Monolith** ⭐ Recommended for MVP
      ├─ Single Django app with Okta SAML
      ├─ PostgreSQL for data + audit log
      ├─ Celery for async approvals/notifications
      ├─ ✅ Fits 6-week timeline
      ├─ ✅ Simple SOC2 audit surface
      └─ ⚠️ May need refactor for scale later

      **Option B: FastAPI + React SPA**
      ├─ Separate backend/frontend
      ├─ More modern stack
      ├─ ⚠️ 8-10 weeks realistic
      └─ Better for future mobile app

      **Option C: Low-code (Retool + Supabase)**
      ├─ Fastest to MVP (3-4 weeks)
      ├─ ⚠️ Limited customization
      └─ ⚠️ SOC2 depends on vendors

      Which approach? Or need more details?

USER: Let's go with A, Django.

BOT:  [updates message]
      ┌──────────────────────────────┐
      │ ✅ Analyzing request         │
      │ ✅ Discovery complete        │
      │ ✅ Architecture: Django      │
      │ 🔄 Defining scope...         │
      └──────────────────────────────┘

BOT:  📋 **Scope Definition**

      **Epic: Access Request Portal MVP**

      **In Scope:**
      ✅ User authentication via Okta SAML
      ✅ Request form for GitHub/Jira/GDrive
      ✅ Manager approval workflow
      ✅ Security review workflow
      ✅ Admin configuration panel
      ✅ Audit logging (SOC2)
      ✅ Email notifications

      **Out of Scope (Phase 2):**
      ❌ Automatic provisioning (manual for MVP)
      ❌ Mobile app
      ❌ Slack integration
      ❌ Advanced analytics

      Confirm this scope? Or adjust?

[... continues through all phases ...]
```

---

## Priority Implementation Order

1. **Progress indication** - Immediate UX improvement
2. **Discovery node** - Foundation for quality requirements
3. **Architecture exploration** - Key differentiator
4. **Graph restructure** - Enable multi-phase flow
5. **Story/Task breakdown** - Proper decomposition
6. **Estimation** - Business value
7. **Security review** - Compliance
8. **Validation** - Quality assurance
9. **Jira hierarchy** - Full sync

---

## Estimated Effort

| Component | Complexity | Lines |
|-----------|------------|-------|
| Progress system | Medium | ~250 |
| Discovery node | Medium | ~200 |
| Architecture node | High | ~350 |
| Scope node | Medium | ~150 |
| Story breakdown | Medium | ~250 |
| Task breakdown | Medium | ~200 |
| Estimation | Medium | ~150 |
| Security review | Medium | ~200 |
| Validation | Medium | ~200 |
| Continuous sync | High | ~400 |
| Jira webhooks | Medium | ~200 |
| Graph restructure | High | ~400 |
| State updates | Low | ~150 |
| **Total** | | **~3100** |

---

**Last Updated:** 2025-12-23
**Status:** Planning Complete - Ready for Implementation

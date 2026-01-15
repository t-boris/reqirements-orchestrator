# Roadmap: Proactive Jira Analyst Bot

## Milestones

- ✅ **v1.0 MVP** — Phases 1-10 (shipped 2026-01-14) → [Archive](milestones/v1.0-ROADMAP.md)
- 📋 **v1.1 Context** — Phases 11+ (planned)

## Completed Milestones

<details>
<summary>✅ v1.0 MVP (Phases 1-10) — SHIPPED 2026-01-14</summary>

- [x] Phase 1: Foundation (3/3 plans) — completed 2026-01-14
- [x] Phase 2: Database Layer (3/3 plans) — completed 2026-01-14
- [x] Phase 3: LLM Integration (6/6 plans) — completed 2026-01-14
- [x] Phase 4: Slack Router (9/9 plans) — completed 2026-01-14
- [x] Phase 5: Agent Core (4/4 plans) — completed 2026-01-14
- [x] Phase 6: Skills (3/3 plans) — completed 2026-01-14
- [x] Phase 7: Jira Integration (3/3 plans) — completed 2026-01-14
- [x] Phase 8: Global State (5/5 plans) — completed 2026-01-14
- [x] Phase 9: Personas (4/4 plans) — completed 2026-01-14
- [x] Phase 10: Deployment (3/3 plans) — completed 2026-01-14

**Total:** 10 phases, 43 plans, 13,248 LOC

Full details: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

## v1.1 Context (Planned)

### Phase 11: Conversation History
**Goal**: Fetch channel messages before @mention to understand conversation context
**Depends on**: Phase 10
**Research**: Complete (11-RESEARCH.md)
**Plans**: 3 plans in 2 waves

Plans:
- [x] 11-01: History Fetching Service (Wave 1) — completed 2026-01-14
- [x] 11-02: Channel Listening State + Commands (Wave 1) — completed 2026-01-14
- [x] 11-03: Handler Integration + Rolling Summary (Wave 2) — completed 2026-01-14

Features:
- [x] Fetch recent channel messages on @mention
- [x] Thread history fetching for mid-conversation joins
- [x] `/maro enable|disable|status` commands for opt-in listening
- [x] Rolling summary for enabled channels (two-layer context)

### Phase 11.1: Jira Duplicate Handling (INSERTED) — COMPLETE
**Goal**: When duplicates found, allow user to link to existing ticket instead of creating new
**Depends on**: Phase 11
**Research**: None needed
**Plans**: 1 plan

Plans:
- [x] 11.1-01: MVP Duplicate Actions — completed 2026-01-15

**Features (from 11.1-CONTEXT.md):**
- [x] Smart matching with WHY explanation (LLM-generated)
- [x] Link to existing ticket action
- [x] Create new anyway action
- [x] Add as info stub (full implementation in 11.3)
- [x] Show more matches modal
- [x] Confirmation after linking

**Deferred to future phases:**
- Bidirectional sync (Phase 11.4)
- Channel Jira Board (Phase 11.3)
- Comment vs Description contributions (Phase 11.3)

### Phase 11.2: Progress & Status Indicators (INSERTED)
**Goal**: Show visual progress feedback during bot processing
**Depends on**: Phase 11
**Research**: None needed
**Plans**: 4 plans in 3 waves

Plans:
- [x] 11.2-01: ProgressTracker Core (Wave 1) — completed 2026-01-15
- [x] 11.2-02: Skill-Specific Status (Wave 2) — completed 2026-01-15
- [x] 11.2-03: Draft State Badges (Wave 2) — completed 2026-01-15
- [x] 11.2-04: Error Handling Protocol (Wave 3) — completed 2026-01-15

**Features (from 11.2-CONTEXT.md):**
- [x] Timing-based status (only show if >4s)
- [x] Skill-specific status messages
- [x] Long operation handling (>15s bottleneck info)
- [x] Draft state badges (Draft/Approved/Created)
- [x] Error retry visibility with action buttons

### Phase 12: Onboarding UX — COMPLETE
**Goal**: Improve first-time user experience and command discoverability
**Depends on**: Phase 11.2
**Research**: Complete (12-CONTEXT.md)
**Plans**: 3 plans in 2 waves

Plans:
- [x] 12-01: Channel Join Handler with Pinned Quick-Reference (Wave 1) — completed 2026-01-15
- [x] 12-02: Hesitation Detection with LLM Classification (Wave 1) — completed 2026-01-15
- [x] 12-03: Interactive /maro help Command (Wave 2) — completed 2026-01-15

**Features (from 12-CONTEXT.md):**
- [x] Pinned quick-reference when bot joins channel (not a greeting, information)
- [x] Contextual hints using LLM classification (hesitation detection)
- [x] Interactive /maro help with example conversations
- [x] Persona selection buttons from hints

**Core Principle:** MARO's onboarding personality is quiet, observant, helpful only when needed. Teaches by doing, not by lecturing. No mandatory walkthroughs.

### Phase 13: Intent Router
**Goal**: Route messages to correct flow (Ticket/Review/Discussion) before extraction
**Depends on**: Phase 12
**Research**: Complete (13-CONTEXT.md)
**Plans**: 4 plans in 3 waves

Plans:
- [x] 13-01: IntentRouter Node (Wave 1) — classify intent, extend state, wire into graph — completed 2026-01-15
- [x] 13-02: ReviewFlow Implementation (Wave 2) — persona-based analysis, no Jira — completed 2026-01-15
- [x] 13-03: DiscussionFlow + Guardrails (Wave 2) — light responses, graph docs — completed 2026-01-15
- [x] 13-04: Review → Ticket Transition + Tests (Wave 3) — scope gate, regression tests — completed 2026-01-15

**Problem solved:**
Bot treats ALL messages as ticket creation requests. "Propose architecture" triggers ticket draft + duplicate detection instead of persona-based analysis.

**Architecture:**
```
User message → IntentRouter → { TicketFlow | ReviewFlow | DiscussionFlow }
```

**Features:**
- [x] IntentRouter node before extraction (LangGraph branch)
- [x] Structured intent result: `{intent, confidence, persona_hint, topic, reasons}`
- [x] TicketFlow: Extract → Validate → Dedupe → Preview (existing)
- [x] ReviewFlow: Context → Persona analysis → Output (no Jira ops)
- [x] DiscussionFlow: Light response, no cycles
- [x] Guardrails: Review/Discussion don't access Jira
- [x] Explicit overrides: `/maro ticket`, `/maro review`, "create a ticket", "don't create ticket"
- [x] "Turn into ticket" button after review with scope gate
- [x] Regression tests: 53 test cases covering all intents

**DoD:**
- [x] Router node chooses branch: Ticket/Review/Discussion
- [x] Review branch doesn't call Jira tools, doesn't build draft
- [x] Discussion branch responds once and stops
- [x] Logs: intent, confidence, reasons
- [x] [Turn into Jira ticket] button after review

### Phase 13.1: Ticket Reference Handling (INSERTED)
**Goal**: Handle explicit ticket references (SCRUM-XXX) and thread bindings
**Depends on**: Phase 13
**Research**: Complete (13.1-CONTEXT.md)
**Plans**: 1 plan

Plans:
- [x] 13.1-01: TICKET_ACTION Intent + Thread Binding Check (Wave 1) — completed 2026-01-15

**Problem solved:**
When user says "create subtasks for SCRUM-1111", bot should work with that ticket directly instead of creating a new one and asking about duplicates.

**Features:**
- [ ] Ticket reference detection (SCRUM-XXX, PROJECT-123 patterns)
- [ ] TICKET_ACTION intent with ticket_key and action_type
- [ ] Thread binding check before duplicate detection
- [ ] Subtask creation context for existing tickets

### Phase 14: Architecture Decision Records — COMPLETE
**Goal**: Auto-detect architecture decisions and post to channel
**Depends on**: Phase 13
**Research**: Complete (14-CONTEXT.md)
**Plans**: 1 plan

Plans:
- [x] 14-01: Decision Detection + Channel Posting (Wave 1) — completed 2026-01-15

**Problem solved:**
After review discussion, when user approves ("let's go with this"), MARO should post the decision to channel as a permanent record.

**Key concept:**
- Thread = thinking process (working table with blueprints)
- Channel = system state (board with approved decisions)

**Features:**
- [x] Decision detection patterns ("let's go with this", "approved", etc.)
- [x] LLM extracts decision summary from review context
- [x] Post formatted decision to channel (not thread)
- [x] Link back to discussion thread

### Phase 15: Review Conversation Flow
**Goal**: Context-aware intent classification for review continuations
**Depends on**: Phase 14
**Research**: Complete (15-CONTEXT.md)
**Plans**: 1 plan

Plans:
- [ ] 15-01: REVIEW_CONTINUATION Intent + Node (Wave 1)

**Problem solved:**
When user replies to a REVIEW with answers to open questions, bot misclassifies as TICKET. Should recognize as REVIEW_CONTINUATION and continue the discussion.

**Features:**
- [ ] REVIEW_CONTINUATION intent type
- [ ] Context-aware intent classification (check review_context)
- [ ] Review continuation node (synthesize answers, ask for approval)
- [ ] Smooth handoff to decision approval (Phase 14)

### Phase 16: Ticket Operations (Planned)
**Goal**: Implement deferred ticket actions from Phase 13.1
**Depends on**: Phase 13.1
**Research**: None needed
**Plans**: 1 plan

Plans:
- [ ] 16-01: JiraService Operations + Handler Dispatch (Wave 1)

**Problem solved:**
Phase 13.1 left "update" and "add_comment" as stubs. User expects these to work.

**Features:**
- [ ] Update ticket via Jira API (add fields, change status)
- [ ] Add comment to ticket via Jira API
- [ ] Create subtasks for existing ticket

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 3/3 | Complete | 2026-01-14 |
| 2. Database Layer | v1.0 | 3/3 | Complete | 2026-01-14 |
| 3. LLM Integration | v1.0 | 6/6 | Complete | 2026-01-14 |
| 4. Slack Router | v1.0 | 9/9 | Complete | 2026-01-14 |
| 5. Agent Core | v1.0 | 4/4 | Complete | 2026-01-14 |
| 6. Skills | v1.0 | 3/3 | Complete | 2026-01-14 |
| 7. Jira Integration | v1.0 | 3/3 | Complete | 2026-01-14 |
| 8. Global State | v1.0 | 5/5 | Complete | 2026-01-14 |
| 9. Personas | v1.0 | 4/4 | Complete | 2026-01-14 |
| 10. Deployment | v1.0 | 3/3 | Complete | 2026-01-14 |
| 11. Conversation History | v1.1 | 3/3 | Complete | 2026-01-14 |
| 11.1 Jira Duplicate Handling | v1.1 | 1/1 | Complete | 2026-01-15 |
| 11.2 Progress & Status Indicators | v1.1 | 4/4 | Complete | 2026-01-15 |
| 12. Onboarding UX | v1.1 | 3/3 | Complete | 2026-01-15 |
| 13. Intent Router | v1.1 | 4/4 | Complete | 2026-01-15 |
| 13.1 Ticket Reference Handling | v1.1 | 1/1 | Complete | 2026-01-15 |
| 14. Architecture Decisions | v1.1 | 1/1 | Complete | 2026-01-15 |
| 15. Review Conversation Flow | v1.1 | 0/1 | Planned | - |
| 16. Ticket Operations | v1.1 | 0/1 | Planned | - |

# Roadmap: MARO

## Milestones

- [x] **v2.0 MARO 2.0** - Phases 1-7 (shipped 2026-02-02)
- [ ] **v2.1 Smart UX & Observability** - Phase 8+

## Current Milestone: v2.1 Smart UX & Observability

Address UX friction and operational gaps identified in improvement review (docs/improvement-1.rtf).

### Phase 8: Smart UX Layer

**Goal:** Simplify bot interaction with Simple Mode UX, structured button-based questions from LLM, intent audit logging, and observability tooling.

**Source:** docs/improvement-1.rtf + user feedback from production testing

**Scope:**
1. **Simple Mode UX** — Hide complex domain model (entities, lifecycle, processes) behind clean conversational UX. User should never feel "the bot is holding a philosophy congress"
2. **LLM Questions → Buttons** — When the LLM asks the user a question (choices, options, confirmations), the bot MUST render them as Slack buttons, not free-form text
3. **Intent Audit Log** — Persist message → intent → confidence → mode → action for every classification. Enables debugging "why did the bot do that?"
4. **Deterministic Post-Filters** — Entity reference must exist for MODIFY, otherwise downgrade to CONVERSE. Prevent entity_id hallucination
5. **Observability** — Event timeline viewer, entity state inspector (via `/maro inspect` slash command)

**Depends on:** Phase 7
**Plans:** 5 plans in 2 waves

Plans:
- [x] 08-01: LLM Question Extraction + Button Rendering (wave 1)
- [x] 08-02: Intent Audit Logging (wave 1)
- [x] 08-03: Deterministic Post-Filters (wave 1)
- [x] 08-04: /maro inspect Command (wave 2, depends: 02)
- [x] 08-05: Architecture Docs Update (wave 1)

### Phase 9: Decision Lifecycle

**Goal:** Complete the decision lifecycle with amendment, deprecation UI, and Jira notifications. Decisions are currently one-way (record and forget) — this phase adds the ability to amend decisions when teams change their minds, deprecate from Slack UI, and notify Jira when decisions change.

**Source:** Production testing — discovered that ADR links are lost after reload, decisions can't be amended, and Jira has no visibility into decision changes.

**Scope:**
1. **DecisionAmended event** — New domain event for updating decision content in-place while preserving audit trail
2. **RECORD mode amendment detection** — When recording in a thread with existing decision, offer to amend instead of duplicate
3. **Jira notifications** — Post comment to linked Jira issue when decision is deprecated or amended
4. **Deprecation UI** — Slack button to deprecate committed decisions with confirmation flow
5. **Dashboard status** — Show active vs deprecated decisions with visual indicators

**Depends on:** Phase 8
**Plans:** 4 plans in 3 waves

Plans:
- [x] 09-01: Domain layer — DecisionAmended event + amend_decision method (wave 1)
- [x] 09-02: Jira notifications — deprecation and amendment comments (wave 1)
- [ ] 09-03: RECORD mode amendment detection + Slack handlers (wave 2, depends: 01)
- [ ] 09-04: Deprecation UI + dashboard enhancement (wave 3, depends: 01, 02, 03)

---

## Completed Milestones

- [v2.0 MARO 2.0](milestones/v2.0-ROADMAP.md) (Phases 1-7) - SHIPPED 2026-02-02

<details>
<summary>v2.0 MARO 2.0 (Phases 1-7) - SHIPPED 2026-02-02</summary>

Complete rewrite of MARO from v1.x to an event-sourced architecture.

- [x] Phase 1: Foundation (5/5 plans) - completed 2026-02-02
- [x] Phase 2: Slack Integration (5/5 plans) - completed 2026-02-02
- [x] Phase 3: Intent & Modes (6/6 plans) - completed 2026-02-02
- [x] Phase 4: Entity Lifecycle (7/7 plans) - completed 2026-02-02
- [x] Phase 5: Process Orchestration (7/7 plans) - completed 2026-02-02
- [x] Phase 6: Jira Projection (5/5 plans) - completed 2026-02-02
- [x] Phase 7: Polish & Deploy (4/4 plans) - completed 2026-02-02

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v2.0 | 5/5 | Complete | 2026-02-02 |
| 2. Slack Integration | v2.0 | 5/5 | Complete | 2026-02-02 |
| 3. Intent & Modes | v2.0 | 6/6 | Complete | 2026-02-02 |
| 4. Entity Lifecycle | v2.0 | 7/7 | Complete | 2026-02-02 |
| 5. Process Orchestration | v2.0 | 7/7 | Complete | 2026-02-02 |
| 6. Jira Projection | v2.0 | 5/5 | Complete | 2026-02-02 |
| 7. Polish & Deploy | v2.0 | 4/4 | Complete | 2026-02-02 |
| 8. Smart UX Layer | v2.1 | 5/5 | Complete | 2026-02-03 |
| 9. Decision Lifecycle | v2.1 | 2/4 | In progress | - |

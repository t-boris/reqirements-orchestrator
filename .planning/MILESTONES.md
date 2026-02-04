# Project Milestones: MARO

## v2.1 Smart UX & Observability (Shipped: 2026-02-04)

**Delivered:** Structured LLM interaction with button rendering, intent observability, full decision lifecycle (record/amend/deprecate), async Jira notifications via outbox, and ADR lifecycle UI on pinned messages.

**Phases completed:** 8-10 (14 plans total)

**Key accomplishments:**
- Structured follow-up questions with Slack button rendering for seamless LLM-guided conversation flows
- Intent audit logging with millisecond-precision classification chain tracking and /maro inspect command
- Deterministic post-filter validation preventing hallucinated entity references
- Full decision lifecycle management (record → amend → deprecate) with Jira notifications and status indicators
- Event-driven async Jira notifications via outbox pattern, decoupling external API calls from handlers
- ADR pinned message lifecycle UI with status badges and contextual action buttons

**Stats:**
- 44 milestone-specific commits
- 13,618 lines of Python (total codebase)
- 3 phases, 14 plans
- 21 days (2026-01-14 → 2026-02-04)

**Git range:** `feat(08-01)` → `feat(10-05)`

**What's next:** Planning next milestone

---

## v2.0 MARO 2.0 (Shipped: 2026-02-02)

**Delivered:** Complete event-sourced rewrite with Slack bot, intent classification, entity lifecycle, workflow orchestration, and Jira projection.

**Phases completed:** 1-7 (39 plans total)

**Key accomplishments:**
- Event-sourced architecture with PostgreSQL backend and 500-event snapshots
- Slack Bolt integration with message routing, button handlers, and /maro commands
- 2-stage intent classification (PreGates + LLM Router) with 4 SuperModes
- Unified entity lifecycle (Draft -> Proposed -> Approved -> Committed)
- Task-based workflow orchestration with FlowTemplates
- Jira projection with preflight duplicate detection and conflict resolution
- Production deployment (Dockerfile, docker-compose, GCE via Cloud Build)

**Stats:**
- 183 files created/modified
- 8,933 lines of Python
- 7 phases, 39 plans
- 1 day from start to ship

**Git range:** `feat(01-01)` -> `docs(07)`

**What's next:** Add version display via /maro version command

---

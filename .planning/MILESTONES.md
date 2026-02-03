# Project Milestones: MARO

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

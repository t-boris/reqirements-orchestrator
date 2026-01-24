# Phase 32: Product Invariants

**Status:** Not Started
**Objective:** Formalize the system's architectural principles as enforced invariants. Stop being "smart" and become reliable.

**Mantra:** "This is no longer a bot. It's a conversation-native version control system."

---

## Vision

Phase 31 introduced concepts (super-modes, managed sections, commit log). Phase 32 elevates them to **product invariants** — contracts that code cannot violate, not design notes that developers should follow.

The system should feel like a product with clear boundaries, not an OS kernel with infinite configuration.

---

## Invariants

### I1: SuperMode = Sole UI Contract

**Current:** IntentResult has both `intent` (routing) and `super_mode` (user-facing).
**Target:** Users ONLY see super-modes. Intents are internal implementation detail.

| SuperMode | What User Sees | Internal Intents |
|-----------|----------------|------------------|
| BUILD | "Building..." | TICKET, DRAFT_REFINE, DRAFT_TRANSFORM |
| OPERATE | "Operating..." | OPS, TICKET_ACTION |
| DECIDE | "Deciding..." | DECISION |
| THINK | "Thinking..." | REVIEW, ARCHITECTURE |
| CHAT | "Chatting..." | DISCUSSION, GREETING, UNCLEAR |

**Rules:**
- R1.1: All user-facing messages use super-mode labels (never intent names)
- R1.2: Debug mode can show intents (developer tool)
- R1.3: Status line format: `[MODE] Action description`
- R1.4: No new super-modes without explicit decision

### I2: Slack = UI (Formalize State Ownership)

**Current:** "Database is truth, Jira is projection, Slack is presentation" — documented but not enforced.
**Target:** Compile-time separation. Slack handlers cannot write to truth stores directly.

**Architecture:**
```
┌─────────────────────────────────────────────────────┐
│ TRUTH LAYER (Registries)                            │
│ - DecisionStore, WorkItemStore, DraftStore          │
│ - ONLY graph nodes can write                        │
└─────────────────────────────────────────────────────┘
         ↑ read                    ↓ events
┌─────────────────────────────────────────────────────┐
│ PROJECTION LAYER                                    │
│ - JiraSyncService, DecisionSyncService              │
│ - Writes to Jira based on registry state            │
└─────────────────────────────────────────────────────┘
         ↓ update status
┌─────────────────────────────────────────────────────┐
│ PRESENTATION LAYER (Slack)                          │
│ - Handlers, Managers, Block builders                │
│ - Read-only access to registries                    │
│ - Can trigger graph actions via dispatch            │
└─────────────────────────────────────────────────────┘
```

**Rules:**
- R2.1: Slack handlers are read-only for truth stores
- R2.2: Mutations go through graph dispatch
- R2.3: Message failures never block state updates
- R2.4: Presentation can cache but not own state

### I3: Commit Log = Append-Only (Event-Sourced)

**Current:** Decision versions exist, commit log entries exist, but relationship is implicit.
**Target:** Explicit event sourcing. Commit log is authoritative, canonical messages are rebuildable.

**Model:**
```
CommitLogEntry (immutable, append-only)
├── id: UUID
├── entity_type: "decision" | "workitem" | "draft"
├── entity_id: UUID
├── action: "create" | "approve" | "deprecate" | "link" | ...
├── actor: UserRef
├── timestamp: datetime
├── snapshot: JSON  # Full entity state at commit time
└── metadata: JSON  # Additional context

CanonicalMessage (mutable, rebuildable from log)
├── channel_id, message_ts
├── entity_type, entity_id
├── current_version: int
└── last_rebuilt: datetime
```

**Rules:**
- R3.1: Commit log entries are NEVER modified after creation
- R3.2: Canonical messages can be rebuilt from commit log at any time
- R3.3: On conflict, commit log wins (replay rebuilds canonical state)
- R3.4: Delete = soft delete via commit log entry (never physical delete)

### I4: MANAGED_SECTION = Law (CI Enforcement)

**Current:** ManagedSectionError exists, tests validate invariant.
**Target:** CI gate. PRs that could violate managed section invariant fail build.

**Enforcement:**
1. **Static analysis:** Lint rule detecting direct Jira description writes outside managed section functions
2. **Test coverage:** Every code path that touches Jira descriptions must go through managed_sections.py
3. **Runtime validation:** ManagedSectionError is never caught and swallowed

**Rules:**
- R4.1: All Jira description modifications use managed_sections.py
- R4.2: ManagedSectionError bubbles up (never silently caught)
- R4.3: CI fails if managed section invariant tests fail
- R4.4: New Jira field projections require explicit managed section handling

### I5: Draft Lifecycle = 3 User-Facing States

**Current:** Complex lifecycle (EMPTY → SINGLE_ITEM → PLAN → PLAN_REFINED → APPROVED → COMMITTED)
**Target:** 3 user-facing states, internal complexity hidden

| User State | Internal States | User Sees |
|------------|-----------------|-----------|
| **Drafting** | EMPTY, SINGLE_ITEM, PLAN, PLAN_REFINED | "Draft in progress" |
| **Ready** | APPROVED | "Ready to commit" |
| **Published** | COMMITTED | "Published to Jira" |

**Rules:**
- R5.1: User messages use 3-state vocabulary only
- R5.2: Internal lifecycle transitions are hidden from UI
- R5.3: Buttons show user-state actions: "Approve" (Drafting→Ready), "Commit" (Ready→Published)
- R5.4: Status indicators use 3-state colors/icons

---

## Implementation Approach

### Wave 1: Foundations (Parallel)
- 32-01: SuperMode UI contract (R1.x) — update all user-facing strings
- 32-02: Commit log schema (R3.x) — create CommitLogEntry, define events
- 32-03: Draft lifecycle simplification (R5.x) — map internal→user states

### Wave 2: Enforcement (Depends on Wave 1)
- 32-04: Slack layer separation (R2.x) — audit and refactor handlers
- 32-05: CI managed section gate (R4.x) — lint rule + test gate

### Wave 3: Documentation
- 32-06: Architecture docs update — formal invariant documentation

---

## Success Criteria

- [ ] All user-facing messages use super-mode labels (no intent names visible)
- [ ] Slack handlers are provably read-only for truth stores
- [ ] CommitLogEntry table exists with append-only semantics
- [ ] Canonical messages can be rebuilt from commit log
- [ ] CI gate blocks PRs that could violate managed section invariant
- [ ] Draft status shows 3 states to users (internal complexity hidden)
- [ ] Architecture docs reflect invariants as hard rules

---

## Philosophy

> "Now you have the ideal moment for the system to stop being 'smart' and become reliable."

Phase 32 is about hardening. The system has powerful abstractions (super-modes, managed sections, commit logs). Now we make them inviolable — not through documentation but through code structure, type safety, and CI gates.

A conversation-native version control system needs the same guarantees as Git: append-only history, clear ownership, rebuildable state. This phase delivers those guarantees.

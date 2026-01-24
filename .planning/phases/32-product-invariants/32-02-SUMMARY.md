---
phase: 32-product-invariants
plan: 02
subsystem: schemas
tags: [invariants, exceptions, tokens, event-sourcing, append-only]

# Dependency graph
requires:
  - phase: 31-architecture-hardening
    provides: ManagedSectionError concept, commit log design
provides:
  - InvariantViolation exception hierarchy (4 specific types)
  - PreflightToken and OverrideToken for type-safe invariant proof
  - CommitLogEntry with immutability enforcement
  - CommitLogStore with append-only semantics
affects: [32-03, 32-04, 32-05, jira-gateway, preflight-service]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen dataclass with __setattr__ override for immutability"
    - "Token pattern: checks return tokens, APIs require tokens"
    - "Append-only store: no update/delete methods by design"

key-files:
  created:
    - src/schemas/invariants.py
    - src/schemas/tokens.py
    - src/db/commit_log.py
  modified: []

key-decisions:
  - "InvariantViolation uses class attribute invariant_name (not instance)"
  - "PreflightToken has 5-minute TTL, OverrideToken has 10-minute TTL"
  - "CommitLogEntry uses __setattr__ override to enforce immutability at runtime"
  - "CommitLogStore table named event_commit_log to avoid collision with existing commit_log"

patterns-established:
  - "Token pattern: cannot construct token without passing check"
  - "Store pattern: append-only with explicit absence of update/delete"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-24
---

# Phase 32 Plan 02: Invariant Violation Types and Commit Log Schema Summary

**InvariantViolation exception hierarchy with 4 types, PreflightToken/OverrideToken for type-safe proofs, and CommitLogEntry with append-only CommitLogStore**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-24T02:34:04Z
- **Completed:** 2026-01-24T02:37:09Z
- **Tasks:** 3
- **Files modified:** 3 created

## Accomplishments
- InvariantViolation base class with 4 specific violation types for Layer 0 protection
- PreflightToken proves preflight check passed; OverrideToken enables audited emergency bypass
- CommitLogEntry is immutable after creation (raises CommitLogMutation on modification)
- CommitLogStore has NO update/delete methods (append-only by design)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create InvariantViolation exception hierarchy** - `0f518d9` (feat)
2. **Task 2: Create token types for invariant proof** - `c51b43b` (feat)
3. **Task 3: Create CommitLogEntry schema for event sourcing** - `f9f7b91` (feat)

## Files Created/Modified
- `src/schemas/invariants.py` - InvariantViolation hierarchy with 4 specific types and raise_invariant_violation helper
- `src/schemas/tokens.py` - PreflightToken and OverrideToken frozen dataclasses with validation methods
- `src/db/commit_log.py` - CommitLogAction enum, CommitLogEntry immutable dataclass, CommitLogStore append-only store

## Decisions Made
- Table named `event_commit_log` to avoid collision with existing `commit_log` table
- Used dataclass with `__setattr__` override for immutability (more explicit than frozen=True)
- Token TTLs: PreflightToken 5 minutes (normal operation), OverrideToken 10 minutes (emergency)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness
- Layer 0 types defined and ready for integration
- Next plans can use InvariantViolation types in gateway implementations
- CommitLogStore ready for event sourcing integration

---
*Phase: 32-product-invariants*
*Completed: 2026-01-24*

# Known Issues and TODOs

Captured from codebase during Phase 18 (Clean Code).

## Open Issues

### Session/Epic Features (Deferred)

| ID | Source | Description | Status |
|----|--------|-------------|--------|
| ISS-001 | commands.py:63 | Route to session creation in 04-04 | Deferred |
| ISS-002 | commands.py:70 | Implement Jira search in Phase 7 | Completed (Phase 7) |
| ISS-003 | commands.py:74 | Query session status in 04-04 | Deferred |
| ISS-004 | duplicates.py:524 | Update session card with linked thread reference | Deferred |
| ISS-005 | duplicates.py:525 | Update Epic summary with cross-reference | Deferred |
| ISS-006 | binding.py:61,148 | Fetch epic_summary from Jira | Deferred |

### Constraint/Contradiction Features (Deferred)

| ID | Source | Description | Status |
|----|--------|-------------|--------|
| ISS-007 | misc.py:312 | Update constraint status to 'conflicted' in KG | Deferred |
| ISS-008 | misc.py:313 | Add to Epic summary as unresolved conflict | Deferred |
| ISS-009 | misc.py:338 | Mark old constraint as 'deprecated' | Deferred |
| ISS-010 | misc.py:339 | Mark new constraint as 'accepted' | Deferred |
| ISS-011 | misc.py:364 | Mark both as 'accepted' with note | Deferred |

## Resolved Issues

| ID | Description | Resolution | Phase |
|----|-------------|------------|-------|
| - | Jira search implementation | Implemented | Phase 7 |
| - | Intent detection for review vs ticket | Implemented | Phase 13 |

## Notes

- Session and Epic features were part of original design but deprioritized for v1.0
- Constraint/contradiction features relate to knowledge graph updates (not yet implemented)
- These issues are tracked here for future reference; no immediate action required

---

*Last updated: 2026-01-15 (Phase 18)*

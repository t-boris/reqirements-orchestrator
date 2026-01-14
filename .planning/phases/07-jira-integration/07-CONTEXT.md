# Phase 7: Jira Integration - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

Phase 7 is where the system transitions from "smart Slack assistant" to real engineering tool. Before this, we were playing with the brain. Now we're connecting hands that touch production data.

**Core philosophy:** Jira skills are NOT "dumb API wrappers". They are **transactional operations with security policies**.

Without this discipline:
- Duplicate tickets appear
- "Accidental" creations happen
- No way to explain why something appeared in Jira

**The golden rule:** Jira comes AFTER Phase 6 (ask_user + preview_ticket). The approval flow gates the action flow.

### jira_create Flow
1. Check approval record exists and draft_hash matches
2. Verify idempotency key `(session_id, draft_hash, "jira_create")`
3. Map priority through lookup table (never hardcode Jira values)
4. Dry-run log the payload before create
5. Create issue only after all guards pass
6. Post-create: update session → CREATED, save jira_key, update Epic, update Slack UI

### jira_search Flow
- Fast JQL search by summary, project, status
- Returns compact results: key, summary, status, assignee, url
- Decision node uses results as "last defense" before create

</vision>

<essential>
## What Must Be Nailed

- **Determinism over magic** — More if-statements, more guards, less "let LLM decide". LLM advises, Decision node dispatches, Jira skill executes with license to fail only once.

- **Idempotency everywhere** — Unique constraint `(session_id, draft_hash, "jira_create")` in DB. Slack retries and rage-clicks must not create duplicates.

- **Draft hash validation** — If user approved, then something changed, then clicked Create → "Please re-approve". Draft drift is blocked.

- **Environment separation** — JIRA_BASE_URL, JIRA_PROJECT_KEY, JIRA_ENV (dev|staging|prod). Never accidentally create test ticket in production.

</essential>

<specifics>
## Specific Ideas

### Authentication
- API Token + email for now (100%). OAuth later if needed.

### Client Architecture
Not a library wrapper:
```python
jira = JIRA(...)
jira.create_issue(...)
```

But a service with policy:
```python
jira_service.create_ticket(draft, policy)
```

Because we need: validation, idempotency, logging, retry/backoff, dry-run mode.

### jira_create Contract
Input:
- session_id
- draft_hash
- ticket_type: story | task | bug
- priority: low | medium | high | critical (internal)
- requires_approval: true/false
- approval_id (if required)

Priority mapping table:
| Internal | Jira |
|----------|------|
| low | Lowest |
| medium | Medium |
| high | High |
| critical | Highest |

### jira_search Contract
```python
jira_search(query, project, limit=5)
```

Returns:
- issue_key
- summary
- status
- assignee
- url

Fast mode only in Phase 7. Semantic comparison (LLM on top-5) can come later.

### Known Pitfalls
1. **Duplicates from Slack retries** — Solved by idempotency key + unique constraint
2. **Draft drift** — Approve → edit → Create fails with "re-approve please"
3. **Jira field mismatch** — Different projects have different fields/workflows. Either limit to one project or build project-specific mapping layer.

</specifics>

<notes>
## Additional Context

**Philosophical key:** Phase 7 is when the agent becomes *responsible*. Before this, it talked. Now it acts in the real world.

Therefore:
- More guards
- Less magic
- Explicit over implicit

**DoD Summary:**

07-01:
- Jira client works
- Dry-run mode exists
- Environment separation configured
- Retry/backoff + logging

07-02:
- jira_create requires approval
- Idempotent (DB constraint)
- Validates draft_hash
- Writes Jira key to session
- Updates Slack UI after create

07-03:
- jira_search is fast
- Returns compact results
- Used as "last defense" before create

</notes>

---

*Phase: 07-jira-integration*
*Context gathered: 2026-01-14*

# Phase 30: Decision as First-Class Entity

## Requirements

### R1: Decision Entity

Decision is a first-class entity with:
- `id`: UUID
- `channel_id`: channel ownership
- `type`: ARCH | SCOPE | CONSTRAINT | PRIORITY | STRUCTURE | PROCESS
- `title`: short description
- `description`: full explanation
- `status`: PROPOSED → APPROVED → DEPRECATED/REPLACED
- `version`: integer (increments on change)
- `created_at`, `updated_at`, `created_by`, `approved_by`

### R2: DecisionLink

Mapping between Decision and Jira:
- `decision_id`: UUID
- `jira_key`: SCRUM-123
- `field_path`: where decision appears in Jira (e.g., "description.architecture")
- `linked_at`: when mapping was established

### R3: Jira as Projection

Jira is a read-only projection of decisions:
- Decision is the source of truth
- Jira fields are derived from decisions
- On decision change → sync to Jira (not reverse)
- On Jira external change → preflight conflict (not auto-import)

### R4: Decision CRUD

Full lifecycle management:
- **Create**: From explicit user statement ("we decided X") or ARCH detection
- **Read**: Query by channel, type, status
- **Update**: Change creates new version, notifies linked tickets
- **Deprecate**: Mark as deprecated, optionally replace with new decision

### R5: Mapping Rules

How decision types map to Jira fields:
| Decision Type | Jira Field |
|---------------|------------|
| ARCH | Description.Architecture section |
| SCOPE | Description.Scope section |
| CONSTRAINT | Description.Constraints section |
| PRIORITY | Priority field |
| STRUCTURE | Epic/Story decomposition |
| PROCESS | Labels or custom field |

### R6: Decision Preflight

Before syncing decision to Jira:
1. Check if Jira field was modified externally
2. If conflict: show side-by-side, require choice
3. If idempotent: auto-succeed
4. If structural (e.g., deleted ticket): block + explain

### R7: Decision Versioning

- Each change creates new version
- Version history queryable
- Linked tickets reference specific version
- On version change: notify affected tickets

### R8: Decision Registry

Per-channel registry of decisions:
- List all decisions for channel
- Filter by type, status
- Show linked tickets per decision
- Track which decisions are "active" (not deprecated)

### R9: UX Commands

New slash commands:
- `/maro decisions` - List channel decisions with filters
- `/maro decision show <id>` - Show decision details with linked tickets
- `/maro decision change <id>` - Propose change (creates new version)
- `/maro decision deprecate <id>` - Mark as deprecated

### R10: Decision Detection

Detect decision statements in conversation:
- "We decided to..."
- "The architecture will be..."
- "Let's go with..."
- "Approved: ..."

Route to decision creation flow (with user confirmation).

### R11: Decision Cards

Slack UI for decisions:
```
┌─────────────────────────────────────┐
│ 📋 DECISION: Use PostgreSQL for DB  │
│ Type: ARCH | Status: APPROVED       │
│ Version: 2 | Approved by @boris     │
│                                     │
│ Linked tickets:                     │
│ • SCRUM-123: Setup database         │
│ • SCRUM-124: Create schema          │
│                                     │
│ [Change] [Deprecate] [Show history] │
└─────────────────────────────────────┘
```

### R12: Decision in Context

Include active decisions in:
- Draft extraction context
- Review analysis context
- Duplicate detection context
- Bot responses about architecture

---

## Philosophy

**Mantra:** "Decisions are versioned, Jira is a projection."

The conversation establishes truth. Decisions formalize that truth. Jira displays that truth to external systems. Changes flow from conversation → decision → Jira, never in reverse without explicit human choice.

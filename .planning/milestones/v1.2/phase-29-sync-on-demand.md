# Phase 29: Sync on Demand

## Goal

Pull changes from Jira for all tracked tickets in a channel. Detect external modifications and update local database.

**Trigger:** `/maro sync` or "sync Jira" message

---

## User Story

> As a user, I want to sync my channel with Jira so that I see changes made directly in Jira (by teammates, automation, etc.)

---

## Current State

- `SYNC_REQUEST` intent exists but pushes TO Jira (decisions → tickets)
- `JiraRegistryStore` tracks channel → Jira key mappings
- No mechanism to pull FROM Jira
- No change detection for external modifications

---

## Design

### 29.1: Jira Registry Enhancement

Add fields to track sync state:

```python
@dataclass
class JiraIssueLink:
    # existing fields...
    summary: Optional[str]
    issue_type: Optional[str]
    # new fields
    status: Optional[str]          # To Do, In Progress, Done
    assignee: Optional[str]        # Jira account ID
    jira_updated: Optional[datetime]  # Jira's updated timestamp
    last_synced: Optional[datetime]   # When we last synced
```

**DB Migration:**
```sql
ALTER TABLE jira_registry ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE jira_registry ADD COLUMN IF NOT EXISTS assignee TEXT;
ALTER TABLE jira_registry ADD COLUMN IF NOT EXISTS jira_updated TIMESTAMPTZ;
ALTER TABLE jira_registry ADD COLUMN IF NOT EXISTS last_synced TIMESTAMPTZ;
```

### 29.2: Sync Service

New service: `src/sync/jira_sync.py`

```python
@dataclass
class SyncChange:
    jira_key: str
    field: str          # summary, status, assignee, etc.
    old_value: str
    new_value: str

@dataclass
class SyncResult:
    total_checked: int
    updated: int
    unchanged: int
    failed: int
    changes: list[SyncChange]
    errors: list[str]

class JiraSyncService:
    async def sync_channel(self, channel_id: str) -> SyncResult:
        """Sync all tracked tickets in channel with Jira."""

    async def sync_ticket(self, channel_id: str, jira_key: str) -> list[SyncChange]:
        """Sync single ticket and return detected changes."""
```

**Sync logic:**
1. Get all tickets from `JiraRegistryStore.get_channel_issues()`
2. For each ticket:
   - Fetch from Jira API
   - Compare fields with registry cache
   - Detect changes
   - Update registry with fresh data
3. Return summary of changes

### 29.3: Sync Handler

Update `src/graph/nodes/sync_trigger.py` to handle pull sync:

```python
async def sync_trigger_node(state: AgentState) -> dict:
    """Handle SYNC_REQUEST intent.

    Two modes:
    - Push: sync local decisions TO Jira (existing)
    - Pull: sync Jira changes TO local (new)
    """
    intent_result = state.get("intent_result", {})

    # Detect mode from user message
    # "sync Jira" / "pull from Jira" / "check for updates" → pull
    # "push to Jira" / "update Jira" → push
```

### 29.4: Sync UI

Slack blocks for sync results:

```
┌─────────────────────────────────────────────┐
│ 🔄 Synced 5 tickets with Jira               │
│                                             │
│ Changes detected:                           │
│ • SCRUM-163: status In Progress → Done      │
│ • SCRUM-164: assignee → @john               │
│ • SCRUM-165: summary changed                │
│                                             │
│ 2 unchanged, 0 failed                       │
│ Last sync: just now                         │
└─────────────────────────────────────────────┘
```

---

## Implementation Order

1. **29.1** - Registry enhancement (add sync fields)
2. **29.2** - Sync service (core logic)
3. **29.3** - Sync handler (integrate with graph)
4. **29.4** - Sync UI (blocks and messages)

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/db/jira_registry.py` | Modify | Add sync fields, update methods |
| `src/sync/__init__.py` | Create | New sync module |
| `src/sync/jira_sync.py` | Create | JiraSyncService |
| `src/graph/nodes/sync_trigger.py` | Modify | Add pull mode |
| `src/slack/blocks/sync.py` | Create | Sync result blocks |
| `src/slack/handlers/sync.py` | Modify | Handle sync UI |

---

## Edge Cases

1. **Ticket deleted in Jira** - Mark as "deleted externally", don't remove from registry
2. **API rate limits** - Batch requests, add delays if needed
3. **Large channels** - Paginate, show progress for >20 tickets
4. **Concurrent sync** - Prevent multiple syncs at once (per channel lock)

---

## Out of Scope (Future)

- Jira webhooks (requires HTTP endpoint)
- Automatic periodic sync (cron)
- Two-way conflict resolution (both changed)
- WorkItem sync (only registry for now)

---

## Verification

1. Create ticket in Jira directly (not through Maro)
2. Run `/maro sync` in channel
3. Verify ticket appears in registry with correct data
4. Change ticket in Jira (rename, change status)
5. Run `/maro sync` again
6. Verify changes detected and reported

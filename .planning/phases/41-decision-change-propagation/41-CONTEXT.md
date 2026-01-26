# Phase 41: Decision Change Propagation — Context

## Problem Statement

When a decision is edited, deprecated, or deleted, the channel loses its "source of truth" status if Jira and other artifacts continue to live as if nothing happened. This leads to chaos and users losing trust in the bot.

**Core Invariant:** Decision = primary object. Jira issues = projection of decisions.

Any action on a decision must have impact analysis:
- Which Jira issues reference this decision
- Which pinned messages/indexes depend on it
- Which other decisions/constraints are linked

Then:
- Auto-update where safe
- Request confirmation where risky

---

## Decision Operations

### A) Edit / New Version (most common)

- Decision vN → vN+1
- Pinned message updates (HEAD)
- Jira issues get managed section update (if linked)

**Can be automatic with notification.**

### B) Deprecate (recommended over delete)

- Decision marked DEPRECATED
- Pinned card shows "Deprecated" prominently
- Jira issues get note: "Decision deprecated, see successor / status"
- Nothing deleted from history

**Can be automatic with notification.**

### C) Delete (almost always a bad idea)

Deletion destroys auditability. Allow only if:
- Decision was never approved
- Or it's a clear error/duplicate
- And only for admins

Even then — use tombstone: `DeletedDecisionRecord` (store deletion fact).

---

## Link Registry

Table of relationships (already emerging in codebase):

```
decision_links:
  - decision_id → jira_issue_key (many-to-many)
  - decision_id → pinned_message_ts
  - decision_id → workitem_id (if exists)
  - decision_id → baseline_arch_id (if referencing)
```

Decision change triggers:
1. Compute impact set
2. Show user what will be affected
3. Apply after confirmation

---

## DecisionChangePropagation Flow

### Step 0: Create Change Operation

On button press (DECISION_EDIT / DECISION_DEPRECATE / DECISION_DELETE):

```python
DecisionChangeOp:
  op_id: UUID
  decision_id: str
  from_version: int
  to_version: int | None  # None for deprecate/delete
  status_change: str | None  # "deprecated", "deleted"
  actor: str
  created_at: datetime
  state: Literal["PROPOSED", "CONFIRMED", "APPLYING", "DONE", "FAILED", "CANCELLED"]
```

### Step 1: Impact Analysis (auto)

Collect:
- Linked Jira issues (keys)
- Pinned artifacts affected (index, baseline)
- Conflicts: Jira updated externally? (preflight)
- Risk: how many objects, which fields

### Step 2: UI Confirmation

In thread under decision or in channel:

```
Decision change summary card:
  "You are updating DEC-12 v3 → v4"
  "Will update 7 Jira tickets (managed sections only)"
  "Will update Channel Index"
  "2 tickets changed in Jira since last sync — may conflict"

Buttons:
  [Apply updates]
  [Apply to Slack only] (if user wants to manually edit Jira)
  [Cancel]
```

**Rule:** If impact includes Jira write → always confirm (even if confidence 1.0)

### Step 3: Apply (transactionally)

Order of application:
1. Update decision state in DB (new version/deprecate) — always first
2. Update pinned decision message (Slack) — if fails, retry, but DB is already truth
3. Update channel index pinned
4. Jira updates:
   - MANAGED_SECTION_ONLY
   - Include decision_version marker in text for traceability
   - Idempotent patch (by op_id)

### Step 4: Result + Rollback Options

Post result:
- Updated: N
- Failed: M with reasons

Buttons:
- [Retry failed]
- [Rollback Jira patches] (if needed)
- [Open diff]

---

## Handling Decision "Deletion" When Jira Already Created

**Must-have rule:** deletion = deprecate + tombstone.

### Pinned decision message:
- Replaced with "DEPRECATED/DELETED — reason — by @user — successor link"
- Never disappears (links would break)

### Jira issues:
- Managed section updated:
  - "This ticket referenced decision DEC-12 which was deprecated/deleted."
  - "See replacement DEC-15 (if exists)"
  - "Status: decision invalidated"

**Critical for trust.**

---

## Anti-Pattern: Silent Mass Updates

Auto-updating "all linked entities" without visibility looks like "bot rewrote Jira".

Product style "reliable & calm" means:
- Immediately notify
- Show impact
- Apply after confirmation
- Offer rollback

---

## v1 Minimum Requirements

To ship quickly without "3-month architecture":

1. **decision_links registry table** — decision↔jira relationships
2. **DecisionChangeOp + impact preview card** — show what changes
3. **MANAGED_SECTION_ONLY patch in Jira** — safe writes
4. **Deprecate instead of delete** (delete only for unapproved)
5. **Update pinned decision message + pinned index**

---

## UI: Decision Card Buttons

### Current State (from Phase 30):
```
Approved Decision Card:
  [Change] [Deprecate] [Show history]
```

### Target State:
```
Approved Decision Card:
  [Edit] → opens edit modal/thread
  [Deprecate] → shows impact preview, then applies
  [Delete] → only if never approved; shows impact, requires confirm
  [Show details] → full decision view
```

Each button triggers DecisionChangeOp flow.

---

## Database Schema Additions

### decision_change_ops table

```sql
CREATE TABLE decision_change_ops (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id UUID NOT NULL REFERENCES decisions(id),
  operation TEXT NOT NULL,  -- 'edit', 'deprecate', 'delete'
  from_version INTEGER NOT NULL,
  to_version INTEGER,
  actor TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'PROPOSED',
  impact_summary JSONB,  -- {jira_keys: [...], artifacts: [...]}
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  confirmed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error_details TEXT
);

CREATE INDEX idx_decision_change_ops_decision ON decision_change_ops(decision_id);
CREATE INDEX idx_decision_change_ops_state ON decision_change_ops(state);
```

### decision_links enhancement

Existing `decision_links` table may need:
- `last_synced_version` — track which version was synced to Jira
- `sync_status` — 'synced', 'pending', 'failed'

---

## Success Criteria

- [ ] Edit/deprecate/delete buttons trigger DecisionChangeOp
- [ ] Impact analysis shows affected Jira tickets
- [ ] Jira writes require user confirmation
- [ ] DB updated first (truth), then Slack, then Jira
- [ ] Failed updates can be retried
- [ ] Deprecated decisions show successor link
- [ ] Never silent mass updates

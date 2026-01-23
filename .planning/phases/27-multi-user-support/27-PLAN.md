# Phase 27: Multi-User Support — Implementation Plan

**Mantra:** Every statement has an author, every action has an approver, every conflict has a resolution path.

**Total Requirements:** 23 requirements across 9 groups
**Estimated Sub-Phases:** 6

---

## Architecture Analysis

### What Already Exists

| Component | Current State | Gap |
|-----------|--------------|-----|
| `AgentState.user_id` | Single user per request | Need multi-user tracking per draft |
| `WorkItem.created_by` | Creator only | Need editors[], watchers[] |
| `ApprovalStore` | First-wins with hash | Need state_version binding |
| `CommitEntry.committed_by` | Actor tracked | Already good |
| `SessionIdentity` | (team, channel, thread) | Need user_id in identity |
| Message handling | user_id extracted in handlers | Need centralized attribution |

### Key Data Model Changes Needed

1. **User Identity** — Store Slack user metadata (display_name, team_id)
2. **Draft Attribution** — Track who said what in multi-author drafts
3. **Approval State Binding** — Approvals tied to state_version, not just hash
4. **Participant Map** — Active users per thread/channel

---

## Sub-Phase Breakdown

### Phase 27.1: User Identity & Attribution Foundation

**Requirements:** R1, R2, R5 (partial)
**Risk:** Low
**Dependencies:** None

**Goal:** Store user identity and attribute every statement to its author.

**Components:**

1. **UserMetadataStore** (NEW)
   ```python
   # src/db/user_metadata_store.py
   class UserMetadata(BaseModel):
       slack_user_id: str  # Primary key
       team_id: str
       display_name: str
       real_name: Optional[str]
       email: Optional[str]
       avatar_url: Optional[str]
       last_seen_at: datetime

   class UserMetadataStore:
       async def upsert(slack_user_id, team_id, display_name, ...) -> None
       async def get(slack_user_id) -> UserMetadata | None
       async def get_display_name(slack_user_id) -> str  # For formatting
   ```

2. **MessageAttribution** model
   ```python
   # src/schemas/attribution.py
   class MessageAttribution(BaseModel):
       author_user_id: str
       source_message_ts: str
       source_permalink: Optional[str]
       confidence: float = 1.0  # For extracted statements
   ```

3. **Update TicketDraft** — Add `attributions: dict[str, MessageAttribution]`
   - Keys: field names (summary, description, constraint_0, etc.)
   - Values: Who said/wrote each part

4. **Handler updates** — Capture user metadata on every message

**Files:**
| File | Action |
|------|--------|
| `src/db/user_metadata_store.py` | NEW |
| `src/schemas/attribution.py` | NEW |
| `src/schemas/draft.py` | Modify — add attributions |
| `src/slack/handlers/core.py` | Modify — upsert user metadata |
| `src/graph/nodes/extraction.py` | Modify — track attribution |

---

### Phase 27.2: Participant Map & Turn-Taking

**Requirements:** R7, R8, R9
**Risk:** Medium
**Dependencies:** 27.1

**Goal:** Track who's in a thread, handle concurrent requests.

**Components:**

1. **ThreadParticipantStore** (NEW)
   ```python
   class ThreadParticipant(BaseModel):
       thread_ts: str
       channel_id: str
       user_id: str
       first_seen_at: datetime
       last_message_at: datetime
       message_count: int

   class ThreadParticipantStore:
       async def record_message(channel_id, thread_ts, user_id) -> None
       async def get_participants(channel_id, thread_ts) -> list[ThreadParticipant]
       async def get_active_participants(channel_id, thread_ts, since_minutes=30) -> list
   ```

2. **Request serialization** — One pending_action at a time per thread
   - Already have `pending_action` in state
   - Add `queued_requests: list[dict]` for multiple concurrent messages
   - Reply "Processing X, your request queued" when busy

3. **Mention rules**
   - Direct question → reply with @user mention
   - General message → neutral "Team,"
   - Max 2 @mentions per message

**Files:**
| File | Action |
|------|--------|
| `src/db/participant_store.py` | NEW |
| `src/slack/handlers/core.py` | Modify — record participation |
| `src/schemas/state.py` | Modify — add queued_requests |
| `src/slack/formatting.py` | Modify — mention rules |

---

### Phase 27.3: Multi-Author Drafts & Conflict Detection

**Requirements:** R10, R11, R12
**Risk:** High
**Dependencies:** 27.1, 27.2

**Goal:** Multiple users can edit same draft; conflicts are surfaced with attribution.

**Components:**

1. **DraftEdit tracking**
   ```python
   class DraftEdit(BaseModel):
       edit_id: str
       draft_id: str
       user_id: str
       field: str  # Which field changed
       old_value: str
       new_value: str
       source_message_ts: str
       edited_at: datetime
   ```

2. **Conflict detection**
   - When new message contradicts existing constraint:
     - Show conflict with attribution:
       ```
       Conflict detected:
       - X proposed by @A (link)
       - Y decided by @B (link)
       Which should we follow? [X] [Y]
       ```
   - Conflict not resolved until explicit selection

3. **DraftEditStore** — Track edit history

**Files:**
| File | Action |
|------|--------|
| `src/db/draft_edit_store.py` | NEW |
| `src/schemas/conflict.py` | NEW |
| `src/graph/nodes/extraction.py` | Modify — detect contradictions |
| `src/slack/blocks/conflict.py` | NEW — conflict UI |
| `src/slack/handlers/conflict.py` | NEW — resolution handlers |

---

### Phase 27.4: State-Bound Approvals

**Requirements:** R13, R14, R15
**Risk:** Medium
**Dependencies:** 27.1

**Goal:** Approvals tied to exact state version; first-wins with audit.

**Components:**

1. **Enhance ApprovalRecord**
   ```python
   class ApprovalRecord(BaseModel):
       # Existing
       session_id: str
       draft_hash: str
       approved_by: str
       approved_at: datetime
       status: str

       # NEW
       state_version: int  # From AgentState.state_version
       ui_version: int  # From AgentState.ui_version
   ```

2. **Button payload** — Include state_version
   - All approve buttons: `{"action": "approve", "state_version": 5, "draft_hash": "..."}`
   - On click: Compare state_version → if outdated: "This preview is outdated. Please review the updated version."

3. **Approval policy** (per channel)
   ```python
   class ApprovalPolicy(str, Enum):
       ANY_CONTRIBUTOR = "any_contributor"  # Anyone can approve
       ONLY_ADMINS = "only_admins"  # Channel admins only
       TWO_PERSON = "two_person"  # Creator cannot approve own work
   ```

4. **First-wins finalization**
   - Replace buttons with: "Approved by @user at time"
   - Subsequent clicks: "Already approved"

**Files:**
| File | Action |
|------|--------|
| `src/db/approval_store.py` | Modify — add state_version |
| `src/schemas/approval.py` | NEW — ApprovalPolicy |
| `src/db/channel_config_store.py` | Modify — store approval policy |
| `src/slack/handlers/draft.py` | Modify — policy check |
| `src/slack/blocks/draft.py` | Modify — state_version in payload |

---

### Phase 27.5: WorkItem Ownership & Audit Log

**Requirements:** R16, R17, R20, R21
**Risk:** Medium
**Dependencies:** 27.1, 27.4

**Goal:** WorkItems have owners/watchers; all external actions logged.

**Components:**

1. **Enhance WorkItem model**
   ```python
   class WorkItem(BaseModel):
       # Existing
       created_by: str

       # NEW
       owners: list[str] = []  # Responsible users
       watchers: list[str] = []  # Notification recipients
       last_updated_by: str | None = None
   ```

2. **AuditLog table**
   ```python
   class AuditEntry(BaseModel):
       entry_id: str
       channel_id: str
       action_type: str  # jira_create, jira_update, approve, etc.
       actor_user_id: str
       target_type: str  # workitem, jira, draft
       target_id: str
       outcome: str  # success, error
       error_message: Optional[str]
       request_id: Optional[str]
       created_at: datetime
   ```

3. **Explain mode** enhancement (`/maro explain`)
   - Show: intent chosen, state active, why this flow, what happens next
   - "Operator protocol" not chain-of-thought

**Files:**
| File | Action |
|------|--------|
| `src/db/models.py` | Modify — WorkItem owners/watchers |
| `src/db/workitem_store.py` | Modify — update owners/watchers |
| `src/db/audit_store.py` | NEW |
| `src/jira/client.py` | Modify — log all API calls |
| `src/graph/nodes/ops.py` | Modify — enhanced explain |

---

### Phase 27.6: Notifications & Slack UX

**Requirements:** R18, R19, R22, R23
**Risk:** Low
**Dependencies:** 27.2, 27.5

**Goal:** Targeted notifications, low-noise principle.

**Components:**

1. **Targeted notifications**
   - Ask "the right person" (owners/role)
   - Support: @user, user group, "owners of WorkItem"
   - Max 2 @mentions per message

2. **No-response policy**
   - After N attempts (3): commit as "OPEN QUESTION" in work log
   - Don't loop infinitely

3. **Channel-level Jira visibility**
   - Jira links/statuses in channel (not hidden in thread)
   - Thread: preview/buttons/discussion
   - Channel: "official status card"

4. **Low-noise principle**
   - Don't reply to every message in listening mode
   - Reply only if: @mentioned, command, or high-confidence actionable

**Files:**
| File | Action |
|------|--------|
| `src/slack/notifications.py` | NEW |
| `src/db/open_question_store.py` | NEW |
| `src/slack/blocks/status_card.py` | NEW |
| `src/slack/handlers/core.py` | Modify — noise filtering |

---

## Implementation Order

```
27.1 ─────────────────────────────────────────────────→
      ↘
27.2 ──────────────────────────────────────→
              ↘
27.3 ────────────────────────────→  (High risk)
      ↘
27.4 ─────────────────────────→
              ↘
27.5 ──────────────────────→
                    ↘
27.6 ────────────────→
```

**Critical path:** 27.1 → 27.3 (multi-author is highest risk)

---

## Migration Plan

1. **Database migrations**
   - Add columns: `owners`, `watchers`, `last_updated_by` to work_items
   - New tables: user_metadata, thread_participants, draft_edits, audit_log

2. **Backfill**
   - Existing WorkItems: `owners = [created_by]`
   - No user_metadata backfill needed (populated on next message)

3. **Feature flags**
   - `MULTI_USER_ATTRIBUTION` — Enable per-statement attribution
   - `APPROVAL_STATE_BINDING` — Require state_version match
   - `CONFLICT_DETECTION` — Surface contradictions

---

## DoD Tests Mapping

| Test | Requirements | Sub-Phase |
|------|--------------|-----------|
| T1: Two users edit same draft | R10, R11 | 27.3 |
| T2: Two users click approve | R13, R15 | 27.4 |
| T3: Conflict surfaced with attribution | R11, R12 | 27.3 |
| T4: Unauthorized user blocked | R4 | 27.4 |
| T5: Non-directed chatter ignored | R23 | 27.6 |

---

## Risk Assessment

| Sub-Phase | Risk | Mitigation |
|-----------|------|------------|
| 27.1 | Low | Standard CRUD operations |
| 27.2 | Medium | Test concurrent message handling |
| 27.3 | High | Conflict detection needs extensive testing |
| 27.4 | Medium | Button payload format change needs backward compat |
| 27.5 | Medium | Audit logging adds latency — async writes |
| 27.6 | Low | UI changes, well-isolated |

---

## Next Steps

1. Create `27.1-PLAN.md` with detailed implementation steps
2. Implement Phase 27.1 (User Identity & Attribution Foundation)
3. Test with single-user flow (no regression)
4. Proceed to 27.2

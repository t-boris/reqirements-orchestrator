# Phase 27: Multi-User Support Requirements

**Mantra:** In multi-user channels, MARO must be an auditable operator: every statement has an author, every action has an approver, every conflict has a resolution path, and the channel owns the truth.

---

## 1) Identity & Attribution

### R1. User identity capture
For each incoming message MARO stores:
- `slack_user_id` (stable key)
- `display_name` (cosmetic, at event time)
- `team_id`, `channel_id`, `thread_ts`
- `timestamp`, `message_permalink` (if available)

### R2. Author attribution in artifacts
Every extracted statement, decision, requirement, constraint must have:
- `author_user_id`
- `source_message_ts` (or list of sources)
- `confidence_score`

No "the team decided" without source reference.

### R3. Role awareness (optional, planned)
MARO supports roles:
- `admin/owner` - can configure bot
- `contributor` - normal participant
- `watcher` - read-only (if needed)

Roles from:
- Manual config: `/maro role @user architect`
- Slack user groups (if connected)
- Default: all are contributors

---

## 2) Permissions & Safety Policies

### R4. Action authorization
"Dangerous" actions require explicit approval from authorized user:
- `jira_create`, `jira_update`, `jira_transition`, `cancel`, `link`
- Enable listening mode
- Change channel mode/config

Approval records:
- Who clicked
- State version / draft_hash
- When

### R5. Impersonation protection
MARO never says "@user said X" without source.
If no certainty/source, formulate as:
- "In this thread I see a proposal to … (from message at 1:44 PM)"

### R6. Privacy boundaries
- Don't expose DM data to channel without explicit permission
- If discussion in private channel/DM, don't auto-summarize to public channel

---

## 3) Conversation Mechanics in Channels

### R7. Mention and addressing rules
MARO must address responses:
- Direct question from @user → reply mentioning that user
- General question → no @mention, neutral "Team,"

MARO must not ping everyone. Limit:
- Max 1-2 @mentions per message by default
- Rest via "Owners list" or `/maro notify @group`

### R8. Participant map for channel/thread
MARO stores "context participants":
- Who participated in thread (thread participants)
- Who is active in channel (recent posters)

Used for:
- Suggesting who to ask on conflict
- Selecting approvers

### R9. Turn-taking and concurrency
Multiple people can ask questions in same thread simultaneously.
MARO must:
- Serialize important operations (one pending_action at a time per thread)
- Reply "I'm processing X, your request queued"
- Not mix two independent requests into one draft

---

## 4) Multi-User Drafting & Conflicts

### R10. Multi-author draft updates
Draft can be updated by messages from different users.
MARO must log "draft edits":
- Who made change
- What changed (diff summary)
- Source (message_ts)

### R11. Contradiction detection with attribution
If new messages contradict existing constraint/decision:
MARO shows conflict as:
- "Conflict: X vs Y"
- "X proposed by @A (link)"
- "Y decided by @B (link)"

And asks:
- "Which should we follow?" + buttons

Never "bot chose itself".

### R12. Resolution requires explicit selection
Conflict is not resolved until:
- Someone clicked button
- Or gave explicit text confirmation

---

## 5) Approval & Voting Model

### R13. Approvals bound to state version (idempotency)
Approval buttons must contain:
- `channel_id`, `thread_ts`
- `action_type`
- `state_version` / `draft_hash`

Click with outdated version → "Outdated, please refresh preview".

### R14. Who can approve
Configurable policy per channel:
- `any_contributor`
- `only_admins`
- `role_based` (architect approves architecture, PM approves scope)
- `two_person_rule` (for critical operations)

### R15. First-wins behavior for duplicate clicks
First approval applies action and replaces buttons with text:
- "Approved by @user at time"

Repeated clicks → "Already approved".

---

## 6) Channel Registry (Source of Truth)

### R16. WorkItem registry stores ownership + watchers
Each WorkItem in channel has:
- `created_by`
- `owners[]` (responsible)
- `watchers[]` (receive notifications)
- `last_updated_by`

### R17. Work log entries include actor
Each commit/entry contains:
- `actor` (who approved/initiated)
- Source references
- What changed

---

## 7) Notifications & Escalation

### R18. Targeted notifications
MARO must:
- "Ask the right person" (owners/role)
- Not spam the whole channel

Support:
- `@user`
- User group
- "Owners of WorkItem"

### R19. "No response" policy
If MARO awaits response:
- Ping only owners/responsible
- After N attempts, commit as "OPEN QUESTION" in channel work log
- Don't loop infinitely

---

## 8) Auditability & Explainability

### R20. Explain mode shows policy trace
`/maro explain` outputs:
- Which intent was chosen
- Which state was active
- Why this flow was chosen
- What happens next

Not "chain-of-thought", but "operator protocol".

### R21. Every external action is logged
Every Jira API call:
- `request_id`
- `actor`
- `outcome`
- `error` + retry info
- Link to message/commit

---

## 9) Slack UX Requirements

### R22. Channel-level visibility for Jira links
- Jira links/statuses in channel (work board/log), not hidden in thread
- In thread — only preview/buttons/discussion
- In channel — "official status card"

### R23. Low-noise principle
MARO doesn't reply to every message in "listening mode".
Replies only if:
- @mentioned
- Command (`/maro …`)
- Or "monitor requirements" mode enabled (replies only on high-confidence actionable items)

---

## 10) Test/DoD for Multi-user Support

### T1. Two users edit same draft → deterministic result
- Verify edits not lost
- diff/attribution correct

### T2. Two users click approve → first wins + audit
- No duplicates, buttons replaced

### T3. Conflict surfaced with correct attribution
- Shows who said what + links

### T4. Unauthorized user tries to create Jira → blocked
- Explain why + suggest approver

### T5. Non-directed chatter ignored
- No spam

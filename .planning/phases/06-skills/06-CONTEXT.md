# Phase 6: Skills - Context

**Gathered:** 2026-01-14
**Status:** Ready for planning

<vision>
## How This Should Work

Phase 6 turns the "smart graph" from Phase 5 into a polite, controlled bot that can do two essential things in Slack: **ask questions** and **show previews for approval**. If these skills work correctly, everything else becomes a repetition of the pattern.

Skills are:
1. **Deterministic** - no magic inside
2. **Idempotent** - Slack retries don't break things
3. **Narrow** - one responsibility each
4. **Explicit contracts** - clear input/output so the agent can use them safely

The `ask_user` skill should feel like a PM who knows exactly what information they need. The `preview_ticket` skill should feel like reviewing a document before signing - clear, complete, and actionable.

### ask_user Flow
- Posts questions to the thread (max 3 at a time)
- Supports plain text responses by default, with optional inline buttons for quick answers
- Uses semantic matching to correlate responses with questions asked
- Re-asks missing questions (max 2 re-asks before proceeding)
- Graph interrupts at `AWAITING_USER`, resumes when user responds

### preview_ticket Flow
- Shows complete draft with all fields, evidence permalinks inline
- Approve button triggers Jira creation (Phase 7)
- "Request Changes" opens edit modal with full draft fields
- Strict version checking: if draft changed since preview, require re-approval
- After approval: update message to show "Approved by @user", disable buttons

### Idempotency Pattern
- Dedup key: `(session_id, state_version)` - clean with checkpointer
- Button clicks: first wins + ignore subsequent + update message to show approved state
- Approval records stored in PostgreSQL with unique constraint on `(session_id, draft_hash)`
- Duplicate actions return "Already approved by @user" instead of re-processing

</vision>

<essential>
## What Must Be Nailed

- **ask_user interrupt/resume** - Graph pauses cleanly at questions, resumes with user response. This makes the whole system "alive".
- **Idempotency everywhere** - Slack retries and rage-clicks must be handled gracefully. First wins, subsequent are noops with feedback.
- **Version-checked approvals** - User approves exactly what they see. Draft changes invalidate the approval.
- **Explicit parameters** - Skills receive all dependencies as parameters (Slack client, session info, draft). No global state access.

</essential>

<specifics>
## Specific Ideas

### ask_user Specifics
- Input: `channel`, `thread_ts`, `questions[]`, `context` (why asking), `expected_fields[]` (optional)
- Output: `message_ts`, `question_id` (UUID), `status="asked"`
- Both modes: plain text default, optional inline buttons for Yes/No style questions
- Semantic matching: LLM figures out which part of response answers which question
- Re-ask limit: 2 times max, then proceed with what we have

### preview_ticket Specifics
- Input: `channel`, `thread_ts`, `draft`, `preview_id`
- Output: `preview_message_ts`, `preview_id`, `status="posted"`
- Evidence links: show 2-3 key source messages inline in preview blocks
- Button actions: `approve_draft`, `reject_draft` (opens modal)
- Draft hash embedded in button value for version checking

### Edit Modal Specifics
- All draft fields editable: title, problem, solution, AC, constraints, risks
- Client-side validation only (Slack modal validates required fields)
- After submit: replace preview message with updated values, keep buttons

### Approval Record Storage
- PostgreSQL table with unique constraint on `(session_id, draft_hash)`
- Fields: `session_id`, `draft_hash`, `approved_by`, `approved_at`, `status`
- On approve: insert record, if unique violation → already approved

### Skill Architecture
- Skills are async functions that return results (not graph nodes)
- Slack client passed as parameter (explicit dependency injection)
- Decision node decides "when" to call skills, skills handle "how"
- Hybrid tool access: LLM can request tools but Decision node controls execution

</specifics>

<notes>
## Additional Context

Priority order for implementation:
1. `ask_user` + interrupt/resume - makes system "alive" and predictable
2. `preview_ticket` - UI layer on same interrupt mechanism
3. Edit modal - enhancement to preview flow

Key architectural insight: Tools are "how", Decision node is "when". The agent doesn't directly invoke Slack - it goes through the skill layer which handles idempotency and version checking.

The "humans are chaotic, systems stay calm" approach: expect duplicate clicks, retries, and mid-flow changes. Design for them.

</notes>

---

*Phase: 06-skills*
*Context gathered: 2026-01-14*

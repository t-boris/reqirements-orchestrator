# Phase 6: Jira Projection - Context

**Gathered:** 2026-02-02
**Status:** Ready for research

<vision>
## How This Should Work

When a work item gets approved in Slack, it should seamlessly create a Jira issue. The bot isn't just fire-and-forget though — it maintains awareness of what's in Jira.

**Slack → Jira (on approval):**
- Approved work items create Jira issues automatically
- Can update any field (usually description) on existing issues
- Decisions append to linked work items as comments or description sections
- This is the primary flow and should feel effortless

**Jira → Slack (on demand):**
- `/maro sync` command for bulk reconciliation
- "Refresh from Jira" button on individual committed entity cards
- When differences are found, the bot asks the user what to do
- Shows clear diffs, presents options: "Use Jira value", "Keep Slack value", "Merge"
- Never auto-overwrites anything — user always decides

The experience should feel like having a reliable assistant that keeps things in sync but always asks before making changes.

</vision>

<essential>
## What Must Be Nailed

All three equally important:

- **Work items → Jira issues** — Approved work items become Jira issues. This is the core value proposition. Must work reliably.

- **Two-way awareness** — Bot knows what's in Jira and can report status. Not just push-and-forget. When asked, it can tell you "this entity is PROJ-123 and the status in Jira is 'In Progress'".

- **Smooth conflict handling** — When Slack and Jira differ, the experience is clear and non-destructive. Show the diff, let user decide. No silent overwrites, no confusing merge conflicts.

</essential>

<specifics>
## Specific Ideas

**Decision handling:**
- Decisions don't create their own Jira issues
- Instead, they append to a linked work item's Jira issue
- Could be as a comment or as content in a managed section of the description
- Need a way to link a decision to a work item before/during approval

**Conflict resolution UX:**
- Present side-by-side comparison
- "Jira says X, Slack says Y"
- Clear buttons: "Use Jira" / "Keep Slack" / "I'll merge manually"
- User always in control

**Triggers:**
- `/maro sync` — Check all committed entities against Jira, report discrepancies
- "Refresh from Jira" button — Pull latest for one specific entity

</specifics>

<notes>
## Additional Context

The spec (maro_2_0.md Part 10) has detailed designs for:
- Field ownership model (JIRA_OWNED, SLACK_OWNED, SHARED)
- Managed sections (<!-- MARO:START --> markers)
- Preflight conflict detection
- JiraClient wrapper using atlassian-python-api
- JiraSyncService with reconcile()
- SyncDiscrepancy tracking

The spec also covers onboarding (importing from Jira) and webhooks — these are nice-to-have but not essential for Phase 6. Focus on the core sync flow first.

Key architectural constraint: Jira is a "projection" — Slack is source of truth for content. Jira is source of truth for workflow fields (status, assignee).

</notes>

---

*Phase: 06-jira-projection*
*Context gathered: 2026-02-02*

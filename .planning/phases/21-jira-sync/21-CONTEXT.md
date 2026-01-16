# Phase 21: Jira Sync & Management - Context

**Gathered:** 2026-01-16
**Status:** Ready for research

<vision>
## How This Should Work

MARO becomes the single interface for Jira in Slack. When you work in a channel, MARO tracks all Jira issues mentioned and keeps them in sync with channel decisions.

"@Maro update Jira issues" triggers smart sync - MARO finds the delta between what the channel has decided and what Jira shows, then applies obvious updates automatically and asks about conflicts.

Natural language commands work for everything: "change the priority of that ticket to high" - MARO figures out which ticket from context. No need for explicit syntax like "update SCRUM-123 priority=high".

When architecture decisions are approved (Phase 14), related Jira tickets auto-update. The channel is the source of truth, Jira stays in sync.

</vision>

<essential>
## What Must Be Nailed

- **Channel-level tracking** - MARO knows all Jira issues related to a channel's work, not just per-thread
- **Smart auto-sync** - Obvious updates happen automatically, only conflicts require user input
- **Bidirectional awareness** - Changes from either side (Slack decisions OR Jira updates) are visible
- **Pinned board** - A visible dashboard in the channel showing tracked issues with status
- **Natural language commands** - "edit/update/delete" work with context understanding
- **Conflict resolution** - When Slack and Jira disagree, user decides each time (show both versions)

All of these need to work together - not prioritized, all equally important.

</essential>

<specifics>
## Specific Ideas

- Delete operations require confirmation ("Are you sure?") even when explicitly requested
- When an architecture decision is approved (Phase 14 flow), auto-update the related Jira ticket
- Success feels like: "Jira always reflects our latest channel decisions without me thinking about it"
- Conflict resolution is the area of most uncertainty - good candidate for early experimentation

</specifics>

<notes>
## Additional Context

This expands the original "agentic intent classification" scope significantly. The user wants the full Jira sync vision in this phase, not incremental steps.

No specific reference products mentioned - this is a greenfield vision, not copying existing integrations.

The core promise: Jira stays in sync with channel decisions automatically, so users never need to manually update Jira.

</notes>

---

*Phase: 21-jira-sync*
*Context gathered: 2026-01-16*

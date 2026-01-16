# Phase 22: Multi-Ticket from Review - Context

**Gathered:** 2026-01-16
**Status:** Ready for planning

<vision>
## How This Should Work

When a review proposes multiple work items (like "I recommend 4 epics"), clicking "Turn into Jira ticket" should smartly detect all items and offer to create them all.

**The flow:**
1. User clicks "Turn into Jira ticket" on a review response
2. MARO automatically detects all proposed items from the review text
3. Shows a table preview with all items (Type, Title, Description)
4. User can edit/remove/add items before creating
5. One click creates all tickets
6. Rich announcement confirms creation with all ticket links

**The feel:**
- Smart detection - MARO understands "4 epics" or "1 epic with 3 stories"
- Table format is scannable - not overwhelming even with many items
- Preserves hierarchy - if review proposes Epic + Stories, creates them linked
- Real-time feedback - live checkmarks as each ticket is created

</vision>

<essential>
## What Must Be Nailed

- **Accurate detection**: Must correctly identify ALL items from review text, with right types (Epic vs Story)
- **Easy editing**: Full draft editing per item via modal (Title, Problem, Solution, AC)
- **One-click creation**: After preview, single button creates everything

</essential>

<specifics>
## Specific Ideas

**Preview UI:**
- Table format with columns: Type icon, Title, Description (truncated)
- Epics grouped at top, Stories below
- Per-item scope dropdown (Decision only / Full / Custom)
- Edit button per row opens modal with full draft fields
- Remove button per row
- "+ Add item" button for missed items
- Duplicate warning inline: "Similar: SCRUM-123" with option to link instead
- Header shows source: "From Technical Architect Review on Jan 16"

**Hierarchy handling:**
- "4 epics" → 4 separate Epic tickets
- "1 epic with 3 stories" → Epic created first, Stories linked via parent field
- Stories without Epic → suggest linking to tracked Epics in channel

**Creation:**
- Live table update - checkmarks per row as each ticket is created
- Partial success okay - create what we can, report failures, user can retry
- Rich announcement to channel with all ticket links and details

**After creation:**
- Auto-track all created tickets in channel (appears in /maro board)
- Each ticket includes "Source: [Slack thread]" link for traceability

**Smart defaults:**
- Project from channel's configured Jira project
- Labels from persona context (e.g., Security analyst review → "security" label)
- Suggest tracked Epics for orphan stories

**Edge cases:**
- Single item detected → fall back to existing single-ticket preview (richer detail)
- Large batch (10+) → same preview, just longer table
- Cancel with edits → confirm "Discard changes?"
- User leaves and returns → preview persists with active buttons

</specifics>

<notes>
## Additional Context

**Trigger:** Only from "Turn into Jira ticket" button on review responses, not from direct messages.

**Existing infrastructure:** Phase 20 already has multi-ticket handlers, blocks, and state (`MultiTicketState`). Phase 21 has channel tracking. This phase wires them together for the review-to-ticket flow.

**Key insight from user:** The 4 epics case should create 4 *separate* Epics, not 1 Epic + 3 Stories. Only preserve hierarchy when review explicitly proposes that structure.

</notes>

---

*Phase: 22-multi-ticket-from-review*
*Context gathered: 2026-01-16*

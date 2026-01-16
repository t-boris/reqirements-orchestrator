---
created: 2026-01-16T16:10
title: Fix "create user stories for EPIC" creates duplicate instead of stories
area: graph
files:
  - src/graph/intent.py
  - src/graph/nodes/ticket_action.py
---

## Problem

When user says "@Maro Create user stories for SCRUM-113" (an existing epic):

**Expected behavior:**
- Recognize this as a TICKET_ACTION with action_type=create_subtask
- Create multiple user stories linked to the existing epic SCRUM-113

**Actual behavior:**
- Shows a draft preview to create a NEW ticket/epic
- The draft contains the same title/description as the referenced epic
- No user stories are created under the epic

This suggests either:
1. Intent classification is not recognizing "create user stories for EPIC-XXX" as TICKET_ACTION
2. Or the extraction is treating it as a new ticket creation instead of creating stories under the epic

**Log evidence (2026-01-16):**
```
Intent classified by LLM: TICKET, confidence=0.95, persona=pm
reasons: 'The user is reiterating and clarifying a previous request to create multiple Jira entities (epics and stories) based on an existing item. This is an explicit request for ticket creation.'
```

The LLM classifies as TICKET (new ticket) instead of TICKET_ACTION (action on existing ticket).
Even though user explicitly said "create MULTIPLE items based on jira item that already exists".

## Solution

1. Check if intent classification recognizes "create user stories for SCRUM-XXX" pattern
2. Ensure TICKET_ACTION with action_type=create_subtask is triggered
3. Verify ticket_action_node handles multi-story creation under epic
4. May need to add batch story creation logic (20-09/20-10 decisions reference this)

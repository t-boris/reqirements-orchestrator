---
created: 2026-01-16T16:35
title: Make intent classification agentic with tool access
area: graph
files:
  - src/graph/intent.py
  - src/graph/nodes/ticket_action.py
---

## Problem

Current implementation hardcodes specific action types (create_stories, create_subtask, update, add_comment) for TICKET_ACTION. This is brittle because:

1. **Missing cases**: What if user asks to "expand ALL epics"? Or "change epic title"?
2. **Rigid classification**: LLM must pick from predefined action types instead of understanding the request dynamically
3. **No tool access during classification**: LLM can't fetch Jira ticket info to understand context before classifying

User feedback: "The LLM should decide what to do with the request, not hardcoded decisions. Classification should have access to tools to get additional information."

**Examples of what's NOT supported:**
- "Expand all our epics with user stories"
- "Update the title of SCRUM-113"
- "Add acceptance criteria to SCRUM-113 based on our discussion"
- "Split SCRUM-113 into smaller tickets"

## Solution

Make intent classification agentic:

1. **Tool-equipped classification**: Give LLM tools during intent classification:
   - `fetch_jira_ticket(key)` - Get ticket details
   - `search_jira(query)` - Find related tickets
   - `ask_clarification(question)` - Ask user for more info

2. **Open-ended action detection**: Instead of fixed action types, let LLM determine:
   - What information is needed (fetch first)
   - What operation makes sense (after context)
   - What tools to use for execution

3. **Two-phase approach**:
   - Phase 1: Analyze request, call tools to gather context
   - Phase 2: Decide on action with full context

This is a significant refactor - should be a separate phase/milestone.

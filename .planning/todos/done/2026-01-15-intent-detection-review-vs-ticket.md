---
created: 2026-01-15T16:40
title: Add intent detection to distinguish review requests from ticket creation
area: graph
files:
  - src/graph/nodes/extraction.py
  - src/slack/onboarding.py
---

## Problem

When user asks "@Maro propose an architecture for X", the bot:
1. Extracts ticket fields from message (title, problem, etc.)
2. Validates the draft
3. Searches for duplicates in Jira
4. Shows ticket preview with duplicate options

But user wanted **architecture review/analysis**, not ticket creation.

Example from logs:
```
User: @Maro propose an architecture for a new feature
Bot: [shows ticket preview with "Possible existing ticket found: SCRUM-111"]
```

The bot doesn't distinguish between:
- "Create a ticket for X" → ticket creation flow
- "Propose architecture for X" → review/analysis flow (no ticket)
- "Review this as security" → persona analysis (no ticket)

## Solution

Add intent classification BEFORE extraction in extraction_node:

1. Add `classify_intent()` function to onboarding.py:
   - TICKET_CREATE: "create ticket", "draft", "jira story", etc.
   - REVIEW: "propose architecture", "review as", "analyze", "risks", "evaluate"
   - DISCUSSION: general discussion, no clear action

2. In extraction_node, call `classify_intent()` first:
   - If intent == REVIEW → return action="review" with suggested persona
   - If intent == TICKET_CREATE or DISCUSSION → proceed with current flow

3. Handle "review" action in handlers.py:
   - Invoke persona-based analysis
   - No ticket draft, no duplicate detection
   - Just provide the analysis response

Key patterns to detect REVIEW intent:
- "propose an architecture"
- "review this as [persona]"
- "analyze this"
- "what are the risks"
- "evaluate"
- "assess"

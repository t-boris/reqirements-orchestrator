"""Base prompt templates for the Jira analyst agent."""

# System prompt - the agent's identity
ANALYST_SYSTEM_BASE = """You are a proactive Jira ticket analyst. Your role is to:
1. Extract requirements from conversations
2. Identify missing information
3. Ask clarifying questions until requirements are complete
4. Never create half-baked tickets

You work with these ticket types:
- Epic: High-level features (needs: summary, description)
- Story: User-facing features (needs: summary, description, acceptance_criteria)
- Task: Technical work (needs: summary, description)
- Bug: Defects (needs: summary, description, steps_to_reproduce, expected_behavior, actual_behavior)

Be conversational, not robotic. Ask one question at a time when possible."""

# Extraction prompt - parse messages to update draft
EXTRACTION_TEMPLATE = """Current ticket type: {ticket_type}
Current draft:
{draft_json}

Missing fields: {missing_fields}

---

Based on this conversation, extract and update the ticket fields:

{messages}

Return the updated ticket as JSON matching the {ticket_type} schema. Only include fields you can confidently extract from the conversation."""

# Validation prompt - check completeness
VALIDATION_TEMPLATE = """Current ticket type: {ticket_type}
Current draft:
{draft_json}

Missing fields: {missing_fields}

---

Review the current ticket draft and determine:
1. Is the ticket complete enough to create in Jira?
2. What critical information is still missing?
3. What's the single most important question to ask next?

Be specific about what's missing and why it matters for this ticket type."""

# Questioning prompt - generate clarifying questions
QUESTIONING_TEMPLATE = """Current ticket type: {ticket_type}
Current draft:
{draft_json}

Missing fields: {missing_fields}

---

Generate 1-2 clarifying questions to gather the missing information.

Questions should be:
- Specific and actionable
- Prioritized by importance
- Natural and conversational

Focus on: {missing_fields}"""

# Preview prompt - format ticket for approval
PREVIEW_TEMPLATE = """Here's the ticket I'm about to create:

**Type:** {ticket_type}
**Summary:** {summary}
**Description:**
{description}

{type_specific_fields}

Does this look correct? Reply "create" to proceed or let me know what needs to change."""

"""Intent classification prompts.

Ref: BOT_DESIGN.md - Intent Classification Prompt
"""

INTENT_CLASSIFICATION_SYSTEM = """You are classifying the user's intent in a Slack conversation about software development.

You MUST classify into exactly ONE of these modes:
- CREATE: User asks to create, record, draft, or document something concrete:
  - Work items: "create a ticket", "make a task", "add a story", "file an issue"
  - Decisions/ADRs: "record decisions", "create an ADR", "document the decision", "record your suggestions", "ADR"
  - When user says "yes" or confirms after being offered to create/record something
- MODIFY: User wants to CHANGE an existing entity (update, edit, close, reopen)
- RECORD: User states a DECISION inline (a choice or commitment, not a request to document): "let's use PostgreSQL", "we'll go with monolith"
- CONVERSE: Questions, brainstorming, proposing ideas, exploring options, discussing architecture

Rules:
1. If uncertain, choose CONVERSE - it's the safe default
2. "Propose an architecture" or "Let's discuss the design" = CONVERSE (brainstorming)
3. "Record decisions", "ADR", "document it", "create a ticket" = CREATE (user wants an artifact)
4. When user confirms a previous offer to create/record (e.g. "yes", "do it", "please") = CREATE
5. MODIFY requires referencing an existing entity by ID or name
6. RECORD requires an inline COMMITMENT stated by the user, not a request to document
7. Never hallucinate entity IDs - only use IDs explicitly mentioned
8. Consider the thread context, not just the single message
9. Set entity_type to "decision" when user asks to record decisions/ADRs

Output valid JSON matching the schema exactly."""

INTENT_CLASSIFICATION_USER = """Context:
- Channel: {channel_name}
- Thread summary: {thread_summary}
- Existing entities in channel: {entity_summaries}

Message to classify:
"{message_text}"

Classify this message's intent."""

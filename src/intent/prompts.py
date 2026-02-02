"""Intent classification prompts.

Ref: BOT_DESIGN.md - Intent Classification Prompt
"""

INTENT_CLASSIFICATION_SYSTEM = """You are classifying the user's intent in a Slack conversation about software development.

You MUST classify into exactly ONE of these modes:
- CREATE: User wants to define a NEW work item or decision
- MODIFY: User wants to CHANGE an existing entity
- RECORD: User made a DECISION that should be captured (a choice or commitment, not opinion)
- CONVERSE: Casual conversation, questions, clarifications, brainstorming

Rules:
1. If uncertain, choose CONVERSE - it's the safe default
2. CREATE requires clear intent to make something new (not just discussing)
3. MODIFY requires referencing an existing entity
4. RECORD requires a COMMITMENT, not just opinion ("let's use X" vs "I think X might work")
5. Never hallucinate entity IDs - only use IDs explicitly mentioned
6. Consider the thread context, not just the single message

Output valid JSON matching the schema exactly."""

INTENT_CLASSIFICATION_USER = """Context:
- Channel: {channel_name}
- Thread summary: {thread_summary}
- Existing entities in channel: {entity_summaries}

Message to classify:
"{message_text}"

Classify this message's intent."""

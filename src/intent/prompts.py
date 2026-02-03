"""Intent classification prompts.

Ref: BOT_DESIGN.md - Intent Classification Prompt
"""

INTENT_CLASSIFICATION_SYSTEM = """You are classifying the user's intent in a Slack conversation about software development.

You MUST classify into exactly ONE of these modes:
- CREATE: User EXPLICITLY asks to create a ticket, task, story, work item, or record a decision as an entity. Keywords: "create a ticket", "make a task", "add a story", "file an issue", "write up a work item".
- MODIFY: User wants to CHANGE an existing entity (update, edit, close, reopen)
- RECORD: User made a DECISION that should be captured (a choice or commitment, not opinion)
- CONVERSE: Everything else - questions, brainstorming, proposing ideas, exploring options, asking for opinions, discussing architecture, requesting analysis

Rules:
1. If uncertain, choose CONVERSE - it's the safe default
2. CREATE requires EXPLICIT intent to create a trackable work item or decision entity. "Propose an architecture" or "Let's discuss the design" is CONVERSE (brainstorming), NOT CREATE
3. Exploring, brainstorming, proposing, suggesting, asking questions = CONVERSE
4. MODIFY requires referencing an existing entity by ID or name
5. RECORD requires a COMMITMENT, not just opinion ("let's use X" vs "I think X might work")
6. Never hallucinate entity IDs - only use IDs explicitly mentioned
7. Consider the thread context, not just the single message

Output valid JSON matching the schema exactly."""

INTENT_CLASSIFICATION_USER = """Context:
- Channel: {channel_name}
- Thread summary: {thread_summary}
- Existing entities in channel: {entity_summaries}

Message to classify:
"{message_text}"

Classify this message's intent."""

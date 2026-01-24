"""Intent Router for classifying user messages.

Classifies user messages into pure user intents:
- WORKITEM_CREATE: User wants to create a new work item (Jira ticket)
- TICKET_ACTION: User wants to perform actions on an existing ticket
- JIRA_COMMAND: User wants to modify ticket fields via natural language
- SYNC_REQUEST: User wants to sync channel with Jira
- JIRA_SEARCH: User wants to search for existing issues
- REVIEW: User wants analysis/feedback without Jira operations
- DISCUSSION: Casual greeting, simple question, no action needed
- META: Questions about the bot itself
- AMBIGUOUS: Intent unclear - triggers scope gate for user to decide
- OPS: Operational mode (debug failures or explain decisions)
- DECISION: User stating a decision to record (Phase 30)

Pattern matching used for DECISION intent detection.
LLM classification as fallback for all intents.
"""
import logging
import re
from typing import Optional

from src.schemas.intent import Intent, IntentResult, OpsSubtype

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
IntentType = Intent  # Alias for legacy code


# =============================================================================
# Decision statement patterns (Phase 30)
# Pattern-first detection for DECISION intent.
# LLM fallback can still classify as DECISION if patterns miss.
# =============================================================================

DECISION_PATTERNS = [
    # "We decided to use PostgreSQL"
    (r"(?:we|I)\s+decided\s+(?:to\s+)?(.+)", "decided"),
    # "The decision is to..."
    (r"(?:the|our)\s+decision\s+is\s+(.+)", "decision_is"),
    # "Approved: use Redis"
    (r"approved[:.]?\s+(.+)", "approved"),
    # "Let's go with option A"
    (r"(?:let'?s|we(?:'ll)?)\s+go\s+with\s+(.+)", "go_with"),
    # "The architecture will use..."
    (r"(?:the|our)\s+architecture\s+will\s+(?:be|use)\s+(.+)", "arch_will"),
    # "Agreed: ..."
    (r"agreed[:.]?\s+(.+)", "agreed"),
    # "Confirmed: ..."
    (r"confirmed[:.]?\s+(.+)", "confirmed"),
    # "Final call: ..."
    (r"final\s+call[:.]?\s+(.+)", "final_call"),
]

# Decision type hints based on keywords
# Maps from hint type to keywords that indicate it
DECISION_TYPE_KEYWORDS: dict[str, list[str]] = {
    "arch": [
        "architecture", "tech stack", "framework", "library", "database",
        "api design", "microservice", "monolith", "stack", "technology",
        "infrastructure", "platform", "tool", "service",
    ],
    "scope": [
        "scope", "boundary", "include", "exclude", "out of scope", "in scope",
        "mvp", "phase 1", "first version", "later", "future",
    ],
    "constraint": [
        "constraint", "limitation", "must not", "cannot", "required to",
        "must have", "non-negotiable", "hard requirement", "compliance",
    ],
    "priority": [
        "priority", "p0", "p1", "p2", "first", "before", "after", "order",
        "blocker", "critical", "urgent", "important",
    ],
    "structure": [
        "epic", "story", "breakdown", "split", "decompose", "structure",
        "parent", "child", "hierarchy",
    ],
    "process": [
        "process", "workflow", "procedure", "how we", "when we",
        "review process", "approval", "deploy", "release",
    ],
}


def _match_decision_patterns(message: str) -> tuple[bool, Optional[str], Optional[str]]:
    """Match message against decision patterns.

    Returns:
        Tuple of (is_decision, title_hint, pattern_name)
        - is_decision: True if message matches a decision pattern
        - title_hint: Extracted title from pattern group
        - pattern_name: Name of the matched pattern (for logging)
    """
    message_lower = message.lower().strip()

    for pattern, pattern_name in DECISION_PATTERNS:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if match:
            # Extract the captured group as title hint
            title_hint = match.group(1).strip() if match.lastindex else None
            # Capitalize first letter for nicer display
            if title_hint:
                title_hint = title_hint[0].upper() + title_hint[1:] if len(title_hint) > 1 else title_hint.upper()
            return True, title_hint, pattern_name

    return False, None, None


def _detect_decision_type_hint(message: str) -> Optional[str]:
    """Detect decision type from keywords in message.

    Returns the decision type hint (arch, scope, etc.) if keywords match,
    None otherwise.
    """
    message_lower = message.lower()

    for type_hint, keywords in DECISION_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                return type_hint

    return None


async def _llm_classify(
    message: str,
    conversation_context: dict | None = None,
    active_draft: dict | None = None,  # Active draft summary (Phase 26)
) -> IntentResult:
    """Use LLM to classify user intent with full conversation context.

    Args:
        message: User's current message text
        conversation_context: Full conversation history (messages + summary)
        active_draft: Active draft summary for context-aware classification (Phase 26)
    """
    from src.llm import get_llm

    llm = get_llm()

    # Build context string from conversation history
    context_str = ""
    if conversation_context:
        messages = conversation_context.get("messages", [])
        summary = conversation_context.get("summary")

        if summary:
            context_str += f"Conversation summary:\n{summary}\n\n"

        if messages:
            context_str += "Recent messages:\n"
            for msg in messages[-15:]:  # Last 15 messages for context
                user = msg.get("user", "unknown")
                text = msg.get("text", "")
                if text:
                    context_str += f"[{user}]: {text}\n"
            context_str += "\n"

    # Build active draft context (Phase 26)
    draft_context_str = ""
    if active_draft:
        draft_title = active_draft.get("title", "")
        draft_issue_type = active_draft.get("issue_type", "")
        draft_has_content = bool(draft_title)
        if draft_has_content:
            draft_context_str = f"""
ACTIVE DRAFT CONTEXT:
- Title: {draft_title}
- Issue Type: {draft_issue_type or 'not specified'}
- Status: Draft in progress
NOTE: If user asks questions about this draft (structure, scope, decomposition), classify as DRAFT_REFINE, NOT REVIEW.
"""

    prompt = f"""You are classifying user intent for a Slack bot that helps with Jira tickets and architecture discussions.

{f"CONVERSATION CONTEXT:{chr(10)}{context_str}" if context_str else ""}{f"ACTIVE DRAFT:{chr(10)}{draft_context_str}" if draft_context_str else ""}
CURRENT USER MESSAGE: "{message}"

Classify the user's intent into ONE category:

- OPS: Operational mode - either debugging failures or explaining decisions
  Subtypes:
  - DEBUG: Error signals present (exception, failed, timeout, stack trace, 400/500 errors)
    Phrases: "fix this", "why did this fail", "retry", "error", "broken", "what went wrong"
  - EXPLAIN: Questions about bot's reasoning/decisions
    Phrases: "why did you do that?", "show reasoning", "explain your logic", "how did you decide?"
  Examples:
  - "why did this fail?" -> OPS, ops_subtype=debug
  - "fix this error" -> OPS, ops_subtype=debug
  - "why did you do that?" -> OPS, ops_subtype=explain
  - "show me your reasoning" -> OPS, ops_subtype=explain

- SYNC_REQUEST: User wants to SYNC channel decisions with Jira (bulk update)
  Key phrases: "update Jira issues", "sync Jira", "sync tickets", "update the tickets",
  "sync everything", "synchronize", "push changes to Jira", "update Jira with our decisions"
  Examples:
  - "update Jira issues" -> SYNC_REQUEST
  - "sync Jira" -> SYNC_REQUEST
  - "update the tickets" -> SYNC_REQUEST
  - "sync everything with Jira" -> SYNC_REQUEST
  - "push our decisions to Jira" -> SYNC_REQUEST
  NOTE: This is for BULK sync, not single ticket changes. Single ticket = JIRA_COMMAND

- JIRA_COMMAND: User wants to CHANGE/MODIFY an existing Jira ticket's field values
  Key verbs: change, update, set, modify, edit, delete, remove, close, mark
  Key fields: priority, status, assignee, description, summary, labels
  Target: ticket key (SCRUM-XXX) OR contextual reference ("that ticket", "the auth ticket", "it")
  For contextual references, extract the ticket key from CONVERSATION CONTEXT above.
  Examples:
  - "change the priority of SCRUM-123 to high" -> command_type=update, field=priority, value=high, ticket_key=SCRUM-123
  - "update that ticket's status to Done" -> command_type=update, field=status, value=Done, ticket_key=<from context>
  - "delete SCRUM-456" -> command_type=delete, ticket_key=SCRUM-456
  - "change the assignee to @john" -> command_type=update, field=assignee, value=@john, ticket_key=<from context>
  - "set the status of the auth ticket to In Progress" -> command_type=update, field=status, ticket_key=<from context>
  - "mark SCRUM-789 as done" -> command_type=update, field=status, value=done, ticket_key=SCRUM-789
  - "close that ticket" -> command_type=update, field=status, value=closed, ticket_key=<from context>
  IMPORTANT: For contextual references, look in CONVERSATION CONTEXT and extract the actual ticket key!

- TICKET_ACTION: User wants to CREATE NEW items linked to an existing ticket
  The ticket can be referenced explicitly (SCRUM-123) OR contextually ("the epic", "that ticket").
  For contextual references, extract the ticket key from CONVERSATION CONTEXT above.
  Examples:
  - "create user stories for SCRUM-113" -> action_type=create_stories, ticket_key=SCRUM-113
  - "create subtasks for PROJ-456" -> action_type=create_subtask, ticket_key=PROJ-456
  - "add a comment to SCRUM-123" -> action_type=add_comment, ticket_key=SCRUM-123
  - "update PROJ-789 with the new requirements" -> action_type=update, ticket_key=PROJ-789
  - "break down SCRUM-100 into stories" -> action_type=create_stories, ticket_key=SCRUM-100
  - "create stories under the epic" -> action_type=create_stories, ticket_key=<from context>
  - "now create user stories for that" -> action_type=create_stories, ticket_key=<from context>
  IMPORTANT: If user says "the epic", "that ticket", "it" - look in conversation context for the ticket key!

- WORKITEM_CREATE: User wants to create a NEW work item (no existing ticket referenced)
  (Previously called TICKET - still accepted as alias)
  Examples: "create a ticket for X", "file a bug", "make a Jira story"

- DRAFT_REFINE: User is ASKING about the ACTIVE DRAFT structure (not commanding)
  REQUIRES: Active draft must exist in context
  Key signals - INTERROGATIVE form (questions):
  - Questions about draft structure: "is one epic enough?", "should we split this?"
  - Scope clarifications: "do you think this covers everything?"
  - Meta-questions: "what do you think about the structure?"
  Examples:
  - "Do you think only one epic is enough?" -> DRAFT_REFINE (when draft exists)
  - "Should we split this into multiple epics?" -> DRAFT_REFINE
  - "Is this scope appropriate?" -> DRAFT_REFINE
  IMPORTANT: Only use DRAFT_REFINE if ACTIVE DRAFT CONTEXT is present above.
  If no active draft, use REVIEW instead.
  If user is COMMANDING (not asking), use DRAFT_TRANSFORM instead!

- DRAFT_TRANSFORM: User is COMMANDING a structural change to the draft (not asking about it)
  REQUIRES: Active draft must exist in context
  IMPORTANT: This is for IMPERATIVE commands, not questions!

  Key signal patterns (imperative/commanding):
  - "Split into..." / "Split this into..."
  - "Make this a plan" / "Turn this into..."
  - "Add stories" / "Add epics"
  - "Merge these" / "Combine..."
  - "Only epics" / "Just epics" (scope change)
  - "Break this down into..."
  - "Decompose into stories"
  - "Group them" / "Group these"
  - "Remove the..." / "Delete..."

  Transform operations:
  - split_to_plan: "Split into epics", "Make this a plan with multiple items"
  - add_items: "Add stories", "Add an epic for authentication"
  - merge_items: "Merge the first two epics", "Combine these"
  - elevate_to_epic: "Make this an epic", "Promote to epic"
  - decompose_to_stories: "Break down the epic", "Add stories under this"
  - change_scope: "Only epics", "Full plan", "Just one ticket"
  - remove_items: "Remove the third epic", "Delete the auth story"

  Examples:
  - "Split this into multiple epics" -> DRAFT_TRANSFORM, transform_operation=split_to_plan
  - "Add a story for login" -> DRAFT_TRANSFORM, transform_operation=add_items
  - "Only epics, no stories" -> DRAFT_TRANSFORM, transform_operation=change_scope
  - "Break this epic into stories" -> DRAFT_TRANSFORM, transform_operation=decompose_to_stories

  IMPORTANT: If user is ASKING ("Should we split?", "Is this enough?"), use DRAFT_REFINE instead!

- JIRA_SEARCH: User wants to SEARCH Jira for existing issues
  Key phrases: "check Jira", "search Jira", "look in Jira", "find in Jira", "do we have a ticket",
  "already have", "similar issue", "existing ticket", "look up", "search for tickets"
  Examples:
  - "check out Jira if we already have similar issue" -> JIRA_SEARCH, search_query=<topic from context>
  - "search Jira for authentication issues" -> JIRA_SEARCH, search_query="authentication"
  - "do we have a ticket for this?" -> JIRA_SEARCH, search_query=<topic from context>
  - "look in Jira for API gateway" -> JIRA_SEARCH, search_query="API gateway"
  - "find existing tickets about logging" -> JIRA_SEARCH, search_query="logging"
  Extract the search query from the user's message or conversation context.

- CHANGE_REQUEST: User wants to MODIFY existing truth (not create new)
  Key distinction: Starts with "we already have X, but now need to change"
  Triggers (high confidence):
  - Verbs: "change", "update", "modify", "rename", "remove", "drop", "replace", "delete"
  - Phrases: "this is wrong", "not like that", "we decided differently"
  - Actions: "split into 3 tickets", "move under another epic", "mark as duplicate"
  Examples:
  - "change the title of that work item" -> CHANGE_REQUEST, change_operation=update
  - "delete SCRUM-123" -> CHANGE_REQUEST, change_targets=[SCRUM-123], change_operation=delete
  - "split this into 3 separate tickets" -> CHANGE_REQUEST, change_operation=split
  - "merge those two tickets" -> CHANGE_REQUEST, change_operation=merge
  - "move this under another epic" -> CHANGE_REQUEST, change_operation=move
  NOT CHANGE_REQUEST:
  - "create a new ticket" -> WORKITEM_CREATE (new, not modification)
  - "update status in Jira" -> JIRA_COMMAND (single field, no diff)

- REVIEW: User wants help, analysis, discussion, or feedback WITHOUT creating a ticket
  Examples: "help me define architecture", "review this design", "what's the best approach",
  "I need help with X", "analyze the risks", "let's discuss Y"
  This is the DEFAULT for most help/discussion requests!

- DISCUSSION: Pure greeting or meta-question with no actionable request
  Examples: "hi", "hello", "thanks"

- META: Questions about the bot itself
  Examples: "what can you do?", "how do you work?"

- DECISION: User is STATING a decision that should be recorded (Phase 30)
  Key signals - DECLARATIVE statements (not questions):
  - "We decided to use PostgreSQL"
  - "The decision is to go with microservices"
  - "Approved: Redis for caching"
  - "Let's go with option A"
  - "The architecture will use GraphQL"
  - "Agreed: no external dependencies"
  - "Confirmed: deploy to AWS"
  Examples:
  - "We decided to use PostgreSQL for the database" -> DECISION, decision_type_hint=arch
  - "The decision is to include auth in MVP scope" -> DECISION, decision_type_hint=scope
  - "Approved: no third-party analytics" -> DECISION, decision_type_hint=constraint
  NOT DECISION:
  - "Should we use PostgreSQL?" -> REVIEW (question, not statement)
  - "What do you think about PostgreSQL?" -> REVIEW (asking for opinion)
  - "Let's discuss the database options" -> REVIEW (discussion, not decision)

- AMBIGUOUS: ONLY use when the message is truly unclear AND could equally be ticket OR review
  This should be RARE. Most requests are clearly REVIEW (discussion/help) or WORKITEM_CREATE (explicit creation).

IMPORTANT RULES:
1. SYNC_REQUEST is for BULK sync ("update Jira issues", "sync tickets") - no specific ticket mentioned
2. JIRA_COMMAND is for MODIFYING existing ticket fields (priority, status, assignee) - SINGLE field only
3. TICKET_ACTION is for CREATING new items (stories, subtasks, comments) linked to a ticket
4. "Change priority of X" or "set status to Y" = JIRA_COMMAND
5. "Create stories for X" or "add comment to X" = TICKET_ACTION
6. OPS intent triggers:
   - If error patterns detected (exception, failed, 400, timeout) -> OPS with ops_subtype=debug
   - If asking "why did you" / "explain" / "show reasoning" -> OPS with ops_subtype=explain
7. WORKITEM_CREATE (formerly TICKET) requires EXPLICIT new creation language
8. If user mentions a ticket key AND wants to CREATE items under it = TICKET_ACTION
9. If user wants to MODIFY/CHANGE field values = JIRA_COMMAND
10. "Help me with X" or "I need help with X" = REVIEW (not AMBIGUOUS)
11. "Define architecture" or "design system" = REVIEW (architecture discussion)
12. Only use AMBIGUOUS if user literally could mean either "create ticket" or "discuss"
13. When in doubt between REVIEW and AMBIGUOUS, choose REVIEW
14. "Update Jira" or "sync Jira" without a specific ticket = SYNC_REQUEST
15. JIRA_SEARCH is for searching Jira ("check Jira", "do we have", "similar issue", "existing ticket")
16. "Check Jira if we have X" or "search for similar" = JIRA_SEARCH (not REVIEW)
17. CHANGE_REQUEST is for STRUCTURAL changes (split, merge, delete, move, rename) - NOT single field updates
18. "Delete this ticket" or "split into multiple" = CHANGE_REQUEST (structural change)
19. "Update title" or "change the description" with diff preview = CHANGE_REQUEST
20. Simple "change priority" = JIRA_COMMAND, but "rename the work item" = CHANGE_REQUEST

Respond in this exact format:
INTENT: <OPS|SYNC_REQUEST|JIRA_COMMAND|JIRA_SEARCH|TICKET_ACTION|WORKITEM_CREATE|DRAFT_REFINE|DRAFT_TRANSFORM|TICKET|CHANGE_REQUEST|DECISION|REVIEW|DISCUSSION|META|AMBIGUOUS>
CONFIDENCE: <0.0-1.0>
PERSONA: <pm|architect|security|none>
TICKET_KEY: <extracted ticket key like SCRUM-123, or "none" if not applicable>
ACTION_TYPE: <create_stories|create_subtask|update|add_comment|link|none>
COMMAND_TYPE: <update|delete|none>
COMMAND_FIELD: <priority|status|assignee|description|summary|labels|none>
COMMAND_VALUE: <the value to set, or "none">
TARGET_TYPE: <explicit|contextual|none>
SEARCH_QUERY: <what to search for in Jira, or "none">
CHANGE_TARGETS: <comma-separated list of affected keys/ids, or "none">
CHANGE_OPERATION: <update|delete|split|merge|move|link|none>
OPS_SUBTYPE: <debug|explain|none>
CONTEXT_RELATION: <continue|refine|change|new_topic|none>
TRANSFORM_OPERATION: <split_to_plan|add_items|merge_items|elevate_to_epic|decompose_to_stories|change_scope|remove_items|none>
DECISION_TYPE_HINT: <arch|scope|constraint|priority|structure|process|none>
DECISION_TITLE_HINT: <extracted decision title, or "none">
REASON: <brief explanation>"""

    try:
        result = await llm.chat(prompt)

        # Parse the response
        lines = result.strip().split("\n")
        intent_str = "REVIEW"  # Default to REVIEW, not AMBIGUOUS
        confidence = 0.8
        reason = "llm classification"
        persona_hint = None
        ticket_key = None
        action_type = None
        command_type = None
        command_field = None
        command_value = None
        target_type = None
        search_query = None
        ops_subtype = None
        context_relation = None
        transform_operation = None
        decision_type_hint = None
        decision_title_hint = None

        for line in lines:
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                intent_value = line.split(":", 1)[1].strip().upper()
                valid_intents = [
                    "OPS", "TICKET", "WORKITEM_CREATE", "DRAFT_REFINE", "DRAFT_TRANSFORM",
                    "TICKET_ACTION", "JIRA_COMMAND", "JIRA_SEARCH", "SYNC_REQUEST",
                    "CHANGE_REQUEST", "DECISION", "REVIEW", "DISCUSSION", "META", "AMBIGUOUS"
                ]
                if intent_value in valid_intents:
                    intent_str = intent_value
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    conf_value = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, conf_value))
                except ValueError:
                    pass
            elif line.upper().startswith("PERSONA:"):
                persona_value = line.split(":", 1)[1].strip().lower()
                if persona_value in ["pm", "architect", "security"]:
                    persona_hint = persona_value
            elif line.upper().startswith("TICKET_KEY:"):
                key_value = line.split(":", 1)[1].strip().upper()
                if key_value and key_value != "NONE":
                    ticket_key = key_value
            elif line.upper().startswith("ACTION_TYPE:"):
                type_value = line.split(":", 1)[1].strip().lower()
                valid_actions = ["create_stories", "create_subtask", "update", "add_comment", "link"]
                if type_value in valid_actions:
                    action_type = type_value
            elif line.upper().startswith("COMMAND_TYPE:"):
                type_value = line.split(":", 1)[1].strip().lower()
                if type_value in ["update", "delete"]:
                    command_type = type_value
            elif line.upper().startswith("COMMAND_FIELD:"):
                field_value = line.split(":", 1)[1].strip().lower()
                if field_value and field_value != "none":
                    command_field = field_value
            elif line.upper().startswith("COMMAND_VALUE:"):
                value = line.split(":", 1)[1].strip()
                if value and value.lower() != "none":
                    command_value = value
            elif line.upper().startswith("TARGET_TYPE:"):
                type_value = line.split(":", 1)[1].strip().lower()
                if type_value in ["explicit", "contextual"]:
                    target_type = type_value
            elif line.upper().startswith("SEARCH_QUERY:"):
                query_value = line.split(":", 1)[1].strip()
                if query_value and query_value.lower() != "none":
                    search_query = query_value
            elif line.upper().startswith("OPS_SUBTYPE:"):
                subtype_str = line.split(":", 1)[1].strip().lower()
                if subtype_str == "debug":
                    ops_subtype = OpsSubtype.DEBUG
                elif subtype_str == "explain":
                    ops_subtype = OpsSubtype.EXPLAIN
            elif line.upper().startswith("CONTEXT_RELATION:"):
                relation = line.split(":", 1)[1].strip().lower()
                if relation in ["continue", "refine", "change", "new_topic"]:
                    context_relation = relation
            elif line.upper().startswith("TRANSFORM_OPERATION:"):
                op_value = line.split(":", 1)[1].strip().lower()
                valid_transform_ops = [
                    "split_to_plan", "add_items", "merge_items", "elevate_to_epic",
                    "decompose_to_stories", "change_scope", "remove_items"
                ]
                if op_value in valid_transform_ops:
                    transform_operation = op_value
            elif line.upper().startswith("DECISION_TYPE_HINT:"):
                type_value = line.split(":", 1)[1].strip().lower()
                valid_types = ["arch", "scope", "constraint", "priority", "structure", "process"]
                if type_value in valid_types:
                    decision_type_hint = type_value
            elif line.upper().startswith("DECISION_TITLE_HINT:"):
                title_value = line.split(":", 1)[1].strip()
                if title_value and title_value.lower() != "none":
                    decision_title_hint = title_value
            elif line.upper().startswith("REASON:"):
                reason = f"llm: {line.split(':', 1)[1].strip()}"

        # Normalize deprecated intents
        if intent_str == "TICKET":
            intent_str = "WORKITEM_CREATE"

        return IntentResult(
            intent=Intent(intent_str.lower()),
            confidence=confidence,
            persona_hint=persona_hint,
            ticket_key=ticket_key,
            action_type=action_type,
            command_type=command_type,
            command_field=command_field,
            command_value=command_value,
            target_type=target_type,
            search_query=search_query,
            ops_subtype=ops_subtype,
            context_relation=context_relation,
            transform_operation=transform_operation,
            decision_type_hint=decision_type_hint,
            decision_title_hint=decision_title_hint,
            reasons=[reason],
        )

    except Exception as e:
        logger.warning(f"LLM intent classification failed: {e}, defaulting to REVIEW")
        return IntentResult(
            intent=Intent.REVIEW,
            confidence=0.5,
            reasons=["llm classification failed, default to REVIEW"],
        )


async def classify_intent(
    message: str,
    conversation_context: dict | None = None,
    active_draft: dict | None = None,  # Phase 26
) -> IntentResult:
    """Classify user message intent using pattern matching + LLM.

    Pattern matching is used first for DECISION intent detection.
    LLM classification is used as fallback for all intents.

    Args:
        message: User's message text
        conversation_context: Full conversation history for context
        active_draft: Active draft summary for context-aware classification (Phase 26)

    Returns:
        IntentResult with intent type, confidence, and reasons
    """
    # Phase 30: Pattern-first detection for DECISION intent
    is_decision, title_hint, pattern_name = _match_decision_patterns(message)

    if is_decision:
        # Detect decision type from keywords
        type_hint = _detect_decision_type_hint(message)

        logger.info(
            f"Decision detected by pattern matching: pattern={pattern_name}, "
            f"type_hint={type_hint}, title_hint={title_hint[:50] if title_hint else None}"
        )

        return IntentResult(
            intent=Intent.DECISION,
            confidence=0.9,  # High confidence for pattern match
            decision_type_hint=type_hint,
            decision_title_hint=title_hint,
            reasons=[f"pattern match: {pattern_name}"],
        )

    # LLM classification for all other intents
    result = await _llm_classify(message, conversation_context, active_draft)
    logger.info(
        f"Intent classified by LLM: {result.intent.value}, "
        f"confidence={result.confidence}, persona={result.persona_hint}, reasons={result.reasons}"
    )
    return result


async def intent_router_node(state: dict) -> dict:
    """LangGraph node for intent routing.

    Gets the latest human message and classifies intent using LLM with full context.
    Returns partial state update with intent_result.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with intent_result
    """
    from langchain_core.messages import HumanMessage

    # Check if intent is already forced (e.g., from scope_gate selection or continuation detection)
    existing_intent = state.get("intent_result")
    if existing_intent:
        reasons = existing_intent.get("reasons", [])
        forced_patterns = ["scope_gate", "event_router", "continuation"]
        if any(pattern in r for r in reasons for pattern in forced_patterns):
            logger.info(f"Skipping intent classification - already forced: {existing_intent.get('intent')}, reasons={reasons}")
            return {"intent_result": existing_intent}

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = None

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for intent classification")
        result = IntentResult(
            intent=Intent.REVIEW,
            confidence=0.5,
            reasons=["no message found, default to REVIEW"],
        )
    else:
        # Get conversation context for LLM
        conversation_context = state.get("conversation_context")

        # Build active draft summary for context-aware classification (Phase 26)
        active_draft = None
        draft = state.get("draft")
        if draft and hasattr(draft, 'title') and draft.title:
            active_draft = {
                "title": draft.title,
                "issue_type": draft.issue_type.value if hasattr(draft, 'issue_type') and draft.issue_type else None,
                "requested_scope": draft.requested_scope.value if hasattr(draft, 'requested_scope') and draft.requested_scope else None,
            }

        result = await classify_intent(latest_human_message, conversation_context, active_draft)

    logger.info(
        f"IntentRouter: intent={result.intent.value}, "
        f"confidence={result.confidence}, reasons={result.reasons}"
    )

    return {"intent_result": result.model_dump()}

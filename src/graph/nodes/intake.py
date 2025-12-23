"""Intake and discovery nodes for gathering requirements."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import (
    parse_llm_json_response,
    get_llm_for_state,
    get_persona_knowledge,
    logger,
    settings,
)

# =============================================================================
# Intent Classification Node
# =============================================================================

INTENT_CLASSIFICATION_PROMPT = """You are an intent classifier for a requirements engineering bot.

Analyze the user message and classify it into one of these categories:
- requirement: User is describing a new feature, story, bug, or requirement
- question: User is asking about existing requirements or the system
- jira_sync: User wants to sync requirements to Jira
- jira_read: User wants to re-read or refresh a Jira issue (e.g., "re-read JIRA-123")
- general: General conversation related to the project
- off_topic: Not related to requirements or the project

Also determine which persona (if any) should handle this:
- architect: Technical architecture, system design, components
- product_manager: User stories, acceptance criteria, business value
- security_analyst: Security requirements, compliance, vulnerabilities
- none: Main bot handles (general requirements work)

Respond in JSON format:
{{
    "intent": "<intent_type>",
    "confidence": <0.0-1.0>,
    "personas": [
        {{"name": "<persona_name>", "confidence": <0.0-1.0>}}
    ],
    "reasoning": "<brief explanation>"
}}

User message: {message}

Context from memory:
{context}
"""


async def intent_classifier_node(state: RequirementState) -> dict:
    """
    Classify user intent and determine which persona should handle.

    Uses LLM to analyze message and return intent type with confidence.
    """
    logger.info(
        "classifying_intent",
        channel_id=state.get("channel_id"),
        message_length=len(state.get("message", "")),
    )

    llm = get_llm_for_state(state, temperature=0.1)  # Low temperature for classification

    # Build context from Zep facts
    context = ""
    if state.get("zep_facts"):
        context = "\n".join(
            f"- {fact.get('content', '')}" for fact in state["zep_facts"][:10]
        )
    else:
        context = "No previous context available."

    prompt = ChatPromptTemplate.from_template(INTENT_CLASSIFICATION_PROMPT)
    messages = prompt.format_messages(
        message=state.get("message", ""),
        context=context,
    )

    try:
        import asyncio
        print(f"[DEBUG] Calling LLM for intent classification with model...")
        try:
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=60.0)
        except asyncio.TimeoutError:
            print(f"[DEBUG] LLM call timed out after 60s")
            raise Exception("LLM call timed out")
        print(f"[DEBUG] LLM response received, parsing...")
        result = parse_llm_json_response(response)
        print(f"[DEBUG] Intent parsed: {result.get('intent')}")

        intent = result.get("intent", "general")
        confidence = result.get("confidence", 0.5)
        personas = result.get("personas", [])

        # Determine if we should respond based on confidence
        should_respond = state.get("is_mention", False) or confidence >= settings.confidence_threshold_main

        # Check for persona activation (95% threshold)
        active_persona = None
        for persona in personas:
            if persona.get("confidence", 0) >= settings.confidence_threshold_persona:
                active_persona = persona.get("name")
                break

        logger.info(
            "intent_classified",
            intent=intent,
            confidence=confidence,
            should_respond=should_respond,
            active_persona=active_persona,
        )

        return {
            "intent": intent,
            "intent_confidence": confidence,
            "persona_matches": personas,
            "active_persona": active_persona,
            "should_respond": should_respond,
        }

    except Exception as e:
        logger.error("intent_classification_failed", error=str(e))
        return {
            "intent": IntentType.GENERAL.value,
            "intent_confidence": 0.5,
            "persona_matches": [],
            "active_persona": None,
            "should_respond": state.get("is_mention", False),
            "error": f"Intent classification failed: {str(e)}",
        }


# =============================================================================
# Intake Node (Enhanced intent + entity extraction + context scoring)
# =============================================================================

INTAKE_PROMPT = """You are an intelligent intake system for a requirements engineering assistant.

Analyze the user's message and extract:
1. Intent classification
2. Key entities mentioned
3. Whether there's enough context to proceed
4. Any Jira issue keys referenced (format: PROJECT-123)

## Intent Types
- proceed: User wants to skip questions and proceed to the next phase (e.g., "create architecture", "proceed", "continue", "go ahead", "just do it", "enough questions", "let's move on", "skip", "start building")
- requirement: New feature, story, bug, or requirement description (when no existing epics/stories)
- modification: Change to EXISTING requirements (when epics/stories already exist and user wants to change architecture, scope, stories, etc.)
- question: Question about requirements, architecture, or the project
- jira_sync: Request to sync/create issues in Jira
- jira_read: Request to re-read/refresh/fetch a specific Jira issue (e.g., "re-read PROJ-123", "refresh that issue")
- jira_status: Request to show status of current thread items (e.g., "status", "show me the status")
- jira_add: Request to add a new story/task to an existing epic (e.g., "add a story to EPIC-123")
- jira_update: Request to update/modify a specific Jira issue field (e.g., "update PROJ-123 description")
- jira_delete: Request to delete a Jira issue (e.g., "delete PROJ-123", "remove that issue")
- general: Project-related conversation
- off_topic: Unrelated to requirements/project

IMPORTANT: When user says things like "create architecture", "design the system", "proceed", "continue", "go ahead", "enough questions" - classify as "proceed", NOT as "requirement". The user wants to skip discovery and move to the next phase.

NOTE: Use "modification" when the user wants to change the architecture, add/remove epics, change scope,
reprioritize stories, etc. - changes that might cascade through the requirements. Use "jira_update" for
simple field changes to a specific issue.

## Entity Types to Extract
- systems: Technical systems, services, tools mentioned (e.g., "GitHub", "Auth service")
- users: User roles or types (e.g., "admin", "customer", "manager")
- features: Specific features or capabilities described
- integrations: External systems to integrate with
- constraints: Non-functional requirements (performance, security, compliance)

## Jira Command Details (for jira_read, jira_add, jira_update intents)
- jira_target: The specific Jira issue key being referenced (e.g., "PROJ-123")
- jira_parent: For jira_add, the parent issue to add to (e.g., "EPIC-456")
- jira_item_type: For jira_add, what type to create ("story", "task", "bug")

## Context Sufficiency
Evaluate if we have enough information to create a well-formed requirement:
- high: Clear goal, user role, and expected outcome specified
- medium: Some details clear, but clarifying questions would help
- low: Vague or incomplete - need discovery phase
- n/a: Not a requirement (question/general/off_topic/jira command)

## Persona Matching
- architect: Technical architecture, system design, components, scalability
- product_manager: User stories, acceptance criteria, business value, prioritization
- security_analyst: Security requirements, compliance, vulnerabilities, authentication
- none: Main bot handles (general requirements work)

## Topic Change Detection (IMPORTANT for thread management)
Analyze if the new message is:
- SAME TOPIC: Continuation of the current thread's discussion (answer to a question, follow-up, clarification)
- NEW TOPIC: A completely different subject/project/question unrelated to the current thread

Examples of topic change:
- Thread about "payment system" → User asks about "user authentication" = NEW TOPIC
- Thread about "Epic-123" → User asks about "Epic-456" = NEW TOPIC
- Thread about "architecture" → User provides more architecture details = SAME TOPIC
- Thread about "requirements" → User answers clarifying question = SAME TOPIC

User message: {message}

Previous context from memory:
{context}

Respond in JSON format:
{{
    "intent": "<intent_type>",
    "confidence": <0.0-1.0>,
    "entities": {{
        "systems": ["<system1>", ...],
        "users": ["<role1>", ...],
        "features": ["<feature1>", ...],
        "integrations": ["<integration1>", ...],
        "constraints": ["<constraint1>", ...]
    }},
    "jira_command": {{
        "target": "<PROJ-123 or null>",
        "parent": "<EPIC-456 or null>",
        "item_type": "<story|task|bug or null>"
    }},
    "context_sufficiency": "<high|medium|low|n/a>",
    "missing_info": ["<what's missing 1>", ...],
    "is_topic_change": <true|false>,
    "topic_change_reason": "<why this is a new topic, or null if same topic>",
    "personas": [
        {{"name": "<persona_name>", "confidence": <0.0-1.0>, "reason": "<why>"}}
    ],
    "suggested_questions": ["<clarifying question 1>", ...],
    "summary": "<1-sentence summary of what user wants>"
}}
"""


async def intake_node(state: RequirementState) -> dict:
    """
    Enhanced intake node with entity extraction and context sufficiency scoring.

    Combines:
    - Intent classification (including Jira commands via LLM)
    - Entity extraction (systems, users, features, etc.)
    - Context sufficiency scoring
    - Clarifying question generation
    - Persona matching

    This is Phase 1 of the new multi-phase workflow.
    """
    message = state.get("message", "")
    current_phase = state.get("current_phase")

    logger.info(
        "intake_processing",
        channel_id=state.get("channel_id"),
        message_length=len(message),
        current_phase=current_phase,
    )

    # If we're already past discovery phase, treat user's response as "proceed"
    # unless it's clearly a new requirement or command
    phases_past_discovery = [
        WorkflowPhase.ARCHITECTURE.value,
        WorkflowPhase.SCOPE.value,
        WorkflowPhase.STORIES.value,
        WorkflowPhase.TASKS.value,
        WorkflowPhase.ESTIMATION.value,
        WorkflowPhase.SECURITY.value,
        WorkflowPhase.VALIDATION.value,
        WorkflowPhase.REVIEW.value,
    ]

    # Quick check for proceed/continue commands
    proceed_keywords = ["proceed", "continue", "go ahead", "yes", "ok", "okay", "sure", "do it", "create", "build", "start"]
    message_lower = message.lower().strip()

    # Check for option selection patterns (e.g., "A", "Option A", "Option 1", "B", "1", "2")
    import re
    option_pattern = re.compile(r'^(option\s*)?([abc123])\s*$', re.IGNORECASE)
    is_option_selection = bool(option_pattern.match(message_lower))

    print(f"[DEBUG] intake_node: current_phase={current_phase}, message={message_lower[:50]}, is_option={is_option_selection}")

    if current_phase in phases_past_discovery:
        # If user is responding in a phase past discovery, default to proceeding
        # unless they explicitly ask questions or provide new requirements
        is_short_response = len(message.split()) <= 10
        has_proceed_keyword = any(kw in message_lower for kw in proceed_keywords)

        if is_short_response or has_proceed_keyword or is_option_selection:
            logger.info("intake_phase_continue", phase=current_phase, action="proceed", is_option=is_option_selection)
            return {
                "intent": "proceed",
                "intent_confidence": 0.9,
                "should_respond": True,
                "current_phase": current_phase,
                "clarifying_questions": [],  # Don't ask more questions
                # Store the selected option for architecture node
                "selected_option": message.strip() if is_option_selection else None,
            }

    # Also check for option selection even if phase is not set (state may not be loaded yet)
    if is_option_selection:
        logger.info("intake_option_selection", option=message.strip())
        return {
            "intent": "proceed",
            "intent_confidence": 0.9,
            "should_respond": True,
            "clarifying_questions": [],
            "selected_option": message.strip(),
        }

    llm = get_llm_for_state(state, temperature=0.1)

    # Build context from Zep facts
    context = ""
    if state.get("zep_facts"):
        context = "\n".join(
            f"- {fact.get('content', '')}" for fact in state["zep_facts"][:10]
        )
    else:
        context = "No previous context available."

    # Add current phase info to context
    if current_phase:
        context += f"\n\nCurrent workflow phase: {current_phase}"

    prompt = ChatPromptTemplate.from_template(INTAKE_PROMPT)
    messages = prompt.format_messages(
        message=state.get("message", ""),
        context=context,
    )

    try:
        import asyncio
        print(f"[DEBUG] Calling LLM for intake analysis...")
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=60.0)
        print(f"[DEBUG] Intake LLM response received, parsing...")
        result = parse_llm_json_response(response)
        print(f"[DEBUG] Intake parsed: intent={result.get('intent')}, sufficiency={result.get('context_sufficiency')}")

        intent = result.get("intent", "general")
        confidence = result.get("confidence", 0.5)
        personas = result.get("personas", [])
        entities = result.get("entities", {})
        context_sufficiency = result.get("context_sufficiency", "n/a")
        missing_info = result.get("missing_info", [])
        suggested_questions = result.get("suggested_questions", [])
        summary = result.get("summary", "")

        # Topic change detection
        is_topic_change = result.get("is_topic_change", False)
        topic_change_reason = result.get("topic_change_reason")

        # Parse Jira command details
        jira_command = result.get("jira_command", {})
        jira_target = jira_command.get("target") if jira_command else None
        jira_parent = jira_command.get("parent") if jira_command else None
        jira_item_type = jira_command.get("item_type") if jira_command else None

        # Determine if we should respond
        should_respond = state.get("is_mention", False) or confidence >= settings.confidence_threshold_main

        # Determine response target based on topic change
        # If topic changed, respond in channel (new thread), otherwise in current thread
        if is_topic_change:
            response_target = "channel"
            logger.info("topic_change_detected", reason=topic_change_reason)
        else:
            response_target = "thread"

        # Check for persona activation
        active_persona = None
        for persona in personas:
            if persona.get("confidence", 0) >= settings.confidence_threshold_persona:
                active_persona = persona.get("name")
                break

        logger.info(
            "intake_complete",
            intent=intent,
            confidence=confidence,
            context_sufficiency=context_sufficiency,
            entity_count=sum(len(v) for v in entities.values()),
            active_persona=active_persona,
            jira_target=jira_target,
        )

        # Build discovered_requirements from entities
        discovered_requirements = []
        for feature in entities.get("features", []):
            discovered_requirements.append({
                "type": "feature",
                "description": feature,
                "source": "user_message",
            })
        for constraint in entities.get("constraints", []):
            discovered_requirements.append({
                "type": "constraint",
                "description": constraint,
                "source": "user_message",
            })

        return {
            # Intent classification
            "intent": intent,
            "intent_confidence": confidence,
            "persona_matches": personas,
            "active_persona": active_persona,
            "should_respond": should_respond,
            "response_target": response_target,  # thread, channel, or broadcast
            # Phase tracking
            "current_phase": WorkflowPhase.INTAKE.value,
            "phase_history": [WorkflowPhase.INTAKE.value],
            # Discovery info
            "clarifying_questions": suggested_questions if context_sufficiency in ("low", "medium") else [],
            "discovered_requirements": discovered_requirements,
            # Goal from summary
            "current_goal": summary if intent == "requirement" else state.get("current_goal"),
            # Jira command details (for jira_read, jira_add, jira_update, jira_status)
            "jira_command_target": jira_target,
            "jira_command_parent": jira_parent,
            "jira_command_type": jira_item_type,
        }

    except Exception as e:
        logger.error("intake_failed", error=str(e))
        return {
            "intent": IntentType.GENERAL.value,
            "intent_confidence": 0.5,
            "persona_matches": [],
            "active_persona": None,
            "should_respond": state.get("is_mention", False),
            "current_phase": WorkflowPhase.INTAKE.value,
            "error": f"Intake processing failed: {str(e)}",
        }


# =============================================================================
# Discovery Node (Clarifying Questions)
# =============================================================================

DISCOVERY_PROMPT = """You are a requirements discovery expert helping gather complete information.

## Current State
User's initial request: {user_message}
Goal identified: {goal}
Discovered so far: {discovered}
Questions already asked: {asked_questions}
User's answers: {user_answers}

## Your Task
Based on the current state:
1. Analyze if we have enough information to create high-quality requirements
2. If not, generate 2-4 focused clarifying questions WITH suggested answers
3. If we have enough, summarize the complete requirements
4. ALWAYS explain your reasoning for what information is missing

## Question Guidelines
- Focus on ONE aspect per question
- Be specific, not vague
- Prioritize: user roles, use cases, constraints, integrations
- ALWAYS provide 2-4 suggested answers for each question
- Include a "Skip / Use defaults" option if reasonable defaults exist

## Response Format
Respond in JSON format:
{{
    "enough_info": <true/false>,
    "discovery_phase_complete": <true/false>,
    "missing_info_explanation": "<explain WHY you need more info and what happens if user proceeds without it>",
    "can_proceed_anyway": <true/false - can we make reasonable assumptions?>,
    "questions_with_options": [
        {{
            "question": "<the question>",
            "why_needed": "<brief explanation why this matters>",
            "suggested_answers": ["<option 1>", "<option 2>", "<option 3>"],
            "default_if_skipped": "<what we'll assume if user skips>"
        }}
    ],
    "updated_requirements": [
        {{
            "type": "<feature|constraint|integration|user_story>",
            "description": "<requirement text>",
            "source": "<user_answer|inferred>"
        }}
    ],
    "summary": "<current understanding in 2-3 sentences>",
    "next_action": "<ask_questions|proceed_to_architecture|proceed_to_scope>"
}}
"""


async def discovery_node(state: RequirementState) -> dict:
    """
    Discovery phase - gather clarifying information from user.

    This node:
    1. Checks if we have enough context
    2. Generates clarifying questions if needed
    3. Processes user answers to build requirements
    4. Decides when discovery is complete

    This is Phase 2 of the multi-phase workflow.
    """
    logger.info(
        "discovery_processing",
        channel_id=state.get("channel_id"),
        questions_count=len(state.get("clarifying_questions", [])),
        answers_count=len(state.get("user_answers", [])),
    )

    # Check if discovery was triggered but no questions to ask
    # (high context sufficiency from intake)
    if not state.get("clarifying_questions") and not state.get("user_answers"):
        logger.info("discovery_skipped", reason="high_context_sufficiency")
        return {
            "current_phase": WorkflowPhase.DISCOVERY.value,
        }

    llm = get_llm_for_state(state, temperature=0.3)

    # Build context for discovery prompt
    discovered = state.get("discovered_requirements", [])
    discovered_str = "\n".join(
        f"- [{d.get('type')}] {d.get('description')}"
        for d in discovered
    ) if discovered else "None yet"

    asked = state.get("clarifying_questions", [])
    asked_str = "\n".join(f"- {q}" for q in asked) if asked else "None"

    answers = state.get("user_answers", [])
    answers_str = "\n".join(
        f"Q: {a.get('question')}\nA: {a.get('answer')}"
        for a in answers
    ) if answers else "None"

    prompt = ChatPromptTemplate.from_template(DISCOVERY_PROMPT)
    messages = prompt.format_messages(
        user_message=state.get("message", ""),
        goal=state.get("current_goal") or "Not yet established",
        discovered=discovered_str,
        asked_questions=asked_str,
        user_answers=answers_str,
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        enough_info = result.get("enough_info", False)
        questions_with_options = result.get("questions_with_options", [])
        # Fallback for old format
        new_questions = result.get("new_questions", [])
        updated_requirements = result.get("updated_requirements", [])
        summary = result.get("summary", "")
        next_action = result.get("next_action", "ask_questions")
        missing_explanation = result.get("missing_info_explanation", "")
        can_proceed = result.get("can_proceed_anyway", True)

        logger.info(
            "discovery_complete",
            enough_info=enough_info,
            questions_count=len(questions_with_options) or len(new_questions),
            next_action=next_action,
            can_proceed_anyway=can_proceed,
        )

        # Merge new requirements with existing
        all_requirements = list(discovered) + updated_requirements

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.DISCOVERY.value not in phase_history:
            phase_history.append(WorkflowPhase.DISCOVERY.value)

        # Build response with status, questions, and options
        response_text = None
        if not enough_info and (questions_with_options or new_questions):
            # Status header
            response_text = f"📍 *Phase: Discovery*\n"
            response_text += f"_{summary}_\n\n"

            # Explanation of what's missing
            if missing_explanation:
                response_text += f"💡 *Why I'm asking:* {missing_explanation}\n\n"

            # Questions with suggested answers
            if questions_with_options:
                for i, q in enumerate(questions_with_options, 1):
                    response_text += f"*{i}. {q.get('question', '')}*\n"
                    if q.get('why_needed'):
                        response_text += f"   _{q['why_needed']}_\n"
                    if q.get('suggested_answers'):
                        response_text += "   Suggested answers:\n"
                        for opt in q['suggested_answers']:
                            response_text += f"   • {opt}\n"
                    if q.get('default_if_skipped'):
                        response_text += f"   _Default if skipped: {q['default_if_skipped']}_\n"
                    response_text += "\n"
            else:
                # Fallback to old format
                for i, q in enumerate(new_questions, 1):
                    response_text += f"{i}. {q}\n"

            # Proceed anyway option
            if can_proceed:
                response_text += "\n---\n"
                response_text += "💨 *Want to skip?* Say `proceed` or `continue` to move to Architecture with defaults.\n"

        # Extract just the question texts for state
        question_texts = [q.get('question', '') for q in questions_with_options] if questions_with_options else new_questions

        return {
            "current_phase": WorkflowPhase.DISCOVERY.value,
            "phase_history": phase_history,
            "clarifying_questions": question_texts,
            "discovered_requirements": all_requirements,
            "current_goal": summary if summary else state.get("current_goal"),
            "response": response_text,
            "should_respond": bool(response_text),
        }

    except Exception as e:
        logger.error("discovery_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.DISCOVERY.value,
            "error": f"Discovery failed: {str(e)}",
        }


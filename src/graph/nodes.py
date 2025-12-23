"""
LangGraph Nodes - All node functions for the requirements workflow.

Each node is a pure function that takes state and returns state updates.
Nodes are composed into the graph in graph.py.
"""

import json
from pathlib import Path
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from src.config.settings import get_settings

# Persona knowledge cache
_persona_knowledge_cache: dict[str, str] = {}
from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
    ProgressStepStatus,
)
# Note: get_model_provider imported lazily inside get_llm() to avoid circular import

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# Helper Functions
# =============================================================================

def parse_llm_json_response(response) -> dict:
    """
    Parse JSON from LLM response, handling various content formats.

    Args:
        response: LLM response object with .content attribute.

    Returns:
        Parsed JSON as dict.

    Raises:
        json.JSONDecodeError: If JSON parsing fails.
    """
    content = response.content

    # Handle list content format (Google Gemini)
    if isinstance(content, list):
        content = "".join(
            part.get("text", str(part)) if isinstance(part, dict) else str(part)
            for part in content
        )

    # Extract JSON from markdown code blocks
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    return json.loads(content.strip())


# =============================================================================
# LLM Factory
# =============================================================================

def get_llm_for_state(state: RequirementState, temperature: float = 0.3) -> BaseChatModel:
    """
    Get the appropriate LLM based on channel configuration.

    Uses channel_config to determine which model and provider to use.
    Falls back to default settings if no config.

    Args:
        state: Current graph state with channel_config.
        temperature: LLM temperature setting.

    Returns:
        Configured LLM instance.
    """
    # Lazy import to avoid circular dependency
    from src.slack.channel_config_store import get_model_provider

    config = state.get("channel_config", {})
    model_name = config.get("default_model", settings.default_llm_model)
    provider = get_model_provider(model_name)

    print(f"[DEBUG] get_llm_for_state: model={model_name}, provider={provider}")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=temperature)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    else:  # Default to OpenAI
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)


def get_personality_prompt(state: RequirementState) -> str:
    """
    Generate personality instructions based on channel config.

    Args:
        state: Current graph state with channel_config.

    Returns:
        Personality instruction string to append to prompts.
    """
    config = state.get("channel_config", {})
    personality = config.get("personality", {})

    if not personality:
        return ""

    humor = personality.get("humor", 0.2)
    formality = personality.get("formality", 0.6)
    emoji = personality.get("emoji_usage", 0.2)
    verbosity = personality.get("verbosity", 0.5)

    instructions = []

    # Humor
    if humor < 0.3:
        instructions.append("Be professional and serious.")
    elif humor > 0.7:
        instructions.append("Feel free to use appropriate humor and wit.")

    # Formality
    if formality < 0.3:
        instructions.append("Use a casual, friendly tone.")
    elif formality > 0.7:
        instructions.append("Use formal, professional language.")

    # Emoji
    if emoji < 0.3:
        instructions.append("Avoid using emojis.")
    elif emoji > 0.7:
        instructions.append("Use emojis where appropriate to be expressive.")

    # Verbosity
    if verbosity < 0.3:
        instructions.append("Be very concise and brief.")
    elif verbosity > 0.7:
        instructions.append("Provide detailed, thorough explanations.")

    if instructions:
        return "\n\nCommunication style: " + " ".join(instructions)
    return ""


def get_persona_knowledge(persona_name: str | None, state: RequirementState) -> str:
    """
    Load ALL files from persona directory and channel config.

    Combines:
    1. All files from personas/{name}/ directory (*.md, *.txt, *.yaml, etc.)
    2. Channel-specific overrides from channel_config.persona_knowledge

    Args:
        persona_name: Name of the persona (architect, product_manager, security_analyst)
        state: Current graph state with channel_config.

    Returns:
        Combined persona knowledge string.
    """
    if not persona_name:
        return ""

    global _persona_knowledge_cache

    # Load ALL files from persona directory if not cached
    if persona_name not in _persona_knowledge_cache:
        persona_dir = Path(__file__).parent.parent.parent / "personas" / persona_name
        knowledge_parts = []

        if persona_dir.exists() and persona_dir.is_dir():
            # Load all text-based files from the directory
            supported_extensions = {".md", ".txt", ".yaml", ".yml", ".json"}
            for file_path in sorted(persona_dir.iterdir()):
                if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                    try:
                        content = file_path.read_text()
                        knowledge_parts.append(f"### {file_path.name}\n{content}")
                    except Exception as e:
                        logger.warning("persona_file_read_failed", file=str(file_path), error=str(e))

        _persona_knowledge_cache[persona_name] = "\n\n".join(knowledge_parts)

    base_knowledge = _persona_knowledge_cache.get(persona_name, "")

    # Get channel-specific overrides
    config = state.get("channel_config", {})
    persona_overrides = config.get("persona_knowledge", {}).get(persona_name, {})
    inline_knowledge = persona_overrides.get("inline", "")

    # Combine knowledge
    parts = []
    if base_knowledge:
        parts.append(f"=== {persona_name.replace('_', ' ').title()} Persona ===\n{base_knowledge}")
    if inline_knowledge:
        parts.append(f"\n=== Channel-Specific Context ===\n{inline_knowledge}")

    return "\n".join(parts)


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

    if current_phase in phases_past_discovery:
        # If user is responding in a phase past discovery, default to proceeding
        # unless they explicitly ask questions or provide new requirements
        is_short_response = len(message.split()) <= 10
        has_proceed_keyword = any(kw in message_lower for kw in proceed_keywords)

        if is_short_response or has_proceed_keyword:
            logger.info("intake_phase_continue", phase=current_phase, action="proceed")
            return {
                "intent": "proceed",
                "intent_confidence": 0.9,
                "should_respond": True,
                "current_phase": current_phase,
                "clarifying_questions": [],  # Don't ask more questions
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

        # Parse Jira command details
        jira_command = result.get("jira_command", {})
        jira_target = jira_command.get("target") if jira_command else None
        jira_parent = jira_command.get("parent") if jira_command else None
        jira_item_type = jira_command.get("item_type") if jira_command else None

        # Determine if we should respond
        should_respond = state.get("is_mention", False) or confidence >= settings.confidence_threshold_main

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


# =============================================================================
# Architecture Exploration Node (Phase 3)
# =============================================================================

ARCHITECTURE_PROMPT = """You are a senior software architect with deep expertise in system design.
{persona_knowledge}

## Project Context
Goal: {goal}
Discovered Requirements:
{requirements}

User's Original Request:
{user_message}

## Your Task
Analyze the requirements and propose 2-3 architecture options. For each option:
1. Give it a clear name
2. Describe the high-level approach
3. List specific technologies/frameworks
4. Identify pros and cons
5. Provide a rough effort estimate

## Guidelines
- Consider the scale and complexity implied by requirements
- Factor in any mentioned constraints (compliance, performance, timeline)
- Recommend ONE option as best fit with clear reasoning
- Be specific about technologies, not vague
- Consider maintainability and team skills

Respond in JSON format:
{{
    "analysis_summary": "<1-2 sentence summary of what we're building>",
    "key_decisions": ["<decision 1>", "<decision 2>", ...],
    "options": [
        {{
            "name": "<option name>",
            "recommended": <true/false>,
            "description": "<2-3 sentence description>",
            "technologies": ["<tech1>", "<tech2>", ...],
            "pros": ["<pro1>", "<pro2>", ...],
            "cons": ["<con1>", "<con2>", ...],
            "effort_estimate": "<e.g., '4-6 weeks for MVP'>",
            "best_for": "<when to choose this option>"
        }}
    ],
    "recommendation_reasoning": "<why the recommended option is best>",
    "questions_for_user": ["<optional clarifying questions about architecture>"]
}}
"""


async def architecture_exploration_node(state: RequirementState) -> dict:
    """
    Explore architecture options based on gathered requirements.

    This node:
    1. Loads Architect persona knowledge
    2. Analyzes requirements and constraints
    3. Generates 2-3 architecture options with trade-offs
    4. Recommends one option with reasoning
    5. Formats for user presentation

    This is Phase 3 of the multi-phase workflow.
    """
    logger.info(
        "architecture_exploration",
        channel_id=state.get("channel_id"),
        requirements_count=len(state.get("discovered_requirements", [])),
    )

    llm = get_llm_for_state(state, temperature=0.4)

    # Always use architect persona for this node
    persona_knowledge = get_persona_knowledge("architect", state)

    # Build requirements summary
    requirements = state.get("discovered_requirements", [])
    req_str = "\n".join(
        f"- [{r.get('type')}] {r.get('description')}"
        for r in requirements
    ) if requirements else "No specific requirements captured yet."

    prompt = ChatPromptTemplate.from_template(ARCHITECTURE_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        requirements=req_str,
        user_message=state.get("message", ""),
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        options = result.get("options", [])
        analysis = result.get("analysis_summary", "")
        reasoning = result.get("recommendation_reasoning", "")
        questions = result.get("questions_for_user", [])

        logger.info(
            "architecture_options_generated",
            options_count=len(options),
            has_recommendation=any(o.get("recommended") for o in options),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.ARCHITECTURE.value not in phase_history:
            phase_history.append(WorkflowPhase.ARCHITECTURE.value)

        # Format response for Slack
        response_text = _format_architecture_options(options, analysis, reasoning)

        # Add questions if any
        if questions:
            response_text += "\n\n*Questions to consider:*\n"
            for q in questions:
                response_text += f"• {q}\n"

        response_text += "\n\nWhich approach would you like to proceed with? Reply with A, B, C or ask questions."

        return {
            "current_phase": WorkflowPhase.ARCHITECTURE.value,
            "phase_history": phase_history,
            "architecture_options": options,
            "response": response_text,
            "should_respond": True,
            "active_persona": "architect",
        }

    except Exception as e:
        logger.error("architecture_exploration_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.ARCHITECTURE.value,
            "error": f"Architecture exploration failed: {str(e)}",
        }


def _format_architecture_options(
    options: list[dict],
    analysis: str,
    reasoning: str,
) -> str:
    """Format architecture options for Slack display."""
    lines = ["*Architecture Options*\n"]

    if analysis:
        lines.append(f"_{analysis}_\n")

    option_letters = ["A", "B", "C", "D"]

    for i, opt in enumerate(options):
        letter = option_letters[i] if i < len(option_letters) else str(i + 1)
        recommended = " ⭐ Recommended" if opt.get("recommended") else ""

        lines.append(f"\n*Option {letter}: {opt.get('name', 'Unnamed')}{recommended}*")
        lines.append(f"├─ {opt.get('description', '')}")

        # Technologies
        techs = opt.get("technologies", [])
        if techs:
            lines.append(f"├─ Technologies: {', '.join(techs)}")

        # Pros
        pros = opt.get("pros", [])
        for pro in pros[:3]:  # Limit to 3
            lines.append(f"├─ ✅ {pro}")

        # Cons
        cons = opt.get("cons", [])
        for con in cons[:2]:  # Limit to 2
            lines.append(f"├─ ⚠️ {con}")

        # Estimate
        estimate = opt.get("effort_estimate")
        if estimate:
            lines.append(f"└─ Estimate: {estimate}")

    if reasoning:
        lines.append(f"\n*Recommendation:* {reasoning}")

    return "\n".join(lines)


# =============================================================================
# Scope Definition Node (Phase 4)
# =============================================================================

SCOPE_PROMPT = """You are a product strategist defining project scope.
{persona_knowledge}

## Context
Goal: {goal}
Chosen Architecture: {architecture}
Discovered Requirements:
{requirements}

## Your Task
Define the project scope clearly:
1. Create Epic(s) - high-level initiative containers
2. Define what's IN scope for MVP
3. Define what's OUT of scope (future phases)
4. Set clear boundaries

## Guidelines
- Be specific about what's included
- Group related functionality
- Prioritize ruthlessly for MVP
- Consider dependencies

Respond in JSON format:
{{
    "epics": [
        {{
            "title": "<epic title>",
            "description": "<2-3 sentence description>",
            "objective": "<what success looks like>",
            "priority": "<critical|high|medium|low>"
        }}
    ],
    "in_scope": [
        "<specific feature or capability 1>",
        "<specific feature or capability 2>"
    ],
    "out_of_scope": [
        "<feature for future phase 1>",
        "<feature for future phase 2>"
    ],
    "assumptions": ["<assumption 1>", ...],
    "dependencies": ["<external dependency 1>", ...],
    "risks": ["<risk 1>", ...]
}}
"""


async def scope_definition_node(state: RequirementState) -> dict:
    """
    Define project scope based on chosen architecture.

    This node:
    1. Creates Epic definition(s)
    2. Defines in-scope vs out-of-scope items
    3. Identifies assumptions, dependencies, risks

    This is Phase 4 of the multi-phase workflow.
    """
    logger.info(
        "scope_definition",
        channel_id=state.get("channel_id"),
        chosen_architecture=state.get("chosen_architecture"),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Use product_manager persona for scope
    persona_knowledge = get_persona_knowledge("product_manager", state)

    # Build requirements summary
    requirements = state.get("discovered_requirements", [])
    req_str = "\n".join(
        f"- [{r.get('type')}] {r.get('description')}"
        for r in requirements
    ) if requirements else "No specific requirements."

    # Get chosen architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not yet selected"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = f"{opt.get('name')}: {opt.get('description')}"
                break

    prompt = ChatPromptTemplate.from_template(SCOPE_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        architecture=arch_str,
        requirements=req_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        epics = result.get("epics", [])
        in_scope = result.get("in_scope", [])
        out_of_scope = result.get("out_of_scope", [])

        logger.info(
            "scope_defined",
            epic_count=len(epics),
            in_scope_count=len(in_scope),
            out_of_scope_count=len(out_of_scope),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.SCOPE.value not in phase_history:
            phase_history.append(WorkflowPhase.SCOPE.value)

        # Format response for user confirmation
        response_text = _format_scope(epics, in_scope, out_of_scope)
        response_text += "\n\nDoes this scope look correct? Reply 'yes' to proceed, or suggest changes."

        return {
            "current_phase": WorkflowPhase.SCOPE.value,
            "phase_history": phase_history,
            "epics": epics,
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("scope_definition_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.SCOPE.value,
            "error": f"Scope definition failed: {str(e)}",
        }


def _format_scope(
    epics: list[dict],
    in_scope: list[str],
    out_of_scope: list[str],
) -> str:
    """Format scope definition for Slack display."""
    lines = ["*Scope Definition*\n"]

    # Epics
    for epic in epics:
        lines.append(f"\n*Epic: {epic.get('title', 'Untitled')}*")
        lines.append(f"_{epic.get('description', '')}_")
        lines.append(f"Priority: {epic.get('priority', 'medium')}")

    # In Scope
    lines.append("\n*In Scope (MVP):*")
    for item in in_scope:
        lines.append(f"✅ {item}")

    # Out of Scope
    if out_of_scope:
        lines.append("\n*Out of Scope (Future):*")
        for item in out_of_scope:
            lines.append(f"❌ {item}")

    return "\n".join(lines)


# =============================================================================
# Story Breakdown Node (Phase 5)
# =============================================================================

STORY_BREAKDOWN_PROMPT = """You are a product manager expert at writing user stories.
{persona_knowledge}

## Context
Goal: {goal}
Epics to break down:
{epics}

Chosen Architecture: {architecture}

## Your Task
Break each Epic into well-formed user stories:
1. Use proper user story format: "As a [role], I want [goal], so that [benefit]"
2. Define clear acceptance criteria
3. Apply MoSCoW prioritization (Must/Should/Could/Won't)
4. Keep stories small enough for 1-2 sprint completion

## Guidelines
- Each Epic should have 3-7 stories
- Stories should be independently testable
- Include edge cases and error handling stories
- Consider user types and their specific needs

Respond in JSON format:
{{
    "stories": [
        {{
            "epic_index": <0-based index of parent epic>,
            "title": "<story title>",
            "as_a": "<user role>",
            "i_want": "<goal>",
            "so_that": "<benefit>",
            "acceptance_criteria": [
                "<criterion 1>",
                "<criterion 2>"
            ],
            "priority": "<Must|Should|Could|Won't>",
            "labels": ["<label1>", ...]
        }}
    ],
    "total_stories": <count>,
    "coverage_notes": "<any gaps or missing areas>"
}}
"""


async def story_breakdown_node(state: RequirementState) -> dict:
    """
    Break epics into user stories with acceptance criteria.

    This node:
    1. Uses Product Manager persona
    2. Creates user stories for each epic
    3. Applies MoSCoW prioritization
    4. Generates acceptance criteria

    This is Phase 5 of the multi-phase workflow.
    """
    logger.info(
        "story_breakdown",
        channel_id=state.get("channel_id"),
        epic_count=len(state.get("epics", [])),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Use product_manager persona
    persona_knowledge = get_persona_knowledge("product_manager", state)

    # Format epics
    epics = state.get("epics", [])
    epics_str = "\n".join(
        f"{i}. {e.get('title', 'Untitled')}: {e.get('description', '')}"
        for i, e in enumerate(epics)
    ) if epics else "No epics defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(STORY_BREAKDOWN_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        epics=epics_str,
        architecture=arch_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        stories = result.get("stories", [])
        coverage_notes = result.get("coverage_notes", "")

        logger.info(
            "stories_created",
            story_count=len(stories),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.STORIES.value not in phase_history:
            phase_history.append(WorkflowPhase.STORIES.value)

        # Format response
        response_text = _format_stories(stories, epics)
        if coverage_notes:
            response_text += f"\n\n_Note: {coverage_notes}_"
        response_text += "\n\nDo these stories look good? Reply 'yes' to proceed to task breakdown, or suggest changes."

        return {
            "current_phase": WorkflowPhase.STORIES.value,
            "phase_history": phase_history,
            "stories": stories,
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("story_breakdown_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.STORIES.value,
            "error": f"Story breakdown failed: {str(e)}",
        }


def _format_stories(stories: list[dict], epics: list[dict]) -> str:
    """Format stories for Slack display."""
    lines = ["*User Stories*\n"]

    # Group by epic
    epic_stories: dict[int, list[dict]] = {}
    for story in stories:
        epic_idx = story.get("epic_index", 0)
        if epic_idx not in epic_stories:
            epic_stories[epic_idx] = []
        epic_stories[epic_idx].append(story)

    for epic_idx, epic_story_list in sorted(epic_stories.items()):
        epic_title = epics[epic_idx].get("title", f"Epic {epic_idx}") if epic_idx < len(epics) else f"Epic {epic_idx}"
        lines.append(f"\n*{epic_title}*")

        for story in epic_story_list:
            priority_emoji = {
                "Must": "🔴",
                "Should": "🟡",
                "Could": "🟢",
                "Won't": "⚪",
            }.get(story.get("priority", ""), "⚪")

            lines.append(f"\n{priority_emoji} *{story.get('title', 'Untitled')}*")
            lines.append(f"  As a {story.get('as_a', '...')}, I want {story.get('i_want', '...')}, so that {story.get('so_that', '...')}")

            # Acceptance criteria (first 3)
            ac = story.get("acceptance_criteria", [])[:3]
            if ac:
                lines.append("  Acceptance:")
                for criterion in ac:
                    lines.append(f"    ✓ {criterion}")

    return "\n".join(lines)


# =============================================================================
# Task Breakdown Node (Phase 6)
# =============================================================================

TASK_BREAKDOWN_PROMPT = """You are a technical lead breaking stories into implementation tasks.
{persona_knowledge}

## Context
Goal: {goal}
Architecture: {architecture}
Stories to break down:
{stories}

## Your Task
Break each story into technical tasks:
1. Identify specific implementation steps
2. Map dependencies between tasks
3. Estimate complexity (S/M/L/XL)
4. Suggest implementation order

## Guidelines
- Tasks should be 0.5-2 days of work
- Include setup, testing, and documentation tasks
- Identify critical path dependencies
- Flag any risks or blockers

Respond in JSON format:
{{
    "tasks": [
        {{
            "story_index": <0-based index of parent story>,
            "title": "<task title>",
            "description": "<what needs to be done>",
            "complexity": "<S|M|L|XL>",
            "dependencies": [<indices of dependent tasks>],
            "tags": ["<backend|frontend|database|testing|devops>", ...]
        }}
    ],
    "critical_path": [<task indices in order>],
    "estimated_total_days": <number>,
    "risks": ["<risk 1>", ...]
}}
"""


async def task_breakdown_node(state: RequirementState) -> dict:
    """
    Break stories into technical tasks with dependencies.

    This node:
    1. Uses Architect persona for technical breakdown
    2. Creates tasks for each story
    3. Maps dependencies
    4. Estimates complexity

    This is Phase 6 of the multi-phase workflow.
    """
    logger.info(
        "task_breakdown",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Use architect persona for technical tasks
    persona_knowledge = get_persona_knowledge("architect", state)

    # Format stories
    stories = state.get("stories", [])
    stories_str = "\n".join(
        f"{i}. [{s.get('priority', 'M')}] {s.get('title', 'Untitled')}: {s.get('i_want', '')}"
        for i, s in enumerate(stories)
    ) if stories else "No stories defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(TASK_BREAKDOWN_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        stories=stories_str,
        architecture=arch_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        tasks = result.get("tasks", [])
        critical_path = result.get("critical_path", [])
        estimated_days = result.get("estimated_total_days", 0)
        risks = result.get("risks", [])

        logger.info(
            "tasks_created",
            task_count=len(tasks),
            estimated_days=estimated_days,
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.TASKS.value not in phase_history:
            phase_history.append(WorkflowPhase.TASKS.value)

        # Format response
        response_text = _format_tasks(tasks, stories, estimated_days, risks)
        response_text += "\n\nReady for estimation? Reply 'yes' to continue."

        return {
            "current_phase": WorkflowPhase.TASKS.value,
            "phase_history": phase_history,
            "tasks": tasks,
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("task_breakdown_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.TASKS.value,
            "error": f"Task breakdown failed: {str(e)}",
        }


def _format_tasks(
    tasks: list[dict],
    stories: list[dict],
    estimated_days: int,
    risks: list[str],
) -> str:
    """Format tasks for Slack display."""
    lines = ["*Technical Tasks*\n"]

    # Group by story
    story_tasks: dict[int, list[dict]] = {}
    for i, task in enumerate(tasks):
        story_idx = task.get("story_index", 0)
        if story_idx not in story_tasks:
            story_tasks[story_idx] = []
        task["_index"] = i
        story_tasks[story_idx].append(task)

    for story_idx, task_list in sorted(story_tasks.items()):
        story_title = stories[story_idx].get("title", f"Story {story_idx}") if story_idx < len(stories) else f"Story {story_idx}"
        lines.append(f"\n*{story_title}*")

        for task in task_list:
            complexity_emoji = {
                "S": "🟢",
                "M": "🟡",
                "L": "🟠",
                "XL": "🔴",
            }.get(task.get("complexity", "M"), "⚪")

            tags = task.get("tags", [])
            tags_str = f" [{', '.join(tags)}]" if tags else ""

            lines.append(f"  {complexity_emoji} {task.get('title', 'Untitled')}{tags_str}")

    # Summary
    lines.append(f"\n*Estimated Total:* ~{estimated_days} days")

    if risks:
        lines.append("\n*Risks:*")
        for risk in risks[:3]:
            lines.append(f"  ⚠️ {risk}")

    return "\n".join(lines)


# =============================================================================
# Estimation Node (Phase 7)
# =============================================================================

ESTIMATION_PROMPT = """You are an expert at software project estimation.
{persona_knowledge}

## Context
Goal: {goal}
Architecture: {architecture}
Stories: {story_count} stories
Tasks: {task_count} tasks
Task Details:
{tasks}

## Your Task
Provide comprehensive estimation:
1. Story points per story (Fibonacci: 1,2,3,5,8,13,21)
2. Hours per task
3. Risk buffer percentage
4. Total project estimate

## Guidelines
- Be realistic, not optimistic
- Factor in complexity and unknowns
- Consider team ramp-up time
- Add buffer for testing and bug fixes
- Account for meetings, reviews, documentation

Respond in JSON format:
{{
    "story_estimates": [
        {{
            "story_index": <index>,
            "story_points": <fibonacci number>,
            "reasoning": "<brief explanation>"
        }}
    ],
    "task_estimates": [
        {{
            "task_index": <index>,
            "hours": <number>,
            "confidence": "<high|medium|low>"
        }}
    ],
    "totals": {{
        "total_story_points": <sum>,
        "total_hours": <sum>,
        "risk_buffer_percent": <10-50>,
        "total_with_buffer": <total hours with buffer>
    }},
    "assumptions": ["<assumption 1>", ...],
    "risks_to_estimate": ["<risk that could affect timeline 1>", ...]
}}
"""


async def estimation_node(state: RequirementState) -> dict:
    """
    Estimate effort for stories and tasks.

    This node:
    1. Assigns story points to stories
    2. Estimates hours for tasks
    3. Calculates risk buffer
    4. Produces total project estimate

    This is Phase 7 of the multi-phase workflow.
    """
    logger.info(
        "estimation",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
        task_count=len(state.get("tasks", [])),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    # Use architect persona for estimation
    persona_knowledge = get_persona_knowledge("architect", state)

    # Format tasks
    tasks = state.get("tasks", [])
    tasks_str = "\n".join(
        f"{i}. [{t.get('complexity', 'M')}] {t.get('title', 'Untitled')}: {t.get('description', '')[:100]}"
        for i, t in enumerate(tasks)
    ) if tasks else "No tasks defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(ESTIMATION_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        architecture=arch_str,
        story_count=len(state.get("stories", [])),
        task_count=len(tasks),
        tasks=tasks_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        totals = result.get("totals", {})
        story_estimates = result.get("story_estimates", [])
        task_estimates = result.get("task_estimates", [])
        assumptions = result.get("assumptions", [])
        risks = result.get("risks_to_estimate", [])

        logger.info(
            "estimation_complete",
            total_points=totals.get("total_story_points"),
            total_hours=totals.get("total_hours"),
            buffer=totals.get("risk_buffer_percent"),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.ESTIMATION.value not in phase_history:
            phase_history.append(WorkflowPhase.ESTIMATION.value)

        # Format response
        response_text = _format_estimation(totals, story_estimates, assumptions, risks)
        response_text += "\n\nDoes this estimation look reasonable? Reply 'yes' to proceed, or suggest adjustments."

        return {
            "current_phase": WorkflowPhase.ESTIMATION.value,
            "phase_history": phase_history,
            "total_story_points": totals.get("total_story_points"),
            "total_hours": totals.get("total_hours"),
            "risk_buffer_percent": totals.get("risk_buffer_percent"),
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("estimation_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.ESTIMATION.value,
            "error": f"Estimation failed: {str(e)}",
        }


def _format_estimation(
    totals: dict,
    story_estimates: list[dict],
    assumptions: list[str],
    risks: list[str],
) -> str:
    """Format estimation for Slack display."""
    lines = ["*Project Estimation*\n"]

    # Summary
    total_points = totals.get("total_story_points", 0)
    total_hours = totals.get("total_hours", 0)
    buffer = totals.get("risk_buffer_percent", 20)
    total_with_buffer = totals.get("total_with_buffer", total_hours * (1 + buffer / 100))

    lines.append(f"*Total Story Points:* {total_points} SP")
    lines.append(f"*Base Hours:* {total_hours}h")
    lines.append(f"*Risk Buffer:* {buffer}%")
    lines.append(f"*Total with Buffer:* {total_with_buffer:.0f}h (~{total_with_buffer / 8:.0f} days)")

    # Story breakdown
    if story_estimates:
        lines.append("\n*Story Points Breakdown:*")
        for est in story_estimates[:5]:  # Limit to 5
            lines.append(f"  Story {est.get('story_index', '?')}: {est.get('story_points', '?')} SP")

    # Assumptions
    if assumptions:
        lines.append("\n*Assumptions:*")
        for assumption in assumptions[:3]:
            lines.append(f"  • {assumption}")

    # Risks
    if risks:
        lines.append("\n*Timeline Risks:*")
        for risk in risks[:3]:
            lines.append(f"  ⚠️ {risk}")

    return "\n".join(lines)


# =============================================================================
# Security Review Node (Phase 8)
# =============================================================================

SECURITY_REVIEW_PROMPT = """You are a security analyst reviewing requirements for security concerns.
{persona_knowledge}

## Context
Goal: {goal}
Architecture: {architecture}
Stories: {story_count} stories
Tasks: {task_count} tasks

Story Details:
{stories}

## Your Task
Perform a security review:
1. Identify security concerns in the requirements
2. Check for OWASP Top 10 risks
3. Evaluate authentication/authorization needs
4. Check data protection requirements
5. Suggest security stories/tasks if missing

## Security Checklist
- Authentication & Authorization
- Input validation
- Data encryption (at rest, in transit)
- Logging & Audit trails
- Session management
- Error handling (no info leakage)
- Dependency security
- API security

Respond in JSON format:
{{
    "security_rating": "<low|medium|high|critical>",
    "concerns": [
        {{
            "category": "<OWASP category or custom>",
            "description": "<what the concern is>",
            "severity": "<low|medium|high|critical>",
            "affected_stories": [<story indices>],
            "recommendation": "<how to address>"
        }}
    ],
    "missing_requirements": [
        {{
            "title": "<security story/task title>",
            "description": "<what needs to be added>",
            "type": "<Story|Task>",
            "priority": "Must"
        }}
    ],
    "checklist_status": {{
        "authentication": "<pass|fail|partial|n/a>",
        "authorization": "<pass|fail|partial|n/a>",
        "input_validation": "<pass|fail|partial|n/a>",
        "data_encryption": "<pass|fail|partial|n/a>",
        "logging": "<pass|fail|partial|n/a>",
        "error_handling": "<pass|fail|partial|n/a>"
    }},
    "overall_assessment": "<1-2 sentence summary>"
}}
"""


async def security_review_node(state: RequirementState) -> dict:
    """
    Perform security review of requirements.

    This node:
    1. Uses Security Analyst persona
    2. Reviews stories/tasks for security concerns
    3. Checks against OWASP Top 10
    4. Suggests security stories/tasks if missing

    This is Phase 8 of the multi-phase workflow.
    """
    logger.info(
        "security_review",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    # Use security_analyst persona
    persona_knowledge = get_persona_knowledge("security_analyst", state)

    # Format stories
    stories = state.get("stories", [])
    stories_str = "\n".join(
        f"{i}. {s.get('title', 'Untitled')}: {s.get('i_want', '')}"
        for i, s in enumerate(stories)
    ) if stories else "No stories defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(SECURITY_REVIEW_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        architecture=arch_str,
        story_count=len(stories),
        task_count=len(state.get("tasks", [])),
        stories=stories_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        rating = result.get("security_rating", "medium")
        concerns = result.get("concerns", [])
        missing = result.get("missing_requirements", [])
        checklist = result.get("checklist_status", {})
        assessment = result.get("overall_assessment", "")

        logger.info(
            "security_review_complete",
            rating=rating,
            concern_count=len(concerns),
            missing_count=len(missing),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.SECURITY.value not in phase_history:
            phase_history.append(WorkflowPhase.SECURITY.value)

        # Format response
        response_text = _format_security_review(rating, concerns, missing, checklist, assessment)

        return {
            "current_phase": WorkflowPhase.SECURITY.value,
            "phase_history": phase_history,
            "response": response_text,
            "should_respond": True,
            "active_persona": "security_analyst",
        }

    except Exception as e:
        logger.error("security_review_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.SECURITY.value,
            "error": f"Security review failed: {str(e)}",
        }


def _format_security_review(
    rating: str,
    concerns: list[dict],
    missing: list[dict],
    checklist: dict,
    assessment: str,
) -> str:
    """Format security review for Slack display."""
    rating_emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }.get(rating, "⚪")

    lines = [f"*Security Review* {rating_emoji} {rating.upper()}\n"]

    if assessment:
        lines.append(f"_{assessment}_\n")

    # Checklist
    lines.append("*Security Checklist:*")
    status_emoji = {"pass": "✅", "fail": "❌", "partial": "⚠️", "n/a": "➖"}
    for item, status in checklist.items():
        emoji = status_emoji.get(status, "❓")
        lines.append(f"  {emoji} {item.replace('_', ' ').title()}")

    # Concerns
    if concerns:
        lines.append("\n*Security Concerns:*")
        for c in concerns[:5]:
            severity_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(c.get("severity", ""), "⚪")
            lines.append(f"\n{severity_emoji} *{c.get('category', 'Unknown')}*")
            lines.append(f"  {c.get('description', '')}")
            if c.get("recommendation"):
                lines.append(f"  → {c.get('recommendation')}")

    # Missing requirements
    if missing:
        lines.append("\n*Suggested Security Items:*")
        for m in missing[:3]:
            lines.append(f"  + [{m.get('type', 'Task')}] {m.get('title', 'Untitled')}")

    lines.append("\n\nProceed to validation? Reply 'yes' or ask about specific concerns.")

    return "\n".join(lines)


# =============================================================================
# Validation Node (Phase 9)
# =============================================================================

VALIDATION_PROMPT = """You are a QA lead validating requirements completeness and quality.

## Context
Goal: {goal}
Epics: {epic_count}
Stories: {story_count}
Tasks: {task_count}

Epic Details:
{epics}

Story Details:
{stories}

## Your Task
Validate the requirements package:
1. Check for gaps in requirements coverage
2. Verify INVEST criteria for stories
3. Check dependency completeness
4. Verify acceptance criteria quality
5. Check for missing non-functional requirements

## INVEST Criteria
- Independent: Can be developed separately
- Negotiable: Not a contract, open to discussion
- Valuable: Delivers value to user/business
- Estimable: Clear enough to estimate
- Small: Fits in a sprint
- Testable: Has clear acceptance criteria

Respond in JSON format:
{{
    "validation_passed": <true/false>,
    "overall_score": <0-100>,
    "gaps": [
        {{
            "type": "<functional|non-functional|integration|edge-case>",
            "description": "<what's missing>",
            "severity": "<low|medium|high>",
            "suggestion": "<how to fix>"
        }}
    ],
    "invest_violations": [
        {{
            "story_index": <index>,
            "violations": ["<I|N|V|E|S|T>"],
            "explanation": "<why it violates>"
        }}
    ],
    "acceptance_criteria_issues": [
        {{
            "story_index": <index>,
            "issue": "<what's wrong with AC>"
        }}
    ],
    "warnings": ["<warning 1>", ...],
    "ready_for_development": <true/false>,
    "summary": "<overall assessment>"
}}
"""


async def validation_node(state: RequirementState) -> dict:
    """
    Validate requirements completeness and quality.

    This node:
    1. Checks for gaps in coverage
    2. Verifies INVEST criteria
    3. Validates acceptance criteria
    4. Produces validation report

    This is Phase 9 of the multi-phase workflow.
    """
    logger.info(
        "validation",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    # Format epics
    epics = state.get("epics", [])
    epics_str = "\n".join(
        f"{i}. {e.get('title', 'Untitled')}: {e.get('description', '')}"
        for i, e in enumerate(epics)
    ) if epics else "No epics defined."

    # Format stories with acceptance criteria
    stories = state.get("stories", [])
    stories_str = ""
    for i, s in enumerate(stories):
        stories_str += f"\n{i}. {s.get('title', 'Untitled')}"
        stories_str += f"\n   As a {s.get('as_a', '...')}, I want {s.get('i_want', '...')}"
        ac = s.get("acceptance_criteria", [])
        if ac:
            stories_str += "\n   AC: " + "; ".join(ac[:3])

    prompt = ChatPromptTemplate.from_template(VALIDATION_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        epic_count=len(epics),
        story_count=len(stories),
        task_count=len(state.get("tasks", [])),
        epics=epics_str,
        stories=stories_str or "No stories defined.",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        passed = result.get("validation_passed", False)
        score = result.get("overall_score", 0)
        gaps = result.get("gaps", [])
        invest_violations = result.get("invest_violations", [])
        warnings = result.get("warnings", [])
        ready = result.get("ready_for_development", False)
        summary = result.get("summary", "")

        logger.info(
            "validation_complete",
            passed=passed,
            score=score,
            gap_count=len(gaps),
            ready=ready,
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.VALIDATION.value not in phase_history:
            phase_history.append(WorkflowPhase.VALIDATION.value)

        # Build validation report
        validation_report = {
            "passed": passed,
            "score": score,
            "gaps": gaps,
            "invest_violations": invest_violations,
            "warnings": warnings,
            "ready": ready,
        }

        # Format response
        response_text = _format_validation(passed, score, gaps, invest_violations, warnings, summary)

        return {
            "current_phase": WorkflowPhase.VALIDATION.value,
            "phase_history": phase_history,
            "validation_report": validation_report,
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("validation_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.VALIDATION.value,
            "error": f"Validation failed: {str(e)}",
        }


def _format_validation(
    passed: bool,
    score: int,
    gaps: list[dict],
    invest_violations: list[dict],
    warnings: list[str],
    summary: str,
) -> str:
    """Format validation report for Slack display."""
    status = "✅ PASSED" if passed else "❌ NEEDS ATTENTION"

    lines = [f"*Validation Report* {status}\n"]
    lines.append(f"*Quality Score:* {score}/100\n")

    if summary:
        lines.append(f"_{summary}_\n")

    # Gaps
    if gaps:
        lines.append("*Gaps Found:*")
        for g in gaps[:4]:
            severity_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(g.get("severity", ""), "⚪")
            lines.append(f"  {severity_emoji} [{g.get('type', 'unknown')}] {g.get('description', '')}")

    # INVEST violations
    if invest_violations:
        lines.append("\n*INVEST Violations:*")
        for v in invest_violations[:3]:
            violations = ", ".join(v.get("violations", []))
            lines.append(f"  Story {v.get('story_index', '?')}: {violations} - {v.get('explanation', '')}")

    # Warnings
    if warnings:
        lines.append("\n*Warnings:*")
        for w in warnings[:3]:
            lines.append(f"  ⚠️ {w}")

    if passed:
        lines.append("\n\n✅ Ready for final review! Reply 'yes' to proceed.")
    else:
        lines.append("\n\n⚠️ Issues found. Would you like to address them or proceed anyway?")

    return "\n".join(lines)


# =============================================================================
# Final Review Node (Phase 10)
# =============================================================================

async def final_review_node(state: RequirementState) -> dict:
    """
    Present final summary for approval before Jira sync.

    This node:
    1. Compiles complete project summary
    2. Shows hierarchy tree (Epic → Stories → Tasks)
    3. Shows estimates and timeline
    4. Prepares for human approval

    This is Phase 10 of the multi-phase workflow.
    """
    logger.info(
        "final_review",
        channel_id=state.get("channel_id"),
        epic_count=len(state.get("epics", [])),
        story_count=len(state.get("stories", [])),
        task_count=len(state.get("tasks", [])),
    )

    # Update phase history
    phase_history = list(state.get("phase_history", []))
    if WorkflowPhase.REVIEW.value not in phase_history:
        phase_history.append(WorkflowPhase.REVIEW.value)

    # Build comprehensive summary
    epics = state.get("epics", [])
    stories = state.get("stories", [])
    tasks = state.get("tasks", [])

    # Format tree view
    response_text = _format_final_summary(
        goal=state.get("current_goal"),
        epics=epics,
        stories=stories,
        tasks=tasks,
        total_points=state.get("total_story_points"),
        total_hours=state.get("total_hours"),
        risk_buffer=state.get("risk_buffer_percent"),
        validation=state.get("validation_report"),
    )

    return {
        "current_phase": WorkflowPhase.REVIEW.value,
        "phase_history": phase_history,
        "response": response_text,
        "should_respond": True,
        "awaiting_human": True,  # This will trigger approval buttons
    }


def _format_final_summary(
    goal: str | None,
    epics: list[dict],
    stories: list[dict],
    tasks: list[dict],
    total_points: int | None,
    total_hours: int | None,
    risk_buffer: int | None,
    validation: dict | None,
) -> str:
    """Format final summary for Slack display."""
    lines = ["*📋 Final Requirements Summary*\n"]

    if goal:
        lines.append(f"*Goal:* {goal}\n")

    # Metrics
    lines.append("*Metrics:*")
    lines.append(f"  • Epics: {len(epics)}")
    lines.append(f"  • Stories: {len(stories)}")
    lines.append(f"  • Tasks: {len(tasks)}")
    if total_points:
        lines.append(f"  • Story Points: {total_points} SP")
    if total_hours:
        buffer = risk_buffer or 20
        total_with_buffer = total_hours * (1 + buffer / 100)
        lines.append(f"  • Effort: {total_hours}h (+{buffer}% buffer = {total_with_buffer:.0f}h)")

    # Validation status
    if validation:
        status = "✅" if validation.get("passed") else "⚠️"
        score = validation.get("score", 0)
        lines.append(f"  • Validation: {status} {score}/100")

    # Tree view
    lines.append("\n*Hierarchy:*")
    lines.append("```")

    # Group stories by epic
    for i, epic in enumerate(epics):
        lines.append(f"📦 {epic.get('title', f'Epic {i}')}")

        # Find stories for this epic
        epic_stories = [s for s in stories if s.get("epic_index") == i]
        for j, story in enumerate(epic_stories):
            is_last_story = j == len(epic_stories) - 1
            prefix = "└─" if is_last_story else "├─"
            priority_marker = {"Must": "🔴", "Should": "🟡", "Could": "🟢"}.get(story.get("priority", ""), "")
            lines.append(f"  {prefix} {priority_marker} {story.get('title', 'Story')}")

            # Find original story index to get tasks
            orig_idx = stories.index(story) if story in stories else -1
            story_tasks = [t for t in tasks if t.get("story_index") == orig_idx]
            for k, task in enumerate(story_tasks[:3]):  # Limit tasks shown
                is_last_task = k == len(story_tasks) - 1 or k == 2
                task_prefix = "    └─" if is_last_task else "    ├─"
                complexity = task.get("complexity", "M")
                lines.append(f"  {task_prefix} [{complexity}] {task.get('title', 'Task')}")
            if len(story_tasks) > 3:
                lines.append(f"      ... and {len(story_tasks) - 3} more tasks")

    lines.append("```")

    lines.append("\n*Ready to create in Jira?*")
    lines.append("Use the buttons below to approve, edit, or reject.")

    return "\n".join(lines)


# =============================================================================
# Memory Node (Zep Retrieval)
# =============================================================================

async def memory_node(state: RequirementState) -> dict:
    """
    Retrieve relevant context from Zep memory.

    Fetches facts, entities, and previous conversations related to the message.
    """
    from src.memory.zep_client import get_zep_client

    logger.info("retrieving_memory", channel_id=state.get("channel_id"))

    try:
        zep = await get_zep_client()
        session_id = f"channel-{state.get('channel_id')}"

        # Search for relevant memories
        results = await zep.memory.search(
            session_id=session_id,
            text=state.get("message", ""),
            limit=10,
        )

        facts = []
        for result in results:
            # Handle dict format from our HTTP-based zep client
            facts.append({
                "content": result.get("content", ""),
                "relevance": result.get("score", 0.0),
                "timestamp": result.get("created_at"),
            })

        logger.info("memory_retrieved", fact_count=len(facts))

        return {
            "zep_facts": facts,
            "zep_session_id": session_id,
        }

    except Exception as e:
        logger.warning("memory_retrieval_failed", error=str(e))
        return {
            "zep_facts": [],
            "zep_session_id": f"channel-{state.get('channel_id')}",
        }


# =============================================================================
# Conflict Detection Node
# =============================================================================

CONFLICT_DETECTION_PROMPT = """Analyze the new requirement against existing requirements and identify any conflicts.

Types of conflicts to detect:
1. contradiction: New requirement directly contradicts an existing one
2. duplicate: New requirement is essentially the same as existing
3. overlap: Significant overlap that needs clarification

New requirement:
{new_requirement}

Existing requirements:
{existing_requirements}

Respond in JSON format:
{{
    "conflicts": [
        {{
            "existing_id": "<id>",
            "existing_summary": "<summary>",
            "conflict_type": "<type>",
            "description": "<explanation>"
        }}
    ],
    "has_conflicts": <true/false>
}}

If no conflicts, return {{"conflicts": [], "has_conflicts": false}}
"""


async def conflict_detection_node(state: RequirementState) -> dict:
    """
    Check for conflicts between new requirement and existing ones.

    Searches Zep and Jira for related requirements and uses LLM to detect conflicts.

    IMPORTANT: When no conflicts are found, this node sets awaiting_human=True because
    the next node (human_approval) uses interrupt_before and won't run until resumed.
    """
    print(f"[DEBUG] conflict_detection_node called, has_draft={bool(state.get('draft'))}")

    # Skip if no draft to check
    if not state.get("draft"):
        print(f"[DEBUG] conflict_detection: no draft, returning empty")
        return {"conflicts": []}

    logger.info("detecting_conflicts", channel_id=state.get("channel_id"))

    llm = get_llm_for_state(state, temperature=0.1)

    # Build existing requirements from memory and Jira
    existing = []
    for fact in state.get("zep_facts", [])[:20]:
        existing.append(f"- {fact.get('content', '')}")

    for issue in state.get("related_jira_issues", [])[:10]:
        existing.append(f"- [{issue.get('key')}] {issue.get('summary', '')}")

    if not existing:
        # No existing requirements to check against - proceed to human approval
        print(f"[DEBUG] conflict_detection: no existing requirements, setting awaiting_human=True")
        return {"conflicts": [], "awaiting_human": True}

    draft = state.get("draft", {})
    new_req = f"Title: {draft.get('title', '')}\nDescription: {draft.get('description', '')}"

    prompt = ChatPromptTemplate.from_template(CONFLICT_DETECTION_PROMPT)
    messages = prompt.format_messages(
        new_requirement=new_req,
        existing_requirements="\n".join(existing),
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        conflicts = result.get("conflicts", [])
        logger.info("conflicts_detected", count=len(conflicts))

        # If no conflicts, we're heading to human_approval which uses interrupt_before
        # Set awaiting_human=True so handlers.py knows to show approval buttons
        if not conflicts:
            print(f"[DEBUG] conflict_detection: no conflicts found, setting awaiting_human=True")
            return {"conflicts": [], "awaiting_human": True}

        print(f"[DEBUG] conflict_detection: {len(conflicts)} conflicts found")
        return {"conflicts": conflicts}

    except Exception as e:
        logger.error("conflict_detection_failed", error=str(e))
        return {"conflicts": [], "error": f"Conflict detection failed: {str(e)}"}


# =============================================================================
# Draft Node
# =============================================================================

DRAFT_REQUIREMENT_PROMPT = """You are a requirements engineering expert.
{persona_knowledge}

Analyze the user's input and create well-structured requirements.

## IMPORTANT: Sizing Guidelines
- **Epic**: Large initiative spanning multiple sprints, contains 5+ distinct features/user flows
- **Story**: Single user-facing feature completable in 1-2 sprints
- **Task**: Technical work item, usually 1-3 days

## Auto-Split Rules
If the user describes a complex system with multiple distinct features, roles, or workflows:
1. Create ONE Epic as the parent container
2. Break it down into multiple Stories (3-7 stories typically)
3. Each Story should be independently deliverable

For simpler requests, create a single Story or Task.

## Format
Use user story format: "As a [user type], I want [goal], so that [benefit]."

Include clear acceptance criteria that are:
- Specific and measurable
- Testable by QA
- Unambiguous

User message: {message}

Context from conversation:
{context}

Current goal/scope: {goal}

Respond in JSON format. For complex requirements, use the "requirements" array:
{{
    "is_complex": <true if needs splitting into Epic + Stories>,
    "requirements": [
        {{
            "title": "<concise title>",
            "description": "<full description>",
            "issue_type": "<Epic|Story|Task|Bug>",
            "acceptance_criteria": ["<criterion 1>", ...],
            "priority": "<low|medium|high|critical>",
            "labels": ["<label1>", ...],
            "parent_index": <null for Epic, 0 for children of first Epic>
        }}
    ],
    "reasoning": "<explain the structure and why you chose this breakdown>"
}}

For simple requirements, you can return a single item in the array.
"""


async def draft_node(state: RequirementState) -> dict:
    """
    Create or refine requirement draft(s) based on user input.

    Now supports:
    - Persona-specific knowledge
    - Auto-splitting complex requirements into Epic + Stories
    """
    logger.info(
        "drafting_requirement",
        channel_id=state.get("channel_id"),
        iteration=state.get("iteration_count", 0),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Get persona knowledge if active
    persona_name = state.get("active_persona")
    persona_knowledge = get_persona_knowledge(persona_name, state)

    # Build context
    context = ""
    for fact in state.get("zep_facts", [])[:5]:
        context += f"- {fact.get('content', '')}\n"

    # Include previous feedback if refining
    if state.get("critique_feedback"):
        context += "\nPrevious feedback to address:\n"
        for feedback in state["critique_feedback"]:
            context += f"- {feedback}\n"

    prompt = ChatPromptTemplate.from_template(DRAFT_REQUIREMENT_PROMPT)
    messages = prompt.format_messages(
        message=state.get("message", ""),
        context=context or "No additional context.",
        goal=state.get("current_goal") or "Not yet established",
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        requirements = result.get("requirements", [])
        is_complex = result.get("is_complex", False)

        if not requirements:
            # Fallback for old format
            requirements = [result]

        # Process requirements
        drafts = []
        for req in requirements:
            draft = {
                "title": req.get("title", ""),
                "description": req.get("description", ""),
                "issue_type": req.get("issue_type", "Story"),
                "acceptance_criteria": req.get("acceptance_criteria", []),
                "priority": req.get("priority", "medium"),
                "labels": req.get("labels", []),
                "parent_index": req.get("parent_index"),
            }
            drafts.append(draft)

        # For now, use the first draft as the main one
        # (multi-draft handling will be added to approval flow)
        main_draft = drafts[0] if drafts else {}

        logger.info(
            "draft_created",
            title=main_draft.get("title"),
            issue_type=main_draft.get("issue_type"),
            total_drafts=len(drafts),
            is_complex=is_complex,
        )

        return {
            "draft": main_draft,
            "all_drafts": drafts if len(drafts) > 1 else None,
            "is_complex_requirement": is_complex,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    except Exception as e:
        logger.error("draft_creation_failed", error=str(e))
        return {"error": f"Draft creation failed: {str(e)}"}


# =============================================================================
# Critique Node (Reflexion)
# =============================================================================

CRITIQUE_PROMPT = """You are a strict QA reviewer for requirements. Critically evaluate this requirement draft.

Check for:
1. Clarity: Is it unambiguous?
2. Completeness: Are all necessary details included?
3. Testability: Can acceptance criteria be verified?
4. INVEST principles: Independent, Negotiable, Valuable, Estimable, Small, Testable
5. User story format (if applicable): As a..., I want..., so that...

Requirement draft:
Title: {title}
Description: {description}
Type: {issue_type}
Acceptance Criteria: {acceptance_criteria}
Priority: {priority}

Respond in JSON format:
{{
    "is_acceptable": <true/false>,
    "issues": ["<issue 1>", "<issue 2>", ...],
    "suggestions": ["<suggestion 1>", "<suggestion 2>", ...],
    "overall_quality": "<poor|fair|good|excellent>"
}}

Be strict but fair. Minor issues should still pass if the core requirement is clear.
"""


async def critique_node(state: RequirementState) -> dict:
    """
    Critique the requirement draft and provide feedback.

    Returns whether draft is acceptable or needs refinement.
    """
    draft = state.get("draft")
    if not draft:
        return {"critique_feedback": ["No draft to critique"]}

    logger.info(
        "critiquing_draft",
        channel_id=state.get("channel_id"),
        iteration=state.get("iteration_count", 0),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    prompt = ChatPromptTemplate.from_template(CRITIQUE_PROMPT)
    messages = prompt.format_messages(
        title=draft.get("title", ""),
        description=draft.get("description", ""),
        issue_type=draft.get("issue_type", ""),
        acceptance_criteria="\n".join(draft.get("acceptance_criteria", [])),
        priority=draft.get("priority", ""),
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        is_acceptable = result.get("is_acceptable", False)
        issues = result.get("issues", [])
        suggestions = result.get("suggestions", [])

        logger.info(
            "critique_complete",
            is_acceptable=is_acceptable,
            issue_count=len(issues),
        )

        # Combine issues and suggestions as feedback
        feedback = issues + suggestions

        return {
            "critique_feedback": feedback if not is_acceptable else [],
        }

    except Exception as e:
        logger.error("critique_failed", error=str(e))
        return {"critique_feedback": [], "error": f"Critique failed: {str(e)}"}


# =============================================================================
# Human Approval Node
# =============================================================================

async def human_approval_node(state: RequirementState) -> dict:
    """
    Handle human-in-the-loop approval.

    This node is interrupted before execution to wait for human decision.
    The actual approval UI is handled by Slack handlers.
    """
    print(f"[DEBUG] human_approval_node called - this should NOT appear if interrupt_before works")
    logger.info(
        "awaiting_human_approval",
        channel_id=state.get("channel_id"),
        draft_title=state.get("draft", {}).get("title"),
    )

    # This state signals that we're waiting for human input
    return {
        "awaiting_human": True,
        "human_decision": HumanDecision.PENDING.value,
    }


async def process_human_decision_node(state: RequirementState) -> dict:
    """
    Process the human decision after approval/rejection.

    Routes to appropriate next action based on decision.
    """
    decision = state.get("human_decision", HumanDecision.PENDING.value)

    logger.info(
        "processing_human_decision",
        channel_id=state.get("channel_id"),
        decision=decision,
    )

    if decision == HumanDecision.APPROVE.value:
        return {"awaiting_human": False, "jira_action": "create"}

    elif decision == HumanDecision.APPROVE_ALWAYS.value:
        # Will be handled by approval system to store permanent approval
        return {"awaiting_human": False, "jira_action": "create"}

    elif decision == HumanDecision.EDIT.value:
        # Reset for new iteration with feedback
        return {
            "awaiting_human": False,
            "iteration_count": 0,  # Reset iterations for edit
        }

    elif decision == HumanDecision.REJECT.value:
        return {
            "awaiting_human": False,
            "draft": None,
            "response": "Requirement rejected. Let me know if you'd like to try again.",
        }

    return {"awaiting_human": False}


# =============================================================================
# Jira Write Node
# =============================================================================

async def jira_write_node(state: RequirementState) -> dict:
    """
    Create or update Jira issues via MCP.

    Creates a full hierarchy: Epic → Stories → Tasks.
    Uses parent_key to establish relationships.
    """
    from src.jira.mcp_client import get_jira_client

    action = state.get("jira_action")

    if not action:
        return {}

    # Get project key from channel config
    config = state.get("channel_config", {})
    project_key = config.get("jira_project_key", "MARO")

    logger.info(
        "writing_to_jira",
        channel_id=state.get("channel_id"),
        action=action,
        project_key=project_key,
    )

    try:
        jira = await get_jira_client()

        if action == "create":
            # Check if we have epics/stories/tasks from the workflow
            epics = state.get("epics", [])
            stories = state.get("stories", [])
            tasks = state.get("tasks", [])

            # If we have epics, create full hierarchy
            if epics:
                return await _create_jira_hierarchy(
                    jira, project_key, epics, stories, tasks
                )

            # Fallback: create single issue from draft
            draft = state.get("draft")
            if draft:
                return await _create_single_issue(jira, project_key, draft)

            return {}

        elif action == "update":
            issue_key = state.get("jira_issue_key")
            draft = state.get("draft")
            if issue_key and draft:
                result = await jira.update_issue(
                    issue_key=issue_key,
                    summary=draft.get("title"),
                    description=draft.get("description"),
                )
                return {"jira_issue_data": result}

    except Exception as e:
        logger.error("jira_write_failed", error=str(e))
        return {"error": f"Jira write failed: {str(e)}"}

    return {}


async def _create_single_issue(jira, project_key: str, draft: dict) -> dict:
    """Create a single Jira issue from a draft."""
    result = await jira.create_issue(
        project_key=project_key,
        issue_type=draft.get("issue_type", "Story"),
        summary=draft.get("title", ""),
        description=draft.get("description", ""),
        priority=draft.get("priority", "Medium"),
        labels=draft.get("labels", []),
    )

    issue_key = result.get("key")
    logger.info("jira_issue_created", key=issue_key)

    return {
        "jira_issue_key": issue_key,
        "jira_issue_data": result,
        "response": f"Created Jira issue: {issue_key}",
        "jira_items": [{"key": issue_key, "type": draft.get("issue_type", "Story")}],
    }


def _map_priority(priority: str) -> str:
    """Map workflow priority to Jira priority."""
    mapping = {
        # MoSCoW for stories
        "Must": "Highest",
        "Should": "High",
        "Could": "Medium",
        "Won't": "Low",
        # Standard for epics
        "critical": "Highest",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
    }
    return mapping.get(priority, "Medium")


def _build_story_description(story: dict) -> str:
    """Build Jira description from user story format."""
    lines = []

    # User story format
    lines.append(f"*As a* {story.get('as_a', 'user')},")
    lines.append(f"*I want* {story.get('i_want', '...')},")
    lines.append(f"*So that* {story.get('so_that', '...')}.")
    lines.append("")

    # Acceptance criteria
    ac = story.get("acceptance_criteria", [])
    if ac:
        lines.append("*Acceptance Criteria:*")
        for criterion in ac:
            lines.append(f"* {criterion}")

    return "\n".join(lines)


def _build_task_description(task: dict) -> str:
    """Build Jira description from task format."""
    lines = []

    if task.get("description"):
        lines.append(task["description"])
        lines.append("")

    # Complexity
    if task.get("complexity"):
        lines.append(f"*Complexity:* {task['complexity']}")

    # Dependencies
    deps = task.get("dependencies", [])
    if deps:
        lines.append(f"*Dependencies:* Task indices {deps}")

    return "\n".join(lines)


async def _create_jira_hierarchy(
    jira,
    project_key: str,
    epics: list[dict],
    stories: list[dict],
    tasks: list[dict],
) -> dict:
    """
    Create full Jira hierarchy: Epic → Stories → Tasks.

    Returns created issue keys and summary.
    """
    created_items = []
    epic_keys = []
    story_keys = []
    errors = []

    # 1. Create Epics
    logger.info("creating_epics", count=len(epics))
    for i, epic in enumerate(epics):
        try:
            description = epic.get("description", "")
            if epic.get("objective"):
                description += f"\n\n*Objective:* {epic['objective']}"

            result = await jira.create_issue(
                project_key=project_key,
                issue_type="Epic",
                summary=epic.get("title", f"Epic {i + 1}"),
                description=description,
                priority=_map_priority(epic.get("priority", "medium")),
                labels=epic.get("labels", []),
            )

            epic_key = result.get("key")
            epic_keys.append(epic_key)
            created_items.append({
                "key": epic_key,
                "type": "Epic",
                "title": epic.get("title", ""),
            })
            logger.info("epic_created", key=epic_key, index=i)

        except Exception as e:
            error_msg = f"Epic {i} failed: {str(e)}"
            logger.error("epic_creation_failed", index=i, error=str(e))
            errors.append(error_msg)
            epic_keys.append(None)

    # 2. Create Stories (linked to Epics)
    logger.info("creating_stories", count=len(stories))
    for i, story in enumerate(stories):
        try:
            epic_index = story.get("epic_index", 0)
            parent_key = epic_keys[epic_index] if epic_index < len(epic_keys) else None

            description = _build_story_description(story)

            result = await jira.create_issue(
                project_key=project_key,
                issue_type="Story",
                summary=story.get("title", f"Story {i + 1}"),
                description=description,
                priority=_map_priority(story.get("priority", "Should")),
                labels=story.get("labels", []),
                parent_key=parent_key,  # Links to Epic
            )

            story_key = result.get("key")
            story_keys.append(story_key)
            created_items.append({
                "key": story_key,
                "type": "Story",
                "title": story.get("title", ""),
                "parent": parent_key,
            })
            logger.info("story_created", key=story_key, index=i, epic=parent_key)

        except Exception as e:
            error_msg = f"Story {i} failed: {str(e)}"
            logger.error("story_creation_failed", index=i, error=str(e))
            errors.append(error_msg)
            story_keys.append(None)

    # 3. Create Tasks (linked to Stories)
    logger.info("creating_tasks", count=len(tasks))
    for i, task in enumerate(tasks):
        try:
            story_index = task.get("story_index", 0)
            parent_key = story_keys[story_index] if story_index < len(story_keys) else None

            description = _build_task_description(task)

            result = await jira.create_issue(
                project_key=project_key,
                issue_type="Task",
                summary=task.get("title", f"Task {i + 1}"),
                description=description,
                priority="Medium",  # Tasks inherit story priority implicitly
                labels=task.get("labels", []),
                parent_key=parent_key,  # Links to Story
            )

            task_key = result.get("key")
            created_items.append({
                "key": task_key,
                "type": "Task",
                "title": task.get("title", ""),
                "parent": parent_key,
            })
            logger.info("task_created", key=task_key, index=i, story=parent_key)

        except Exception as e:
            error_msg = f"Task {i} failed: {str(e)}"
            logger.error("task_creation_failed", index=i, error=str(e))
            errors.append(error_msg)

    # Build summary response
    summary_lines = ["*Jira Issues Created:*"]
    summary_lines.append(f"• {len(epic_keys)} Epic(s): {', '.join(k for k in epic_keys if k)}")
    summary_lines.append(f"• {len(story_keys)} Story(ies): {', '.join(k for k in story_keys if k)}")
    task_keys = [item["key"] for item in created_items if item["type"] == "Task"]
    summary_lines.append(f"• {len(task_keys)} Task(s): {', '.join(task_keys)}")

    if errors:
        summary_lines.append(f"\n⚠️ {len(errors)} error(s) occurred during creation.")

    response = "\n".join(summary_lines)

    logger.info(
        "jira_hierarchy_created",
        epics=len(epic_keys),
        stories=len(story_keys),
        tasks=len(task_keys),
        errors=len(errors),
    )

    return {
        "jira_items": created_items,
        "jira_issue_key": epic_keys[0] if epic_keys else None,  # Primary key for reference
        "response": response,
        "error": "\n".join(errors) if errors else None,
    }


# =============================================================================
# Memory Update Node
# =============================================================================

async def memory_update_node(state: RequirementState) -> dict:
    """
    Save the processed requirement to Zep memory.

    Stores the requirement as a fact for future retrieval.
    """
    from src.memory.zep_client import get_zep_client

    draft = state.get("draft")
    if not draft:
        return {}

    logger.info("updating_memory", channel_id=state.get("channel_id"))

    try:
        zep = await get_zep_client()
        session_id = state.get("zep_session_id", f"channel-{state.get('channel_id')}")

        # Add the requirement as a message to the session
        await zep.memory.add(
            session_id=session_id,
            messages=[
                {
                    "role": "assistant",
                    "content": f"Created requirement: {draft.get('title')} - {draft.get('description')}",
                    "metadata": {
                        "type": "requirement",
                        "issue_type": draft.get("issue_type"),
                        "jira_key": state.get("jira_issue_key"),
                        "channel_id": state.get("channel_id"),
                        "user_id": state.get("user_id"),
                    },
                }
            ],
        )

        logger.info("memory_updated", session_id=session_id)
        return {}

    except Exception as e:
        logger.warning("memory_update_failed", error=str(e))
        return {}


# =============================================================================
# Jira Command Handler Nodes
# =============================================================================


async def jira_read_node(state: RequirementState) -> dict:
    """
    Re-read/refresh a specific Jira issue.

    Fetches the latest data from Jira and updates memory.
    """
    from src.jira.mcp_client import get_jira_client

    target_key = state.get("jira_command_target")

    if not target_key:
        return {
            "response": "Please specify a Jira issue key to refresh (e.g., 're-read PROJ-123').",
            "error": "No target issue specified",
        }

    logger.info("jira_read_requested", key=target_key)

    try:
        jira = await get_jira_client()
        issue = await jira.get_issue(target_key)

        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "Unknown")
        summary = fields.get("summary", "")
        description = fields.get("description", "")[:500]
        issue_type = fields.get("issuetype", {}).get("name", "")

        # Build response
        response_lines = [
            f"*{target_key}* - {summary}",
            f"*Type:* {issue_type} | *Status:* {status}",
        ]
        if description:
            response_lines.append(f"\n_{description}_")

        logger.info("jira_read_complete", key=target_key, status=status)

        return {
            "response": "\n".join(response_lines),
            "jira_issue_data": issue,
        }

    except Exception as e:
        logger.error("jira_read_failed", key=target_key, error=str(e))
        return {
            "response": f"Failed to read {target_key}: {str(e)}",
            "error": str(e),
        }


async def jira_status_node(state: RequirementState) -> dict:
    """
    Show status of all Jira items in this thread/conversation.

    Displays current state of all tracked issues.
    """
    from src.jira.mcp_client import get_jira_client

    jira_items = state.get("jira_items", [])

    if not jira_items:
        return {
            "response": "No Jira items tracked in this conversation yet.\n\nCreate some requirements and I'll track them here!",
        }

    logger.info("jira_status_requested", item_count=len(jira_items))

    try:
        jira = await get_jira_client()

        # Fetch current status for each item
        status_lines = ["*Jira Items in This Thread:*\n"]
        status_emoji = {
            "To Do": "⚪",
            "In Progress": "🔵",
            "In Review": "🟡",
            "Done": "✅",
            "Blocked": "🔴",
        }

        for item in jira_items:
            key = item.get("key")
            if not key:
                continue

            try:
                issue = await jira.get_issue(key)
                fields = issue.get("fields", {})
                status = fields.get("status", {}).get("name", "Unknown")
                summary = fields.get("summary", item.get("title", ""))
                issue_type = item.get("type", "")

                emoji = status_emoji.get(status, "⚪")
                status_lines.append(f"{emoji} *{key}* [{issue_type}] - {summary}")
                status_lines.append(f"   Status: {status}")

            except Exception as e:
                status_lines.append(f"⚠️ *{key}* - Unable to fetch ({str(e)[:30]})")

        return {
            "response": "\n".join(status_lines),
        }

    except Exception as e:
        logger.error("jira_status_failed", error=str(e))
        return {
            "response": f"Failed to fetch status: {str(e)}",
            "error": str(e),
        }


async def jira_add_node(state: RequirementState) -> dict:
    """
    Add a new story/task to an existing epic.

    Uses LLM to generate the item based on user description,
    then creates it in Jira linked to the parent.
    """
    from src.jira.mcp_client import get_jira_client

    parent_key = state.get("jira_command_parent")
    item_type = state.get("jira_command_type", "story")
    message = state.get("message", "")

    if not parent_key:
        return {
            "response": "Please specify a parent issue to add to (e.g., 'add story to EPIC-123: user login feature').",
            "error": "No parent issue specified",
        }

    logger.info("jira_add_requested", parent=parent_key, type=item_type)

    # Get project key from config
    config = state.get("channel_config", {})
    project_key = config.get("jira_project_key", "MARO")

    try:
        jira = await get_jira_client()

        # Verify parent exists
        parent_issue = await jira.get_issue(parent_key)
        parent_summary = parent_issue.get("fields", {}).get("summary", "")

        # Use LLM to generate item details from the message
        llm = get_llm_for_state(state, temperature=0.3)

        prompt = f"""Generate a {item_type} to add to: {parent_key} - {parent_summary}

User's request: {message}

Respond in JSON:
{{
    "title": "<concise title>",
    "description": "<detailed description>",
    "acceptance_criteria": ["<criterion 1>", "<criterion 2>"]
}}
"""
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        result = parse_llm_json_response(response)

        title = result.get("title", "New item")
        description = result.get("description", "")
        ac = result.get("acceptance_criteria", [])

        # Build full description
        full_description = description
        if ac:
            full_description += "\n\n*Acceptance Criteria:*\n" + "\n".join(f"* {c}" for c in ac)

        # Create the issue
        issue_type_map = {"story": "Story", "task": "Task", "bug": "Bug"}
        jira_issue_type = issue_type_map.get(item_type.lower(), "Story")

        created = await jira.create_issue(
            project_key=project_key,
            issue_type=jira_issue_type,
            summary=title,
            description=full_description,
            parent_key=parent_key,
        )

        new_key = created.get("key")
        logger.info("jira_add_complete", key=new_key, parent=parent_key)

        # Update jira_items
        new_items = state.get("jira_items", []) + [{
            "key": new_key,
            "type": jira_issue_type,
            "title": title,
            "parent": parent_key,
        }]

        return {
            "response": f"Created *{new_key}*: {title}\n\nLinked to {parent_key}",
            "jira_items": new_items,
            "jira_issue_key": new_key,
        }

    except Exception as e:
        logger.error("jira_add_failed", parent=parent_key, error=str(e))
        return {
            "response": f"Failed to add {item_type} to {parent_key}: {str(e)}",
            "error": str(e),
        }


async def jira_update_node(state: RequirementState) -> dict:
    """
    Update a specific Jira issue based on user request.

    Uses LLM to determine what fields to update.
    """
    from src.jira.mcp_client import get_jira_client

    target_key = state.get("jira_command_target")
    message = state.get("message", "")

    if not target_key:
        return {
            "response": "Please specify a Jira issue to update (e.g., 'update PROJ-123 description to ...').",
            "error": "No target issue specified",
        }

    logger.info("jira_update_requested", key=target_key)

    try:
        jira = await get_jira_client()

        # Get current issue state
        current = await jira.get_issue(target_key)
        current_fields = current.get("fields", {})
        current_summary = current_fields.get("summary", "")
        current_description = current_fields.get("description", "")

        # Use LLM to determine updates
        llm = get_llm_for_state(state, temperature=0.3)

        prompt = f"""Analyze what the user wants to update in this Jira issue.

Issue: {target_key}
Current title: {current_summary}
Current description: {current_description[:500]}

User's request: {message}

Respond in JSON with ONLY the fields to update (omit fields that shouldn't change):
{{
    "summary": "<new title or null>",
    "description": "<new description or null>",
    "status": "<new status or null>"
}}
"""
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        result = parse_llm_json_response(response)

        # Extract updates (filter nulls and unchanged)
        updates = {}
        if result.get("summary") and result["summary"] != current_summary:
            updates["summary"] = result["summary"]
        if result.get("description") and result["description"] != current_description:
            updates["description"] = result["description"]

        if not updates:
            return {
                "response": f"No changes detected for {target_key}. Please be more specific about what you'd like to update.",
            }

        # Apply updates
        await jira.update_issue(
            issue_key=target_key,
            summary=updates.get("summary"),
            description=updates.get("description"),
            status=result.get("status"),
        )

        logger.info("jira_update_complete", key=target_key, updated_fields=list(updates.keys()))

        # Build response
        update_list = ", ".join(updates.keys())
        return {
            "response": f"Updated *{target_key}*\n\nChanged: {update_list}",
        }

    except Exception as e:
        logger.error("jira_update_failed", key=target_key, error=str(e))
        return {
            "response": f"Failed to update {target_key}: {str(e)}",
            "error": str(e),
        }


async def jira_delete_node(state: RequirementState) -> dict:
    """
    Delete a Jira issue.

    Requires confirmation before deletion (handled by checking for explicit intent).
    """
    from src.jira.mcp_client import get_jira_client

    target_key = state.get("jira_command_target")

    if not target_key:
        return {
            "response": "Please specify a Jira issue to delete (e.g., 'delete PROJ-123').",
            "error": "No target issue specified",
        }

    logger.info("jira_delete_requested", key=target_key)

    try:
        jira = await get_jira_client()

        # Get issue details before deletion for confirmation message
        issue = await jira.get_issue(target_key)
        summary = issue.get("fields", {}).get("summary", "")
        issue_type = issue.get("fields", {}).get("issuetype", {}).get("name", "")

        # Delete the issue
        await jira.delete_issue(target_key)

        logger.info("jira_delete_complete", key=target_key)

        # Remove from jira_items if present
        updated_items = [
            item for item in state.get("jira_items", [])
            if item.get("key") != target_key
        ]

        return {
            "response": f"Deleted *{target_key}* ({issue_type}): {summary}",
            "jira_items": updated_items,
        }

    except Exception as e:
        logger.error("jira_delete_failed", key=target_key, error=str(e))
        return {
            "response": f"Failed to delete {target_key}: {str(e)}",
            "error": str(e),
        }


# =============================================================================
# Impact Analysis Node
# =============================================================================

IMPACT_ANALYSIS_PROMPT = """You are analyzing the impact of a change request on existing requirements.

## Current State
Epics: {epics}
Stories: {stories}
Tasks: {tasks}
Architecture: {architecture}

## Change Request
{change_request}

## Impact Categories
Classify the impact and determine what needs to be re-evaluated:

1. **architecture**: Changes to system design, components, integrations, or technical approach
   - Examples: "switch to microservices", "add Redis caching", "change database"
   - Requires: Re-evaluate architecture → scope → stories → tasks → estimation

2. **scope**: Changes to what's included/excluded, epic-level changes
   - Examples: "add mobile app support", "remove admin panel", "add new epic"
   - Requires: Re-evaluate scope → stories → tasks → estimation

3. **story**: Changes to user stories, acceptance criteria, priorities
   - Examples: "add new story", "change acceptance criteria", "reprioritize"
   - Requires: Re-evaluate stories → tasks → estimation

4. **task**: Changes to technical tasks, dependencies
   - Examples: "add new task", "change task order", "update dependencies"
   - Requires: Re-evaluate tasks → estimation

5. **estimation**: Changes to estimates only
   - Examples: "increase story points", "add buffer time"
   - Requires: Re-evaluate estimation only

6. **text_only**: Minor text changes that don't affect structure
   - Examples: "fix typo", "clarify description", "update wording"
   - Requires: Direct update, no re-evaluation

Respond in JSON:
{{
    "impact_level": "<architecture|scope|story|task|estimation|text_only>",
    "confidence": <0.0-1.0>,
    "affected_items": ["<item key or index>", ...],
    "reasoning": "<brief explanation>",
    "cascade_phases": ["<phase1>", "<phase2>", ...],
    "suggested_action": "<what to do next>"
}}
"""


class ImpactLevel:
    """Impact levels for change classification."""
    ARCHITECTURE = "architecture"
    SCOPE = "scope"
    STORY = "story"
    TASK = "task"
    ESTIMATION = "estimation"
    TEXT_ONLY = "text_only"


# Mapping from impact level to starting phase
IMPACT_TO_PHASE = {
    ImpactLevel.ARCHITECTURE: WorkflowPhase.ARCHITECTURE.value,
    ImpactLevel.SCOPE: WorkflowPhase.SCOPE.value,
    ImpactLevel.STORY: WorkflowPhase.STORIES.value,
    ImpactLevel.TASK: WorkflowPhase.TASKS.value,
    ImpactLevel.ESTIMATION: WorkflowPhase.ESTIMATION.value,
    ImpactLevel.TEXT_ONLY: None,  # Direct update, no phase
}


async def impact_analysis_node(state: RequirementState) -> dict:
    """
    Analyze the impact of a change request and determine re-evaluation path.

    Used when user wants to modify existing requirements after they've been
    through the full workflow. Determines which phases need to be re-run.
    """
    message = state.get("message", "")

    # Get current state summary
    epics = state.get("epics", [])
    stories = state.get("stories", [])
    tasks = state.get("tasks", [])
    architecture = state.get("chosen_architecture", {})

    logger.info(
        "impact_analysis_started",
        channel_id=state.get("channel_id"),
        epic_count=len(epics),
        story_count=len(stories),
        task_count=len(tasks),
    )

    # Format current state for LLM
    epics_summary = "\n".join(
        f"- Epic {i}: {e.get('title', 'Untitled')}"
        for i, e in enumerate(epics)
    ) or "None defined"

    stories_summary = "\n".join(
        f"- Story {i} (Epic {s.get('epic_index', 0)}): {s.get('title', 'Untitled')}"
        for i, s in enumerate(stories)
    ) or "None defined"

    tasks_summary = "\n".join(
        f"- Task {i} (Story {t.get('story_index', 0)}): {t.get('title', 'Untitled')}"
        for i, t in enumerate(tasks)
    ) or "None defined"

    arch_summary = architecture.get("name", "Not chosen") if architecture else "Not chosen"

    llm = get_llm_for_state(state, temperature=0.2)

    prompt = ChatPromptTemplate.from_template(IMPACT_ANALYSIS_PROMPT)
    messages = prompt.format_messages(
        epics=epics_summary,
        stories=stories_summary,
        tasks=tasks_summary,
        architecture=arch_summary,
        change_request=message,
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        impact_level = result.get("impact_level", ImpactLevel.TEXT_ONLY)
        confidence = result.get("confidence", 0.5)
        affected_items = result.get("affected_items", [])
        reasoning = result.get("reasoning", "")
        cascade_phases = result.get("cascade_phases", [])
        suggested_action = result.get("suggested_action", "")

        logger.info(
            "impact_analysis_complete",
            impact_level=impact_level,
            confidence=confidence,
            affected_count=len(affected_items),
        )

        # Determine restart phase
        restart_phase = IMPACT_TO_PHASE.get(impact_level)

        # Build response for user
        impact_emoji = {
            ImpactLevel.ARCHITECTURE: "🏗️",
            ImpactLevel.SCOPE: "📦",
            ImpactLevel.STORY: "📝",
            ImpactLevel.TASK: "🔧",
            ImpactLevel.ESTIMATION: "📊",
            ImpactLevel.TEXT_ONLY: "✏️",
        }

        response_lines = [
            f"{impact_emoji.get(impact_level, '📋')} *Impact Analysis*",
            f"",
            f"*Level:* {impact_level.replace('_', ' ').title()}",
            f"*Reason:* {reasoning}",
        ]

        if affected_items:
            response_lines.append(f"*Affected:* {', '.join(str(i) for i in affected_items)}")

        if cascade_phases:
            response_lines.append(f"*Phases to re-run:* {' → '.join(cascade_phases)}")

        if suggested_action:
            response_lines.append(f"\n_{suggested_action}_")

        return {
            "impact_level": impact_level,
            "impact_confidence": confidence,
            "affected_items": affected_items,
            "cascade_phases": cascade_phases,
            "restart_phase": restart_phase,
            "response": "\n".join(response_lines),
            "should_respond": True,
        }

    except Exception as e:
        logger.error("impact_analysis_failed", error=str(e))
        return {
            "impact_level": ImpactLevel.TEXT_ONLY,
            "response": f"Could not analyze impact: {str(e)}. Treating as minor change.",
            "error": str(e),
        }


# =============================================================================
# Response Generation Node
# =============================================================================

RESPONSE_PROMPT = """You are a requirements engineering assistant responding to a user.
{persona_knowledge}

## User's Message
{user_message}

## Current Context
- Intent: {intent}
- Active Persona: {active_persona}
- Draft requirement: {draft}
- All drafts (if complex): {all_drafts}
- Conflicts detected: {conflicts}
- Jira Issue created: {jira_key}
- Error (if any): {error}

## Response Guidelines by Intent

**If intent is "question":**
- DIRECTLY answer the user's question using your expertise
- If asking about a draft/requirement, provide specific feedback
- If asking for architecture advice, give concrete recommendations
- Be helpful and substantive, not generic

**If intent is "requirement" with conflicts:**
- Explain the conflicts found
- Suggest how to resolve them

**If intent is "general":**
- Engage in helpful project-related conversation
- Provide relevant context or suggestions

**If there's an error:**
- Explain what went wrong clearly
- Suggest next steps

## Format
- Be concise but substantive
- Use markdown for clarity when needed
- If you created multiple requirements, summarize them
- NEVER output meta-responses like "here are some options" - just respond directly
"""


async def response_node(state: RequirementState) -> dict:
    """
    Generate the final response to send to the user.

    Now includes:
    - Persona knowledge for specialized responses
    - User's original message for context
    - Better handling of different intent types
    """
    print(f"[DEBUG] response_node called, intent={state.get('intent')}, draft={bool(state.get('draft'))}")

    # If response already set (e.g., by rejection), use it
    if state.get("response"):
        print(f"[DEBUG] response_node: response already set")
        return {}

    logger.info("generating_response", channel_id=state.get("channel_id"))

    llm = get_llm_for_state(state, temperature=0.5)

    # Get persona knowledge
    persona_name = state.get("active_persona")
    persona_knowledge = get_persona_knowledge(persona_name, state)

    # Format draft info
    draft_str = "None"
    if state.get("draft"):
        draft = state["draft"]
        draft_str = f"Title: {draft.get('title')}\nType: {draft.get('issue_type')}\nDescription: {draft.get('description', '')[:200]}"

    # Format all drafts if complex
    all_drafts_str = "None"
    if state.get("all_drafts"):
        all_drafts = state["all_drafts"]
        all_drafts_str = "\n".join(
            f"- [{d.get('issue_type')}] {d.get('title')}"
            for d in all_drafts
        )

    # Format conflicts
    conflicts_str = "None"
    if state.get("conflicts"):
        conflicts_str = "\n".join(
            f"- {c.get('conflict_type')}: {c.get('description')}"
            for c in state["conflicts"]
        )

    prompt = ChatPromptTemplate.from_template(RESPONSE_PROMPT)
    messages = prompt.format_messages(
        user_message=state.get("message", ""),
        intent=state.get("intent", "unknown"),
        active_persona=persona_name or "Main Bot",
        draft=draft_str,
        all_drafts=all_drafts_str,
        conflicts=conflicts_str,
        jira_key=state.get("jira_issue_key") or "None",
        error=state.get("error") or "None",
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        return {"response": response.content}

    except Exception as e:
        logger.error("response_generation_failed", error=str(e))
        return {"response": "I've processed your request. Let me know if you need anything else."}


# =============================================================================
# No Response Node
# =============================================================================

async def no_response_node(state: RequirementState) -> dict:
    """
    Terminal node when bot decides not to respond.

    This is used when confidence is below threshold and bot stays silent.
    """
    logger.info(
        "no_response",
        channel_id=state.get("channel_id"),
        confidence=state.get("intent_confidence"),
    )
    return {"should_respond": False, "response": None}

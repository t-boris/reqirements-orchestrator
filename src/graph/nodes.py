"""
LangGraph Nodes - All node functions for the requirements workflow.

Each node is a pure function that takes state and returns state updates.
Nodes are composed into the graph in graph.py.
"""

import json
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from src.config.settings import get_settings
from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
)
from src.slack.channel_config_store import get_model_provider

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
    config = state.get("channel_config", {})
    model_name = config.get("default_model", settings.default_llm_model)
    provider = get_model_provider(model_name)

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
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

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
            facts.append({
                "content": result.message.content if result.message else "",
                "relevance": result.score,
                "timestamp": result.message.created_at if result.message else None,
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
    """
    # Skip if no draft to check
    if not state.get("draft"):
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
        return {"conflicts": []}

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

        return {"conflicts": conflicts}

    except Exception as e:
        logger.error("conflict_detection_failed", error=str(e))
        return {"conflicts": [], "error": f"Conflict detection failed: {str(e)}"}


# =============================================================================
# Draft Node
# =============================================================================

DRAFT_REQUIREMENT_PROMPT = """You are a requirements engineering expert. Create a well-structured requirement from the user's input.

Use this format for user stories:
"As a [user type], I want [goal], so that [benefit]."

Include clear acceptance criteria that are:
- Specific and measurable
- Testable by QA
- Unambiguous

User message: {message}

Context from conversation:
{context}

Current goal/scope: {goal}

Respond in JSON format:
{{
    "title": "<concise title>",
    "description": "<full description with user story format if applicable>",
    "issue_type": "<Epic|Story|Task|Bug>",
    "acceptance_criteria": ["<criterion 1>", "<criterion 2>", ...],
    "priority": "<low|medium|high|critical>",
    "labels": ["<label1>", "<label2>"],
    "reasoning": "<why this structure was chosen>"
}}
"""


async def draft_node(state: RequirementState) -> dict:
    """
    Create or refine a requirement draft based on user input.

    Uses LLM to structure the requirement properly.
    """
    logger.info(
        "drafting_requirement",
        channel_id=state.get("channel_id"),
        iteration=state.get("iteration_count", 0),
    )

    llm = get_llm_for_state(state, temperature=0.3)

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
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        draft = {
            "title": result.get("title", ""),
            "description": result.get("description", ""),
            "issue_type": result.get("issue_type", "Story"),
            "acceptance_criteria": result.get("acceptance_criteria", []),
            "priority": result.get("priority", "medium"),
            "labels": result.get("labels", []),
        }

        logger.info("draft_created", title=draft["title"], issue_type=draft["issue_type"])

        return {
            "draft": draft,
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
    Create or update a Jira issue via MCP.

    Uses the MCP client to interact with Jira.
    """
    from src.jira.mcp_client import get_jira_client

    action = state.get("jira_action")
    draft = state.get("draft")

    if not action or not draft:
        return {}

    logger.info(
        "writing_to_jira",
        channel_id=state.get("channel_id"),
        action=action,
        title=draft.get("title"),
    )

    try:
        jira = await get_jira_client()

        # Get project key from channel config
        config = state.get("channel_config", {})
        project_key = config.get("jira_project_key", "MARO")

        if action == "create":
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
            }

        elif action == "update":
            issue_key = state.get("jira_issue_key")
            if issue_key:
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
# Response Generation Node
# =============================================================================

RESPONSE_PROMPT = """Generate a helpful response for the user based on the current state.

Intent: {intent}
Draft: {draft}
Conflicts: {conflicts}
Jira Issue: {jira_key}
Error: {error}

Generate a concise, friendly response that:
1. Acknowledges what was done
2. Highlights any important information
3. Asks for clarification if needed

Keep it brief and professional.
"""


async def response_node(state: RequirementState) -> dict:
    """
    Generate the final response to send to the user.

    Synthesizes all processing results into a user-friendly message.
    """
    # If response already set (e.g., by rejection), use it
    if state.get("response"):
        return {}

    logger.info("generating_response", channel_id=state.get("channel_id"))

    llm = get_llm_for_state(state, temperature=0.5)

    draft_str = ""
    if state.get("draft"):
        draft = state["draft"]
        draft_str = f"Title: {draft.get('title')}\nType: {draft.get('issue_type')}"

    conflicts_str = ""
    if state.get("conflicts"):
        conflicts_str = "\n".join(
            f"- {c.get('conflict_type')}: {c.get('description')}"
            for c in state["conflicts"]
        )

    prompt = ChatPromptTemplate.from_template(RESPONSE_PROMPT)
    messages = prompt.format_messages(
        intent=state.get("intent", "unknown"),
        draft=draft_str or "None",
        conflicts=conflicts_str or "None",
        jira_key=state.get("jira_issue_key") or "None",
        error=state.get("error") or "None",
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

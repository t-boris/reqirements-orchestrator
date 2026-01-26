"""Review continuation node - synthesize user answers and update recommendations.

When user provides answers to open questions from a review, this node:
1. Maps answers to original questions
2. Updates architecture recommendations (via PATCH mode by default)
3. Asks user to proceed with decision

Patch mode outputs only changes, not full regeneration.
Full synthesis is triggered by "Show full architecture" button.

Phase 37: Unified Question Engine integration
- Uses FreeformProvider when user asks for questions
- Generates structured questions via Question Engine
"""
import logging
import re
from typing import Any

from src.questions.freeform_provider import FreeformProvider
from src.schemas.question import QuestionTask
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


def _extract_questions_from_response(response: str) -> list[str]:
    """Extract numbered questions from LLM response.

    Looks for patterns like "1. Question?" or "1) Question?" or "**1. Question**"
    and extracts the question text.

    Returns:
        List of question strings (empty if no questions found)
    """
    import re
    questions = []
    # Match numbered question patterns - with or without markdown bold
    # Patterns: "1. Question?", "1) Question?", "**1. Question?**", "1. **Question?**"
    numbered_pattern = r'^\s*\**\d+[\.\)]\**\s*\**(.+?\?)\**\s*$'

    for line in response.split('\n'):
        line = line.strip()
        match = re.match(numbered_pattern, line)
        if match:
            question_text = match.group(1).strip()
            # Clean up any remaining markdown
            question_text = re.sub(r'\*+', '', question_text).strip()
            if question_text:
                questions.append(question_text)

    return questions


async def _generate_options_for_question(
    question_text: str,
    topic: str,
) -> list[dict]:
    """Generate answer options for a specific question using LLM.

    Args:
        question_text: The question to generate options for
        topic: The discussion topic for context

    Returns:
        List of option dicts with option_id, label, value, description
    """
    from src.llm import get_llm

    prompt = f'''Generate 2-4 answer options for this question about {topic}.

Question: {question_text}

Return a JSON array of options. Each option should have:
- "label": Short button text (max 30 chars)
- "value": The answer value to record
- "description": Brief explanation (optional)
- "is_recommended": true for the most common/recommended choice (only one)

Example format:
[
  {{"label": "Option A", "value": "option_a_detail", "description": "Why this choice", "is_recommended": true}},
  {{"label": "Option B", "value": "option_b_detail", "description": "Why this choice", "is_recommended": false}}
]

Return ONLY the JSON array, no other text.'''

    llm = get_llm(max_tokens=1024)
    try:
        response = await llm.chat(prompt)
        # Parse JSON from response
        import json
        # Try to extract JSON array from response
        response = response.strip()
        if response.startswith('```'):
            # Remove markdown code block
            response = re.sub(r'^```(?:json)?\n?', '', response)
            response = re.sub(r'\n?```$', '', response)

        options = json.loads(response)
        # Add option_id to each
        for i, opt in enumerate(options):
            opt["option_id"] = f"opt_{i}"
        return options
    except Exception as e:
        logger.warning(f"Failed to generate options for question: {e}")
        return []


async def _generate_review_questions(
    review_context: dict,
    num_questions: int = 3,
) -> list[QuestionTask]:
    """Generate review questions using FreeformProvider.

    Args:
        review_context: Current review context
        num_questions: Number of questions to generate

    Returns:
        List of QuestionTask objects (with options if LLM generated them)
    """
    provider = FreeformProvider()

    # Build context for provider
    context = {
        "topic": review_context.get("topic", "Architecture discussion"),
        "assumptions": [],
        "constraints": [],
        "risks": [],
    }

    # Get previous summary to identify gaps
    previous_summary = (
        review_context.get("updated_recommendation") or
        review_context.get("review_summary", "")
    )

    # Determine what's missing
    missing_fields = []
    if "assumption" not in previous_summary.lower():
        missing_fields.append("assumptions")
    if "constraint" not in previous_summary.lower():
        missing_fields.append("constraints")
    if "risk" not in previous_summary.lower():
        missing_fields.append("risks")

    if not missing_fields:
        missing_fields = ["assumptions", "constraints", "risks"]

    questions: list[QuestionTask] = []
    for i in range(num_questions):
        if not missing_fields:
            break
        task = await provider.generate_question(context, missing_fields)
        if task:
            # Assign a unique question_id if not set
            if not task.question_id:
                task.question_id = f"review_q_{i}"
            questions.append(task)
            # Rotate to next field
            missing_fields = missing_fields[1:] + missing_fields[:1]

    return questions


# Patch mode prompt - outputs only changes (4 sections, max 12 bullets)
PATCH_REVIEW_PROMPT = '''Based on the user's answers, generate a PATCH update to the architecture review.

Previous review (version {version}):
{previous_summary}

User's answers:
{user_answers}

Generate a PATCH with exactly these 4 sections (max 12 bullets total):

## New Decisions
[Decisions made based on user's answers - max 3 bullets]

## New Risks
[New risks identified based on answers - max 3 bullets, or "None identified"]

## New Open Questions
[Any new questions that arose - max 3 bullets, or "None"]

## Changes Since v{version}
[What changed from previous version - max 3 bullets]

Keep it concise. This is a PATCH, not a full review.
If user wants full synthesis, they can click "Show full architecture".

Format for Slack:
- Bold: *text* (single asterisks)
- Italic: _text_ (underscores)
- Lists: Use bullet • or dash -
- NO ### headers (use *Bold Title:* instead)
'''


# Legacy full continuation prompt (still used for explicit full synthesis requests)
REVIEW_CONTINUATION_PROMPT = '''You are continuing an architecture discussion.

Original review topic: {topic}

Your previous analysis:
{original_review}

FULL CONVERSATION HISTORY:
{conversation_history}

Based on the FULL conversation above (not just the last message), provide a complete updated architecture incorporating all the information provided:

1. Acknowledge the user's answers and choices
2. Present the COMPLETE updated architecture with all sections:
   - High-level approach
   - Key components and their interactions
   - Technical decisions based on user's answers
   - Implementation considerations
   - Risks and mitigations
   - Open questions (if any remain)

Format for Slack:
- Bold: *text*
- Section headers: *Header:*
- Lists: Use bullet •
- Keep it comprehensive but focused on what's relevant given their answers
- If they asked to "show updated architecture", provide the FULL updated design, not just a summary
'''


# Single prompt that handles both intent detection and response generation
SMART_CONTINUATION_PROMPT = '''You are continuing an architecture discussion as {persona}.

Topic: {topic}

Previous architecture review:
{previous_summary}

User's latest message:
{user_message}

First, determine what the user wants:
- If they're asking for a FINAL/COMPLETE/FULL architecture summary, provide a comprehensive document
- If they're providing answers, feedback, or incremental input, provide a focused update
- If they're asking you to ASK THEM questions (e.g., "continue with your open questions", "ask me the questions"), list the open questions as a numbered list for them to answer

For FULL SYNTHESIS (user wants complete summary):
Provide a complete, detailed architecture document. Be thorough and comprehensive - cover everything discussed. Include:
1. High-level approach
2. Key components and interactions
3. Technical decisions made (with rationale)
4. Implementation considerations
5. Risks and mitigations
6. Remaining open questions (if any)

For ASK QUESTIONS (user wants YOU to ask THEM):
Key signals: "continue with questions", "ask me", "what questions", "your open questions", "ask the open questions"
When user explicitly asks you to ASK them questions:
- List 2-4 specific, numbered questions they need to answer
- Focus on the most critical open questions from the previous review
- Make questions clear and actionable
- DO NOT answer the questions yourself - just list them for the user to answer
Example response format:
"Great, here are the key questions we need to resolve:
1. [First question]?
2. [Second question]?
3. [Third question]?
Please answer any or all of these."

For INCREMENTAL UPDATE (user providing answers/feedback):
Focus on what's new or changed:
- New decisions based on user's input
- New risks identified
- New open questions (if any)
- What changed from previous version

Format for Slack:
- Bold: *text* (single asterisks)
- Lists: Use bullet • or dash -
- NO ### headers (use *Bold Title:* instead)

Do not artificially limit your response. Provide as much detail as needed for a complete answer.
'''


async def review_continuation_node(state: AgentState) -> dict[str, Any]:
    """Continue review conversation after user provides answers.

    Uses PATCH mode by default for efficiency - outputs only changes.
    Full synthesis available via "Show full architecture" button.

    Respects freeze semantics (Phase 20):
    - If review_context is None (frozen), don't continue
    - If review_context.state is POSTED or APPROVED, don't continue

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result and updated review_context
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm
    from src.schemas.state import ReviewState

    # Don't continue if review is frozen or already posted
    review_context = state.get("review_context")
    if not review_context:
        logger.info("No review context - cannot continue (may be frozen)")
        return {
            "decision_result": {
                "action": "error",
                "message": "No active review to continue",
            }
        }

    review_state = review_context.get("state")
    if review_state in (ReviewState.POSTED, ReviewState.APPROVED, "POSTED", "APPROVED"):
        logger.info(f"Review already {review_state} - not continuing")
        return {
            "decision_result": {
                "action": "error",
                "message": "Review already completed",
            }
        }

    review_artifact = state.get("review_artifact", {})

    # Phase 43 fix: Check if this is a synthesis trigger (all questions answered)
    all_questions_answered = review_context.get("all_questions_answered", False)
    qa_summary = review_context.get("qa_summary", "")

    # Get latest human message as user's answers
    messages = state.get("messages", [])
    user_answers = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_answers = msg.content
            break

    # If synthesis trigger, use the accumulated Q&A summary instead of raw message
    if all_questions_answered and qa_summary:
        user_answers = f"All questions have been answered:\n\n{qa_summary}"
        logger.info("Review synthesis triggered with accumulated Q&A")

    # Get review context fields
    topic = review_context.get("topic", "Architecture discussion")
    persona = review_context.get("persona", "Architect")

    # Calculate version number for patch tracking
    # Use review_artifact.version if exists, else review_context.version, else start at 1
    current_version = (
        review_artifact.get("version", 0) or
        review_context.get("version", 0) or
        0
    ) + 1

    # Get previous summary
    previous_summary = (
        review_context.get("updated_recommendation") or
        review_context.get("review_summary", "")
    )

    # LLM decides what to do based on user message (no pattern matching)
    prompt = SMART_CONTINUATION_PROMPT.format(
        persona=persona,
        topic=topic,
        previous_summary=previous_summary,
        user_message=user_answers,
        version=current_version - 1,
    )

    llm = get_llm(max_tokens=8192)  # Increased for longer responses
    try:
        response_content = await llm.chat(prompt)

        logger.info(
            f"Review continuation generated: {len(response_content)} chars",
            extra={
                "topic": topic,
                "persona": persona,
                "version": current_version,
                "response_length": len(response_content),
            },
        )

        # Update review_context with version tracking
        updated_context = {
            **review_context,
            "version": current_version,
            "answers_received": True,
            "updated_recommendation": response_content,
        }

        # Limit question rounds to prevent infinite loops
        question_round = review_context.get("question_round", 0) + 1
        max_question_rounds = 5

        # Phase 43 fix: If this is a synthesis (all questions answered),
        # do NOT extract more questions - this is the final response with buttons
        if all_questions_answered:
            logger.info("Synthesis complete - returning final response with buttons")
            # Clear the synthesis flags so next interaction works normally
            updated_context["all_questions_answered"] = False
            updated_context["qa_summary"] = None
            updated_context["pending_questions"] = []
            updated_context["answers"] = {}

            return {
                "decision_result": {
                    "action": "review_continuation",
                    "message": response_content,
                    "persona": persona,
                    "topic": topic,
                    "version": current_version,
                    "is_synthesis": True,  # Tells dispatch to show buttons
                },
                "review_context": updated_context,
            }

        # Extract questions from LLM response and generate buttons for them
        extracted_questions = _extract_questions_from_response(response_content)
        if extracted_questions and question_round <= max_question_rounds:
            # Generate options for each question
            questions_data = []
            for i, question_text in enumerate(extracted_questions[:4]):  # Max 4 questions
                options = await _generate_options_for_question(question_text, topic)
                q_data = {
                    "question_id": f"review_q_{i}",
                    "question_text": question_text,
                    "question_type": "ask_user",
                    "target_field": f"answer_{i}",
                    "options": options if options else None,
                }
                questions_data.append(q_data)

            if questions_data:
                return {
                    "decision_result": {
                        "action": "review_continuation",
                        "message": response_content,
                        "persona": persona,
                        "topic": topic,
                        "version": current_version,
                        "is_questions": True,
                        "questions_data": questions_data,
                    },
                    "review_context": {
                        **updated_context,
                        "question_round": question_round,
                        "awaiting_answers": True,
                    },
                }

        return {
            "decision_result": {
                "action": "review_continuation",
                "message": response_content,
                "persona": persona,
                "topic": topic,
                "version": current_version,
                "is_patch": True,
            },
            "review_context": updated_context,
        }

    except Exception as e:
        logger.error(f"Review continuation LLM call failed: {e}")
        return {
            "decision_result": {
                "action": "review_continuation",
                "message": f"I encountered an error processing your answers: {str(e)}",
            }
        }

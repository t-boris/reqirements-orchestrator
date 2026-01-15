"""Answer matcher - semantic matching of user responses to questions.

Uses LLM to correlate parts of user response with questions asked.
"""
import json
import logging
from typing import Optional
from pydantic import BaseModel, Field

from src.llm import get_llm

logger = logging.getLogger(__name__)


class AnswerMatch(BaseModel):
    """Match between a question and extracted answer."""
    question: str
    question_index: int  # 1-based index in original questions list
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)  # 0.0 to 1.0
    source_text: str = ""  # Original text that contained the answer


class MatchResult(BaseModel):
    """Result of matching user response to questions."""
    matches: list[AnswerMatch] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(default_factory=list)
    all_answered: bool = False


MATCH_PROMPT = '''You are matching a user's response to questions that were asked.

Questions asked (numbered):
{questions}

User's response:
{response}

For each question, determine if the response contains an answer. Return a JSON object with:
- "matches": list of matched answers, each with:
  - "question_index": 1-based question number
  - "answer": the extracted answer (brief, just the answer)
  - "confidence": 0.0 to 1.0 (how confident you are this answers the question)
  - "source_text": the part of the response that contains the answer
- "unanswered": list of 1-based indices for questions not answered

Rules:
- Only extract answers that are clearly stated in the response
- Do not invent or assume answers
- Confidence should be high (0.8+) only if the answer is explicit
- For Yes/No questions, "yes", "sure", "okay" = "yes"; "no", "not", "nope" = "no"
- If response says "I don't know" or similar, mark as unanswered
- IMPORTANT: If user says "propose yours", "suggest some", "you decide", "come up with", or similar delegation phrases, treat this as: answer="[GENERATE]", confidence=0.9. This signals the assistant should generate content autonomously.

JSON response:'''


async def match_answers(
    questions: list[str],
    user_response: str,
    expected_fields: Optional[list[str]] = None,
) -> MatchResult:
    """Match user response to questions using semantic analysis.

    Args:
        questions: List of questions that were asked
        user_response: User's message/response
        expected_fields: Optional field names to help with matching

    Returns:
        MatchResult with matches and unanswered questions
    """
    if not questions or not user_response.strip():
        return MatchResult(
            unanswered_questions=questions,
            all_answered=False,
        )

    # Format questions with numbers
    numbered_questions = "\n".join(
        f"{i}. {q}" for i, q in enumerate(questions, 1)
    )

    prompt = MATCH_PROMPT.format(
        questions=numbered_questions,
        response=user_response,
    )

    try:
        llm = get_llm()
        result = await llm.chat(prompt)
        response_text = result.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        parsed = json.loads(response_text)

        # Build matches
        matches = []
        matched_indices = set()

        for match_data in parsed.get("matches", []):
            idx = match_data.get("question_index", 0)
            if 1 <= idx <= len(questions):
                matched_indices.add(idx)
                matches.append(AnswerMatch(
                    question=questions[idx - 1],
                    question_index=idx,
                    answer=match_data.get("answer", ""),
                    confidence=float(match_data.get("confidence", 0.5)),
                    source_text=match_data.get("source_text", ""),
                ))

        # Determine unanswered questions
        unanswered_indices = parsed.get("unanswered", [])
        unanswered = [
            questions[idx - 1]
            for idx in unanswered_indices
            if 1 <= idx <= len(questions)
        ]

        # Add any questions not mentioned at all
        for i, q in enumerate(questions, 1):
            if i not in matched_indices and q not in unanswered:
                unanswered.append(q)

        logger.info(
            "Matched answers",
            extra={
                "total_questions": len(questions),
                "matched": len(matches),
                "unanswered": len(unanswered),
            }
        )

        return MatchResult(
            matches=matches,
            unanswered_questions=unanswered,
            all_answered=len(unanswered) == 0,
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse match response: {e}")
        return MatchResult(
            unanswered_questions=questions,
            all_answered=False,
        )
    except Exception as e:
        logger.error(f"Answer matching failed: {e}")
        return MatchResult(
            unanswered_questions=questions,
            all_answered=False,
        )

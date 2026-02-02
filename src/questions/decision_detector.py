"""DecisionDetector - LLM-based detection of implicit decisions in user responses.

Phase 45: Structured Discussion Flow

Detects when user answers contain decisions (choices or commitments) that should
be captured as CapturedDecision for later formal creation as Decision entities.

Design Rule: Only LLM can detect intents and decisions - no regex patterns.
This ensures semantic understanding rather than brittle string matching.

Example:
    User answers "1 - long-form Slack message" to a question about format.
    LLM detects this as an ARCH decision about communication patterns.
"""
import json
import logging
from typing import Optional

from src.llm.client import get_llm
from src.schemas.decision import DecisionType
from src.schemas.discussion_state import CapturedDecision
from src.schemas.question import QuestionTask

logger = logging.getLogger(__name__)


DECISION_DETECTION_PROMPT = """Analyze this user response in context of the question asked.

QUESTION: {question_text}
USER RESPONSE: {message}

Determine if the user's response contains a DECISION (a choice or commitment).

A DECISION is when the user:
- Makes a choice between options (explicit or implicit)
- Commits to an approach, method, or solution
- Selects a preference that affects implementation
- Confirms a constraint or requirement

NOT a decision:
- Asking for more information
- Expressing uncertainty ("I think maybe...")
- Deferring ("Let's discuss later")
- Providing information without making a choice
- Asking clarifying questions

If the response contains a decision, extract:
1. The decision itself (what was chosen/committed to)
2. The decision type:
   - ARCH: Architecture/technical implementation choice
   - SCOPE: What's included/excluded
   - CONSTRAINT: Limitation or requirement
   - PRIORITY: Ordering or importance
   - STRUCTURE: Organization or decomposition
   - PROCESS: How work will be done

Respond with JSON:
{{
  "contains_decision": true/false,
  "decision_text": "What was decided" or null,
  "decision_type": "ARCH|SCOPE|CONSTRAINT|PRIORITY|STRUCTURE|PROCESS" or null,
  "confidence": 0.0-1.0,
  "rationale": "Why this is/isn't a decision"
}}

Examples:
- "1 - long-form Slack message" → decision (chose option 1)
- "Let's go with PostgreSQL" → decision (chose PostgreSQL)
- "We need at least 99.9% uptime" → decision (constraint)
- "What do you mean by that?" → NOT a decision (clarification)
- "I'm not sure yet" → NOT a decision (uncertainty)
"""


class DecisionDetector:
    """Detect implicit decisions using LLM classification.

    RULE: Only LLM can detect intents and decisions - no regex patterns.

    This detector is used during structured discussions to capture
    decisions made in user responses, enabling mid-conversation
    decision tracking.
    """

    def __init__(self, temperature: float = 0.2, max_tokens: int = 500):
        """Initialize the decision detector.

        Args:
            temperature: LLM temperature for classification (low for consistency)
            max_tokens: Maximum tokens in LLM response
        """
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def detect(
        self,
        message: str,
        question_context: Optional[QuestionTask] = None,
    ) -> Optional[CapturedDecision]:
        """Use LLM to check if message contains a decision.

        Args:
            message: User's response message
            question_context: The question that prompted this response (if any)

        Returns:
            CapturedDecision if a decision was detected with sufficient confidence,
            None otherwise.
        """
        if not message or not message.strip():
            return None

        question_text = (
            question_context.question_text if question_context else "N/A (unprompted message)"
        )

        prompt = DECISION_DETECTION_PROMPT.format(
            question_text=question_text,
            message=message,
        )

        try:
            llm = get_llm(temperature=self.temperature, max_tokens=self.max_tokens)
            response = await llm.chat(prompt)

            result = self._parse_response(response)

            if not result:
                logger.warning("Failed to parse decision detection response")
                return None

            if not result.get("contains_decision", False):
                logger.debug(
                    "No decision detected",
                    extra={
                        "message": message[:100],
                        "rationale": result.get("rationale", ""),
                    },
                )
                return None

            confidence = result.get("confidence", 0.0)
            if confidence < 0.7:
                logger.debug(
                    "Decision detected but low confidence",
                    extra={
                        "confidence": confidence,
                        "decision_text": result.get("decision_text", ""),
                    },
                )
                return None

            decision_type_str = result.get("decision_type")
            if not decision_type_str:
                logger.warning("Decision detected but no type specified")
                decision_type_str = "ARCH"  # Default to ARCH

            try:
                decision_type = DecisionType(decision_type_str.lower())
            except ValueError:
                logger.warning(f"Invalid decision type: {decision_type_str}, defaulting to ARCH")
                decision_type = DecisionType.ARCH

            captured = CapturedDecision(
                decision_text=result.get("decision_text", message),
                decision_type=decision_type,
                confidence=confidence,
                source_question=question_text if question_context else None,
                rationale_hints=[result.get("rationale", "")],
            )

            logger.info(
                "Decision captured",
                extra={
                    "decision_text": captured.decision_text[:100],
                    "decision_type": captured.decision_type.value,
                    "confidence": captured.confidence,
                },
            )

            return captured

        except Exception as e:
            logger.error(f"Decision detection failed: {e}")
            return None

    def _parse_response(self, response: str) -> Optional[dict]:
        """Parse LLM JSON response.

        Handles markdown code blocks if present.

        Args:
            response: Raw LLM response

        Returns:
            Parsed dict or None if parsing fails
        """
        if not response:
            return None

        response_text = response.strip()

        # Handle markdown code block wrapper
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first line (```json) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            response_text = "\n".join(lines)

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}, response: {response_text[:200]}")
            return None


async def detect_decision(
    message: str,
    question_context: Optional[QuestionTask] = None,
) -> Optional[CapturedDecision]:
    """Convenience function for decision detection.

    Args:
        message: User's response message
        question_context: The question that prompted this response

    Returns:
        CapturedDecision if detected, None otherwise
    """
    detector = DecisionDetector()
    return await detector.detect(message, question_context)

"""DiscussionProvider - Extract and structure questions from discussion responses.

Phase 45: Structured Discussion Flow

Extracts open questions from LLM-generated discussion responses (like persona
responses with numbered questions) and converts them to structured QuestionTask
objects with button options where applicable.

Example input (from Technical Architect persona):
    "5. Remaining Open Questions
    1. Note Delivery Format: When a student clicks a nudge, should the note
       be delivered as a long-form Slack message or a signed URL to a PDF?
    2. Interactive Elements: Do you want buttons for quick actions (Read Now,
       Remind me in 1 hour) or simple text reminders?"

Output: List of QuestionTask objects with button options.
"""
import json
import logging
import re
from typing import Any, Optional
import uuid

from src.llm.client import get_llm
from src.schemas.question import QuestionOption, QuestionTask, QuestionType

logger = logging.getLogger(__name__)


QUESTION_EXTRACTION_PROMPT = """Extract structured questions from this discussion response.

DISCUSSION RESPONSE:
{response}

Find any questions being asked to the user. For each question, extract:
1. The question text
2. Whether it has explicit options (choices)
3. The options if present

Return JSON array of questions:
[
  {{
    "question_text": "The full question being asked",
    "has_options": true/false,
    "options": ["option1", "option2", ...] or null,
    "topic": "short topic label (e.g., 'delivery_format', 'interactive_elements')"
  }},
  ...
]

Guidelines:
- Extract ONLY questions directed at the user
- If options are implied (A or B format), extract them
- If question is open-ended (no clear options), set has_options=false
- topic should be a short snake_case identifier

Return empty array [] if no questions found.

JSON:"""


QUESTION_TO_OPTIONS_PROMPT = """Convert this question into button options. Output ONLY valid JSON, no other text.

QUESTION: {question}

Generate 2-4 clear options as buttons. Keep labels SHORT (under 25 chars).

If the question cannot be answered with buttons (needs free text), output: {{"options": null}}

Otherwise output:
{{"options": [{{"label": "Option 1", "value": "option_1"}}, {{"label": "Option 2", "value": "option_2"}}]}}

JSON only:"""


class DiscussionProvider:
    """Generates structured questions for architectural discussions.

    Parses LLM responses that contain embedded questions (often from
    persona-driven discussions) and converts them to QuestionTask format
    with button options where applicable.
    """

    def __init__(self, temperature: float = 0.2, max_tokens: int = 1000):
        """Initialize the discussion provider.

        Args:
            temperature: LLM temperature for extraction (low for consistency)
            max_tokens: Maximum tokens in LLM response
        """
        self.temperature = temperature
        self.max_tokens = max_tokens

    def get_target_type(self) -> str:
        """Return target state type."""
        return "discussion"

    async def extract_open_questions(
        self,
        llm_response: str,
        context: Optional[dict[str, Any]] = None,
    ) -> list[QuestionTask]:
        """Parse LLM response to extract questions with options.

        Takes a free-form discussion response (like from Technical Architect
        persona) and extracts embedded questions, converting them to
        structured QuestionTask format.

        Args:
            llm_response: The full LLM response text
            context: Optional context for better option generation

        Returns:
            List of QuestionTask objects, empty if no questions found
        """
        if not llm_response or not llm_response.strip():
            return []

        # Check if response likely contains questions
        if not self._likely_has_questions(llm_response):
            return []

        prompt = QUESTION_EXTRACTION_PROMPT.format(response=llm_response)

        try:
            llm = get_llm(temperature=self.temperature, max_tokens=self.max_tokens)
            response = await llm.chat(prompt)

            questions_data = self._parse_response(response)

            if not questions_data:
                return []

            # Convert each extracted question to QuestionTask
            tasks = []
            for q_data in questions_data:
                task = await self._create_question_task(q_data, context)
                if task:
                    tasks.append(task)

            logger.info(
                f"Extracted {len(tasks)} questions from discussion response",
                extra={"question_count": len(tasks)},
            )

            return tasks

        except Exception as e:
            logger.error(f"Question extraction failed: {e}")
            return []

    async def generate_options_for_question(
        self,
        question_text: str,
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[list[QuestionOption]]:
        """Generate button options for a question using LLM.

        For questions that don't have explicit options in the text,
        use LLM to generate sensible choices.

        Args:
            question_text: The question to generate options for
            context: Optional context for better option generation

        Returns:
            List of QuestionOption or None if question should be open-ended
        """
        prompt = QUESTION_TO_OPTIONS_PROMPT.format(
            question=question_text,
            context=json.dumps(context) if context else "General discussion",
        )

        try:
            llm = get_llm(temperature=self.temperature, max_tokens=500)
            response = await llm.chat(prompt)

            result = self._parse_response(response)
            if not result or not result.get("options"):
                return None

            options = []
            for i, opt in enumerate(result["options"]):
                if isinstance(opt, dict):
                    options.append(
                        QuestionOption(
                            option_id=f"opt_{i}_{uuid.uuid4().hex[:8]}",
                            label=opt.get("label", f"Option {i+1}"),
                            description=opt.get("description"),
                            value=opt.get("value", opt.get("label", f"option_{i}")),
                        )
                    )
                elif isinstance(opt, str):
                    options.append(
                        QuestionOption(
                            option_id=f"opt_{i}_{uuid.uuid4().hex[:8]}",
                            label=opt,
                            value=opt,
                        )
                    )

            return options if options else None

        except Exception as e:
            logger.error(f"Option generation failed: {e}")
            return None

    async def _create_question_task(
        self,
        question_data: dict,
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[QuestionTask]:
        """Create a QuestionTask from extracted question data.

        Args:
            question_data: Extracted question dict
            context: Optional context for option generation

        Returns:
            QuestionTask or None if creation fails
        """
        question_text = question_data.get("question_text")
        if not question_text:
            return None

        topic = question_data.get("topic", "clarification")

        # Determine options
        options = None
        has_options = question_data.get("has_options", False)
        raw_options = question_data.get("options")

        if has_options and raw_options:
            # Use extracted options
            options = [
                QuestionOption(
                    option_id=f"opt_{i}_{uuid.uuid4().hex[:8]}",
                    label=opt if isinstance(opt, str) else opt.get("label", f"Option {i+1}"),
                    value=opt if isinstance(opt, str) else opt.get("value", f"option_{i}"),
                    description=opt.get("description") if isinstance(opt, dict) else None,
                )
                for i, opt in enumerate(raw_options)
            ]
        elif not has_options:
            # Try to generate options for open-ended question
            options = await self.generate_options_for_question(question_text, context)

            # Fallback: if no options generated, try common patterns
            if not options:
                options = self._generate_fallback_options(question_text)

        # Determine question type
        question_type = (
            QuestionType.CONFIRM_SCOPE if options else QuestionType.ASK_USER
        )

        return QuestionTask(
            question_id=str(uuid.uuid4()),
            question_type=question_type,
            question_text=question_text,
            target_field=f"discussion.{topic}",
            options=options,
        )

    def _generate_fallback_options(self, question_text: str) -> Optional[list[QuestionOption]]:
        """Generate fallback options based on question patterns.

        Used when LLM option generation fails. Detects common question
        patterns and provides sensible defaults.

        Args:
            question_text: The question text

        Returns:
            List of QuestionOption or None if no pattern matches
        """
        question_lower = question_text.lower()

        # Yes/No questions
        if any(phrase in question_lower for phrase in [
            "should we", "do you want", "would you like", "is it",
            "are you", "can we", "shall we", "do we need"
        ]):
            return [
                QuestionOption(
                    option_id=f"opt_yes_{uuid.uuid4().hex[:8]}",
                    label="Yes",
                    value="yes",
                ),
                QuestionOption(
                    option_id=f"opt_no_{uuid.uuid4().hex[:8]}",
                    label="No",
                    value="no",
                ),
                QuestionOption(
                    option_id=f"opt_discuss_{uuid.uuid4().hex[:8]}",
                    label="Let's discuss",
                    value="discuss",
                ),
            ]

        # "Or" questions (A or B)
        if " or " in question_lower:
            # Try to extract options from "X or Y" pattern
            import re
            match = re.search(r'(?:should|do|would|is|are).*?(\w[\w\s]*?)\s+or\s+(\w[\w\s]*?)(?:\?|$)', question_lower)
            if match:
                opt_a = match.group(1).strip().title()[:25]
                opt_b = match.group(2).strip().title()[:25]
                return [
                    QuestionOption(
                        option_id=f"opt_a_{uuid.uuid4().hex[:8]}",
                        label=opt_a,
                        value=opt_a.lower().replace(" ", "_"),
                    ),
                    QuestionOption(
                        option_id=f"opt_b_{uuid.uuid4().hex[:8]}",
                        label=opt_b,
                        value=opt_b.lower().replace(" ", "_"),
                    ),
                ]

        # "How many" questions - provide range options
        if "how many" in question_lower:
            return [
                QuestionOption(option_id=f"opt_few_{uuid.uuid4().hex[:8]}", label="A few (1-10)", value="few"),
                QuestionOption(option_id=f"opt_dozens_{uuid.uuid4().hex[:8]}", label="Dozens (10-100)", value="dozens"),
                QuestionOption(option_id=f"opt_hundreds_{uuid.uuid4().hex[:8]}", label="Hundreds (100+)", value="hundreds"),
                QuestionOption(option_id=f"opt_thousands_{uuid.uuid4().hex[:8]}", label="Thousands (1000+)", value="thousands"),
            ]

        return None

    def _likely_has_questions(self, text: str) -> bool:
        """Quick check if text likely contains questions.

        Args:
            text: Text to check

        Returns:
            True if text likely contains questions
        """
        # Check for question marks
        if "?" not in text:
            return False

        # Check for question-indicating phrases
        question_indicators = [
            "question",
            "how would",
            "what should",
            "should we",
            "do you want",
            "would you like",
            "which option",
            "what is your",
        ]

        text_lower = text.lower()
        return any(indicator in text_lower for indicator in question_indicators)

    def _parse_response(self, response: str) -> Optional[Any]:
        """Parse LLM JSON response.

        Handles markdown code blocks and extracts JSON from mixed content.

        Args:
            response: Raw LLM response

        Returns:
            Parsed JSON (dict or list) or None if parsing fails
        """
        if not response:
            return None

        response_text = response.strip()

        # Handle markdown code block wrapper
        if "```" in response_text:
            # Extract content between ``` markers
            import re
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
            if match:
                response_text = match.group(1).strip()
            else:
                # Just remove ``` markers
                response_text = response_text.replace("```json", "").replace("```", "").strip()

        # Try to find JSON object or array in the response
        # Look for { or [ at the start
        json_start = -1
        for i, char in enumerate(response_text):
            if char in '{[':
                json_start = i
                break

        if json_start > 0:
            response_text = response_text[json_start:]

        # Find matching end bracket
        if response_text.startswith('{'):
            # Find last }
            last_brace = response_text.rfind('}')
            if last_brace > 0:
                response_text = response_text[:last_brace + 1]
        elif response_text.startswith('['):
            # Find last ]
            last_bracket = response_text.rfind(']')
            if last_bracket > 0:
                response_text = response_text[:last_bracket + 1]

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}, response: {response_text[:200]}")
            return None

    def extract_non_question_text(self, llm_response: str) -> str:
        """Extract the non-question portion of the response.

        Used to show the analysis/discussion part separately from
        the questions.

        Args:
            llm_response: Full LLM response

        Returns:
            Text with question section removed
        """
        # Common patterns for question sections
        question_section_patterns = [
            r"\d+\.\s*(Remaining\s+)?Open\s+Questions.*",
            r"(?:Here\s+are\s+)?(?:my\s+)?questions?:.*",
            r"I\s+have\s+(?:some|a\s+few)\s+questions?:.*",
        ]

        text = llm_response

        for pattern in question_section_patterns:
            # Find and remove question section (case insensitive)
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                text = text[: match.start()].strip()
                break

        return text


async def extract_discussion_questions(
    llm_response: str,
    context: Optional[dict[str, Any]] = None,
) -> list[QuestionTask]:
    """Convenience function for question extraction.

    Args:
        llm_response: The full LLM response text
        context: Optional context for better option generation

    Returns:
        List of QuestionTask objects
    """
    provider = DiscussionProvider()
    return await provider.extract_open_questions(llm_response, context)

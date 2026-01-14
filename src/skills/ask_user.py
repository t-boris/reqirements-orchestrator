"""ask_user skill - post questions to Slack threads.

Posts formatted questions, handles Yes/No button detection,
generates question_id for tracking, and stores QuestionSet for matching.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4
from pydantic import BaseModel, Field


class QuestionStatus(str, Enum):
    """Status of a question set."""
    ASKED = "asked"
    ANSWERED = "answered"
    PARTIALLY_ANSWERED = "partially_answered"
    TIMED_OUT = "timed_out"


class QuestionSet(BaseModel):
    """Set of questions posted to a thread.

    Tracks questions asked, expected fields, and re-ask count.
    """
    question_id: str = Field(default_factory=lambda: str(uuid4()))
    questions: list[str] = Field(default_factory=list)
    expected_fields: list[str] = Field(default_factory=list)
    asked_at: datetime = Field(default_factory=datetime.utcnow)
    re_ask_count: int = 0
    message_ts: Optional[str] = None  # Slack message timestamp

    def is_yes_no_question(self, question: str) -> bool:
        """Check if question should have Yes/No buttons.

        Heuristic: Questions starting with Is/Are/Do/Does/Should/Will
        """
        prefixes = ("Is ", "Are ", "Do ", "Does ", "Should ", "Will ")
        return question.strip().startswith(prefixes)


class AskResult(BaseModel):
    """Result of asking questions."""
    message_ts: str
    question_id: str
    status: QuestionStatus = QuestionStatus.ASKED
    button_questions: list[str] = Field(default_factory=list)  # Questions with buttons


async def ask_user(
    slack_client,
    channel: str,
    thread_ts: str,
    questions: list[str],
    context: str = "",
    expected_fields: Optional[list[str]] = None,
) -> AskResult:
    """Post questions to Slack thread.

    Args:
        slack_client: Slack WebClient instance
        channel: Slack channel ID
        thread_ts: Thread timestamp (session ID)
        questions: List of questions to ask
        context: Why we're asking (context message)
        expected_fields: Optional list of expected field names

    Returns:
        AskResult with message_ts and question_id

    Behavior:
    - Posts questions as formatted message
    - Adds Yes/No buttons for questions starting with Is/Are/Do/Does/Should/Will
    - Generates question_id (UUID) for tracking
    - Returns AskResult with message_ts
    """
    question_set = QuestionSet(
        questions=questions,
        expected_fields=expected_fields or [],
    )

    # Build message blocks
    blocks = []
    button_questions = []

    # Add context if provided
    if context:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_{context}_",
            }
        })

    # Add questions
    for i, question in enumerate(questions, 1):
        if question_set.is_yes_no_question(question):
            # Question with Yes/No buttons
            button_questions.append(question)
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{i}.* {question}",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Yes",
                    },
                    "action_id": f"question_yes_{i}",
                    "value": f"{question_set.question_id}:{i}:yes",
                }
            })
            # Add No button as separate action block
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Yes",
                        },
                        "style": "primary",
                        "action_id": f"question_yes_{question_set.question_id}_{i}",
                        "value": f"{question_set.question_id}:{i}:yes",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "No",
                        },
                        "action_id": f"question_no_{question_set.question_id}_{i}",
                        "value": f"{question_set.question_id}:{i}:no",
                    },
                ]
            })
        else:
            # Plain text question (user replies in thread)
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{i}.* {question}",
                }
            })

    # Add help text
    if button_questions:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Click buttons or reply in thread to answer._",
                }
            ]
        })
    else:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Reply in thread to answer._",
                }
            ]
        })

    # Post message
    result = await slack_client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        blocks=blocks,
        text=f"I have {len(questions)} question(s) for you.",  # Fallback text
    )

    message_ts = result.get("ts", "")

    return AskResult(
        message_ts=message_ts,
        question_id=question_set.question_id,
        status=QuestionStatus.ASKED,
        button_questions=button_questions,
    )

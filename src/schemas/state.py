"""State schema for the LangGraph agent."""
from typing import Literal, Optional, Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from src.schemas.ticket import JiraTicketBase


class AgentState(TypedDict):
    """State for the Analyst Agent in LangGraph.

    This state flows through the ReAct loop:
    extraction -> validation -> decision -> (loop or complete)
    """

    # Conversation history (LangGraph manages with add_messages reducer)
    messages: Annotated[list[BaseMessage], add_messages]

    # Current ticket draft being built (EpicSchema, StorySchema, TaskSchema, or BugSchema)
    draft: Optional[JiraTicketBase]

    # Questions the agent needs to ask (populated by validation)
    missing_info: list[str]

    # Current status in the ticket lifecycle
    status: Literal["collecting", "ready_to_sync", "synced"]

    # Thread context
    thread_ts: Optional[str]  # Slack thread timestamp (session ID)
    channel_id: Optional[str]  # Slack channel

    # Metadata
    user_id: Optional[str]  # Requesting user

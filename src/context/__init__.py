"""Context building for LLM prompts.

Goal-driven context assembly with three-layer architecture:
- Layer A: Canonical State (DB) - decisions, workitems, registry
- Layer B: Working History - normalized messages with rendered blocks
- Layer C: Retrieval Add-ons - attachments, Jira snapshots

Also provides channel context management for global state.
"""
from src.context.pin_extractor import PinExtractor, PinInfo
from src.context.root_indexer import RootIndexer
from src.context.jira_linker import JiraLinker, ThreadJiraLink
from src.context.retriever import (
    ChannelContextRetriever,
    ChannelContextResult,
    RetrievalMode,
    ContextSource,
)
from src.context.spec import ContextSpec
from src.context.packet import ContextPacket

__all__ = [
    "PinExtractor",
    "PinInfo",
    "RootIndexer",
    "JiraLinker",
    "ThreadJiraLink",
    "ChannelContextRetriever",
    "ChannelContextResult",
    "RetrievalMode",
    "ContextSource",
    "ContextSpec",
    "ContextPacket",
]

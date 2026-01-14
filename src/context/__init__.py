"""Channel context extraction and processing.

This package handles extracting context from various channel sources
like pinned messages, activity patterns, and Jira data.
"""

from src.context.pin_extractor import PinExtractor, PinInfo
from src.context.jira_linker import JiraLinker, ThreadJiraLink

__all__ = ["PinExtractor", "PinInfo", "JiraLinker", "ThreadJiraLink"]

"""Pin content extraction and processing for Channel Knowledge layer."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.db.models import ChannelKnowledge

logger = logging.getLogger(__name__)


@dataclass
class PinInfo:
    """Metadata about a pinned message."""

    pin_id: str  # Usually message_ts
    message_ts: str
    text: str
    user_id: str
    pinned_at: Optional[str] = None


class PinExtractor:
    """Extracts and processes pinned messages for channel knowledge.

    Usage:
        extractor = PinExtractor(slack_client)
        pins = await extractor.fetch_pins(channel_id)
        digest = extractor.compute_digest(pins)
        if digest != stored_digest:
            knowledge = await extractor.extract_knowledge(pins)
    """

    def __init__(self, client: WebClient) -> None:
        """Initialize with Slack WebClient.

        Args:
            client: Slack WebClient for API calls.
        """
        self._client = client

    async def fetch_pins(self, channel_id: str) -> list[PinInfo]:
        """Fetch all pinned messages for a channel.

        Uses Slack's pins.list API to retrieve pinned messages.
        Filters for message pins only (not file pins).

        Args:
            channel_id: Slack channel ID.

        Returns:
            List of PinInfo objects sorted by pinned_at (oldest first).
        """
        pins: list[PinInfo] = []

        try:
            # pins.list returns all pins (no pagination needed, typically < 100)
            response = self._client.pins_list(channel=channel_id)

            items = response.get("items", [])

            for item in items:
                # Filter for message pins only (skip file pins)
                if item.get("type") != "message":
                    continue

                message = item.get("message", {})
                text = message.get("text", "")

                # Skip empty messages
                if not text.strip():
                    continue

                pin_info = PinInfo(
                    pin_id=message.get("ts", ""),
                    message_ts=message.get("ts", ""),
                    text=text,
                    user_id=message.get("user", ""),
                    pinned_at=item.get("created"),
                )
                pins.append(pin_info)

            # Sort by pinned_at (oldest first) for consistent ordering
            pins.sort(key=lambda p: p.pinned_at or "")

        except SlackApiError as e:
            logger.warning(f"Failed to fetch pins for {channel_id}: {e.response['error']}")
            # Return empty list on error - graceful degradation

        return pins

    def compute_digest(self, pins: list[PinInfo]) -> str:
        """Compute SHA256 hash of pin IDs + message_ts.

        Used for change detection - if digest unchanged, skip re-extraction.

        Args:
            pins: List of PinInfo objects.

        Returns:
            SHA256 hex digest (first 16 chars for readability).
        """
        # Sort pins by pin_id for deterministic ordering
        content = "|".join(
            f"{p.pin_id}:{p.message_ts}" for p in sorted(pins, key=lambda x: x.pin_id)
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def extract_knowledge(self, pins: list[PinInfo]) -> ChannelKnowledge:
        """Extract structured knowledge from pinned content using LLM.

        Looks for:
        - naming_convention: How to name tickets/branches
        - definition_of_done: What makes a ticket complete
        - api_format_rules: API conventions (timestamp format, etc.)
        - custom_rules: Other extracted rules

        Args:
            pins: List of PinInfo objects with text content.

        Returns:
            ChannelKnowledge with extracted rules.
        """
        if not pins:
            return ChannelKnowledge(source_pin_ids=[])

        # Combine pin texts (limit to reasonable size)
        pin_content = "\n\n---\n\n".join(
            f"[Pin {i + 1}] {p.text[:2000]}"  # Truncate long pins
            for i, p in enumerate(pins[:10])  # Max 10 pins
        )

        from src.llm.client import get_llm

        try:
            llm = get_llm()
            prompt = EXTRACTION_PROMPT.format(pin_content=pin_content)
            result = await llm.chat(prompt)

            # Parse JSON response
            import json

            # Handle potential markdown code blocks in response
            response_text = result.strip()
            if response_text.startswith("```"):
                # Remove markdown code blocks
                lines = response_text.split("\n")
                # Find first and last ``` and extract content between
                start_idx = 1 if lines[0].startswith("```") else 0
                end_idx = len(lines) - 1
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == "```":
                        end_idx = i
                        break
                response_text = "\n".join(lines[start_idx:end_idx])

            data = json.loads(response_text)

            return ChannelKnowledge(
                naming_convention=data.get("naming_convention"),
                definition_of_done=data.get("definition_of_done"),
                api_format_rules=data.get("api_format_rules"),
                custom_rules=data.get("custom_rules", {}),
                source_pin_ids=[p.pin_id for p in pins],
            )
        except Exception as e:
            logger.warning(f"Knowledge extraction failed: {e}")
            # Graceful fallback - return empty knowledge with source pins noted
            return ChannelKnowledge(source_pin_ids=[p.pin_id for p in pins])


# LLM prompt for knowledge extraction
EXTRACTION_PROMPT = """Analyze these pinned messages from a Slack channel and extract any team rules or conventions.

PINNED MESSAGES:
{pin_content}

Extract the following if present (leave null if not found):
- naming_convention: How the team names things (tickets, branches, PRs)
- definition_of_done: What makes work complete
- api_format_rules: API conventions (date formats, field naming, etc.)
- custom_rules: Any other rules or conventions mentioned

Respond in JSON format:
{{
  "naming_convention": "string or null",
  "definition_of_done": "string or null",
  "api_format_rules": "string or null",
  "custom_rules": {{"rule_name": "rule_description"}}
}}

Only extract explicit rules. Don't infer or guess."""

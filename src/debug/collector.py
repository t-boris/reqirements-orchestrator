"""Debug data collector for structured debug output.

Collects debug information during message processing for output when debug mode is enabled.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DebugEntry:
    """Individual debug entry for a processing step."""

    timestamp: datetime
    category: str  # "intent", "duplicates", "decision", "llm", "error"
    title: str
    data: dict
    duration_ms: Optional[int] = None


@dataclass
class LLMCall:
    """Record of an LLM API call."""

    model: str
    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    duration_ms: int


@dataclass
class DebugCollector:
    """Collects debug information during message processing.

    Usage:
        collector = DebugCollector()
        collector.add_entry("intent", "Pattern matching", {"pattern": "TICKET", "confidence": 0.9})
        collector.add_llm_call("gpt-4", "prompt...", "response...", 100, 50, 1200)

        # Output to Slack
        blocks = collector.to_slack_blocks()

        # Output to file attachment
        content = collector.to_file_content()
    """

    entries: list[DebugEntry] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_entry(
        self,
        category: str,
        title: str,
        data: dict,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Add a debug entry."""
        self.entries.append(
            DebugEntry(
                timestamp=datetime.now(timezone.utc),
                category=category,
                title=title,
                data=data,
                duration_ms=duration_ms,
            )
        )

    def add_llm_call(
        self,
        model: str,
        prompt: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
    ) -> None:
        """Add an LLM call record."""
        self.llm_calls.append(
            LLMCall(
                model=model,
                prompt=prompt,
                response=response,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_ms=duration_ms,
            )
        )

    def add_error(self, error: Exception, context: str) -> None:
        """Add an error entry."""
        self.add_entry(
            category="error",
            title=f"Error: {type(error).__name__}",
            data={
                "context": context,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )

    def get_total_duration_ms(self) -> int:
        """Get total duration from start to now in milliseconds."""
        now = datetime.now(timezone.utc)
        delta = now - self.start_time
        return int(delta.total_seconds() * 1000)

    def to_slack_blocks(self, truncate_prompts: int = 300) -> list[dict]:
        """Format debug info as Slack blocks.

        Args:
            truncate_prompts: Max length for LLM prompts/responses (default 300)

        Returns:
            List of Slack Block Kit blocks
        """
        blocks: list[dict] = []

        # Header
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Debug Output", "emoji": True}
        })

        # Timing summary
        total_ms = self.get_total_duration_ms()
        llm_time = sum(call.duration_ms for call in self.llm_calls)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Total time:* {total_ms}ms | *LLM time:* {llm_time}ms | *Entries:* {len(self.entries)} | *LLM calls:* {len(self.llm_calls)}"
            }
        })

        blocks.append({"type": "divider"})

        # Group entries by category
        categories: dict[str, list[DebugEntry]] = {}
        for entry in self.entries:
            if entry.category not in categories:
                categories[entry.category] = []
            categories[entry.category].append(entry)

        # Output each category
        category_order = ["intent", "duplicates", "decision", "llm", "error"]
        category_titles = {
            "intent": "Intent Routing",
            "duplicates": "Duplicate Detection",
            "decision": "Decision Points",
            "llm": "LLM Processing",
            "error": "Errors",
        }

        for cat in category_order:
            if cat not in categories:
                continue

            entries = categories[cat]
            title = category_titles.get(cat, cat.title())

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{title}*"}
            })

            for entry in entries:
                timing = f" ({entry.duration_ms}ms)" if entry.duration_ms else ""
                data_str = self._format_data(entry.data, max_length=200)
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"_{entry.title}_{timing}\n```{data_str}```"
                    }
                })

        # LLM calls section
        if self.llm_calls:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*LLM Calls*"}
            })

            for i, call in enumerate(self.llm_calls, 1):
                prompt_truncated = self._truncate(call.prompt, truncate_prompts)
                response_truncated = self._truncate(call.response, truncate_prompts)

                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Call {i}:* `{call.model}` ({call.duration_ms}ms)\n"
                            f"Tokens: {call.tokens_in} in, {call.tokens_out} out\n"
                            f"*Prompt:*\n```{prompt_truncated}```\n"
                            f"*Response:*\n```{response_truncated}```"
                        )
                    }
                })

        return blocks

    def to_file_content(self) -> str:
        """Format debug info as plain text for file attachment.

        Returns:
            Full debug content as plain text string
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("DEBUG OUTPUT")
        lines.append("=" * 60)
        lines.append("")

        # Timing summary
        total_ms = self.get_total_duration_ms()
        llm_time = sum(call.duration_ms for call in self.llm_calls)
        lines.append(f"Total time: {total_ms}ms")
        lines.append(f"LLM time: {llm_time}ms")
        lines.append(f"Entries: {len(self.entries)}")
        lines.append(f"LLM calls: {len(self.llm_calls)}")
        lines.append("")

        # All entries
        lines.append("-" * 60)
        lines.append("ENTRIES")
        lines.append("-" * 60)

        for entry in self.entries:
            timing = f" ({entry.duration_ms}ms)" if entry.duration_ms else ""
            lines.append(f"[{entry.category.upper()}] {entry.title}{timing}")
            lines.append(f"  Timestamp: {entry.timestamp.isoformat()}")
            for key, value in entry.data.items():
                lines.append(f"  {key}: {value}")
            lines.append("")

        # LLM calls
        if self.llm_calls:
            lines.append("-" * 60)
            lines.append("LLM CALLS")
            lines.append("-" * 60)

            for i, call in enumerate(self.llm_calls, 1):
                lines.append(f"Call {i}: {call.model} ({call.duration_ms}ms)")
                lines.append(f"  Tokens: {call.tokens_in} in, {call.tokens_out} out")
                lines.append("  Prompt:")
                lines.append(f"    {call.prompt}")
                lines.append("  Response:")
                lines.append(f"    {call.response}")
                lines.append("")

        return "\n".join(lines)

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max length with ellipsis."""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."

    def _format_data(self, data: dict, max_length: int = 200) -> str:
        """Format dict as compact string, truncating if needed."""
        # Simple key=value format
        parts = [f"{k}={repr(v)}" for k, v in data.items()]
        result = ", ".join(parts)
        return self._truncate(result, max_length)

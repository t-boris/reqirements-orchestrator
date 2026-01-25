"""BlockRenderer for converting Slack blocks to readable text.

Phase 38: Context Architecture

Bot messages with blocks currently appear empty in LLM context.
BlockRenderer converts blocks to human-readable text for inclusion
in conversation context.
"""

from typing import Any


class BlockRenderer:
    """Convert Slack blocks to human-readable text for LLM context."""

    def render(self, blocks: list[dict]) -> str:
        """Convert blocks array to readable text.

        Args:
            blocks: List of Slack Block Kit blocks

        Returns:
            Human-readable text representation
        """
        parts = []
        for block in blocks:
            rendered = self._render_block(block)
            if rendered:
                parts.append(rendered)
        return "\n".join(parts)

    def _render_block(self, block: dict) -> str:
        """Render a single block by dispatching to type-specific handler."""
        block_type = block.get("type", "")
        handler = getattr(self, f"_render_{block_type}", self._render_unknown)
        return handler(block)

    def _render_section(self, block: dict) -> str:
        """Render section block.

        Sections contain text and optionally an accessory (button, image, etc).
        """
        text_obj = block.get("text", {})
        text = text_obj.get("text", "")

        # Handle accessory if present (button, image, etc.)
        accessory = block.get("accessory")
        if accessory:
            acc_type = accessory.get("type", "")
            if acc_type == "button":
                btn_text = accessory.get("text", {}).get("text", "")
                text += f" [{btn_text}]"
            elif acc_type == "image":
                alt_text = accessory.get("alt_text", "image")
                text += f" [Image: {alt_text}]"

        # Handle fields if present
        fields = block.get("fields", [])
        if fields:
            field_texts = [f.get("text", "") for f in fields]
            if field_texts:
                text += "\n" + " | ".join(field_texts)

        return text

    def _render_actions(self, block: dict) -> str:
        """Render actions block.

        Actions contain interactive elements like buttons and selects.
        """
        elements = block.get("elements", [])
        rendered = []

        for el in elements:
            el_type = el.get("type", "")

            if el_type == "button":
                btn_text = el.get("text", {}).get("text", "")
                rendered.append(f"[{btn_text}]")

            elif el_type in ("static_select", "external_select", "users_select",
                            "conversations_select", "channels_select"):
                placeholder = el.get("placeholder", {}).get("text", "Select...")
                rendered.append(f"[{placeholder}]")

            elif el_type == "overflow":
                rendered.append("[...]")

            elif el_type == "datepicker":
                placeholder = el.get("placeholder", {}).get("text", "Pick a date")
                rendered.append(f"[{placeholder}]")

        return " ".join(rendered) if rendered else ""

    def _render_context(self, block: dict) -> str:
        """Render context block.

        Context blocks contain muted text and images for secondary information.
        """
        elements = block.get("elements", [])
        texts = []

        for el in elements:
            el_type = el.get("type", "")
            if el_type in ("plain_text", "mrkdwn"):
                texts.append(el.get("text", ""))
            elif el_type == "image":
                texts.append(f"[Image: {el.get('alt_text', 'image')}]")

        return " | ".join(texts) if texts else ""

    def _render_header(self, block: dict) -> str:
        """Render header block.

        Headers are large bold text for section titles.
        """
        text_obj = block.get("text", {})
        return f"**{text_obj.get('text', '')}**"

    def _render_divider(self, block: dict) -> str:
        """Render divider block."""
        return "---"

    def _render_rich_text(self, block: dict) -> str:
        """Render rich_text block.

        Rich text blocks have nested elements for formatted content.
        """
        elements = block.get("elements", [])
        return self._extract_rich_text_content(elements)

    def _extract_rich_text_content(self, elements: list) -> str:
        """Extract text content from rich_text nested elements."""
        parts = []

        for el in elements:
            el_type = el.get("type", "")

            if el_type == "rich_text_section":
                section_parts = []
                for sub in el.get("elements", []):
                    sub_type = sub.get("type", "")
                    if sub_type == "text":
                        section_parts.append(sub.get("text", ""))
                    elif sub_type == "user":
                        section_parts.append(f"@{sub.get('user_id', 'user')}")
                    elif sub_type == "link":
                        url = sub.get("url", "")
                        text = sub.get("text", url)
                        section_parts.append(text if text else url)
                    elif sub_type == "emoji":
                        section_parts.append(f":{sub.get('name', 'emoji')}:")
                    elif sub_type == "channel":
                        section_parts.append(f"#{sub.get('channel_id', 'channel')}")
                if section_parts:
                    parts.append("".join(section_parts))

            elif el_type == "rich_text_list":
                list_style = el.get("style", "bullet")
                for idx, item in enumerate(el.get("elements", []), 1):
                    item_text = self._extract_rich_text_content([item])
                    if list_style == "ordered":
                        parts.append(f"{idx}. {item_text}")
                    else:
                        parts.append(f"* {item_text}")

            elif el_type == "rich_text_preformatted":
                section_parts = []
                for sub in el.get("elements", []):
                    if sub.get("type") == "text":
                        section_parts.append(sub.get("text", ""))
                if section_parts:
                    parts.append("```" + "".join(section_parts) + "```")

            elif el_type == "rich_text_quote":
                section_parts = []
                for sub in el.get("elements", []):
                    if sub.get("type") == "text":
                        section_parts.append(sub.get("text", ""))
                if section_parts:
                    parts.append("> " + "".join(section_parts))

        return "\n".join(parts) if parts else ""

    def _render_input(self, block: dict) -> str:
        """Render input block.

        Input blocks contain form elements like text inputs.
        """
        label = block.get("label", {}).get("text", "")
        element = block.get("element", {})
        el_type = element.get("type", "")

        if el_type == "plain_text_input":
            placeholder = element.get("placeholder", {}).get("text", "")
            return f"{label}: [{placeholder}]" if placeholder else f"{label}: [input]"
        elif el_type == "static_select":
            placeholder = element.get("placeholder", {}).get("text", "Select...")
            return f"{label}: [{placeholder}]"
        elif el_type == "multi_static_select":
            placeholder = element.get("placeholder", {}).get("text", "Select...")
            return f"{label}: [{placeholder}]"
        elif el_type == "datepicker":
            return f"{label}: [date]"
        elif el_type == "timepicker":
            return f"{label}: [time]"
        elif el_type == "checkboxes":
            options = element.get("options", [])
            opt_texts = [o.get("text", {}).get("text", "") for o in options]
            return f"{label}: [ ] " + " [ ] ".join(opt_texts)
        elif el_type == "radio_buttons":
            options = element.get("options", [])
            opt_texts = [o.get("text", {}).get("text", "") for o in options]
            return f"{label}: ( ) " + " ( ) ".join(opt_texts)

        return f"{label}: [input]"

    def _render_image(self, block: dict) -> str:
        """Render image block."""
        alt_text = block.get("alt_text", "image")
        title = block.get("title", {}).get("text", "")
        if title:
            return f"[Image: {title} - {alt_text}]"
        return f"[Image: {alt_text}]"

    def _render_video(self, block: dict) -> str:
        """Render video block."""
        alt_text = block.get("alt_text", "video")
        title = block.get("title", {}).get("text", "")
        if title:
            return f"[Video: {title}]"
        return f"[Video: {alt_text}]"

    def _render_file(self, block: dict) -> str:
        """Render file block."""
        return "[File attached]"

    def _render_unknown(self, block: dict) -> str:
        """Render unknown block type as fallback."""
        block_type = block.get("type", "unknown")
        return f"[{block_type} block]"


# Module-level singleton and convenience function
_renderer = BlockRenderer()


def render_blocks(blocks: list[dict]) -> str:
    """Render Slack blocks to readable text.

    Convenience function using singleton renderer.

    Args:
        blocks: List of Slack Block Kit blocks

    Returns:
        Human-readable text representation
    """
    if not blocks:
        return ""
    return _renderer.render(blocks)

"""Markdown-safe formatting and long message splitting for Telegram in ARU AI V4."""

from __future__ import annotations

import re


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """
    Split long message into chunks <= max_length characters without breaking code blocks.
    If a split occurs inside a code fence (```lang), automatically closes it in the
    current chunk and reopens it in the subsequent chunk.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current_chunk = ""
    in_code_block = False
    current_fence = "```"

    # Split lines preserving endings
    lines = text.splitlines(keepends=True)

    for line in lines:
        # Detect code fence toggle
        fence_match = re.match(r"^\s*(```[a-zA-Z0-9_-]*)", line)
        if fence_match:
            if not in_code_block:
                in_code_block = True
                current_fence = fence_match.group(1).strip()
            else:
                in_code_block = False

        # If adding this line would exceed max_length
        if len(current_chunk) + len(line) + (len("\n```") if in_code_block else 0) > max_length:
            if current_chunk:
                if in_code_block:
                    current_chunk += "\n```"
                chunks.append(current_chunk.rstrip("\n"))
                # Next chunk starts with reopened fence if still inside code block
                current_chunk = f"{current_fence}\n" if in_code_block else ""

            # If a single line itself is longer than max_length, hard-slice it
            while len(line) > max_length:
                slice_len = max_length - (len(current_chunk) + 10)
                chunks.append(line[:slice_len])
                line = line[slice_len:]

        current_chunk += line

    if current_chunk:
        chunks.append(current_chunk.rstrip("\n"))

    return chunks


def escape_markdown(text: str) -> str:
    """Escape Telegram markdown control characters in plaintext."""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(r"([%s])" % re.escape(escape_chars), r"\\\1", text)


def format_command_help(commands: dict[str, str]) -> str:
    """Format a dictionary of command descriptions into a readable Telegram message."""
    lines = ["**Available Commands:**\n"]
    for cmd, desc in commands.items():
        lines.append(f"• `/{cmd}` — {desc}")
    return "\n".join(lines)

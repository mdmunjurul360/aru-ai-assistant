"""Tests for Telegram message formatter and splitter in ARU AI V4."""

import pytest
from aru.interfaces.telegram.formatter import (
    escape_markdown,
    format_command_help,
    split_message,
)


def test_split_message_short():
    text = "Short message under limit."
    chunks = split_message(text, max_length=100)
    assert chunks == [text]


def test_split_message_long_plain():
    lines = [f"Line {i}: Some content here" for i in range(50)]
    text = "\n".join(lines)
    chunks = split_message(text, max_length=200)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 200

    # Ensure all content is preserved
    reconstructed = "".join(chunks)
    assert "Line 0" in reconstructed
    assert "Line 49" in reconstructed


def test_split_message_with_code_block():
    code_lines = [f"    print('hello world {i}')" for i in range(40)]
    text = "```python\n" + "\n".join(code_lines) + "\n```"

    chunks = split_message(text, max_length=250)
    assert len(chunks) > 1

    # First chunk must close the code fence
    assert chunks[0].strip().endswith("```")
    # Second chunk must reopen the code fence with language tag
    assert chunks[1].strip().startswith("```python")

    for chunk in chunks:
        assert len(chunk) <= 250


def test_split_message_huge_single_line():
    huge_line = "A" * 500
    chunks = split_message(huge_line, max_length=100)
    assert len(chunks) >= 5
    for chunk in chunks:
        assert len(chunk) <= 100


def test_escape_markdown():
    raw = "Hello_World *bold* [link](url) `code`"
    escaped = escape_markdown(raw)
    assert r"\_" in escaped
    assert r"\*" in escaped
    assert r"\[" in escaped
    assert r"\`" in escaped


def test_format_command_help():
    cmds = {
        "start": "Start bot",
        "help": "Help menu",
    }
    result = format_command_help(cmds)
    assert "• `/start` — Start bot" in result
    assert "• `/help` — Help menu" in result

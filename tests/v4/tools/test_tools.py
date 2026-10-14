"""Unit tests for Phase 7: Tool System."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from aru.tools import (
    BaseTool,
    CalculatorTool,
    ExecutionContext,
    FileReaderTool,
    MemoryTool,
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    WebSearchTool,
)


class DummySlowTool(BaseTool):
    name = "slow_tool"
    description = "A tool that sleeps past its timeout."
    parameters = {"type": "object", "properties": {}}
    timeout = 0.1

    async def execute(self, **kwargs) -> ToolResult:
        await asyncio.sleep(1.0)
        return ToolResult(success=True, output="Done")


def test_permission_levels_and_context() -> None:
    """Verify permission hierarchy and ExecutionContext permission checks."""
    assert ToolPermission.READ.level < ToolPermission.WRITE.level
    assert ToolPermission.WRITE.level < ToolPermission.EXECUTE.level
    assert ToolPermission.EXECUTE.level < ToolPermission.ADMIN.level

    boss_ctx = ExecutionContext(user_id=1, is_boss=True)
    assert boss_ctx.has_permission(ToolPermission.ADMIN) is True
    assert boss_ctx.has_permission(ToolPermission.EXECUTE) is True

    guest_ctx = ExecutionContext(user_id=2, is_boss=False, permissions={ToolPermission.READ})
    assert guest_ctx.has_permission(ToolPermission.READ) is True
    assert guest_ctx.has_permission(ToolPermission.WRITE) is False
    assert guest_ctx.has_permission(ToolPermission.ADMIN) is False


def test_tool_registry_and_schema_export() -> None:
    """Verify ToolRegistry stores tools and exports function calling schemas."""
    registry = ToolRegistry()
    calc = CalculatorTool()
    registry.register(calc)

    assert registry.has("calculator") is True
    assert registry.get("calculator") is calc
    assert registry.count() == 1

    schemas = registry.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "calculator"

    assert registry.unregister("calculator") is True
    assert registry.has("calculator") is False


@pytest.mark.asyncio
async def test_tool_executor_permission_denial() -> None:
    """Verify ToolExecutor blocks unauthorized calls."""
    registry = ToolRegistry()
    calc = CalculatorTool()
    calc.required_permission = ToolPermission.ADMIN
    registry.register(calc)

    executor = ToolExecutor(registry)
    guest_ctx = ExecutionContext(user_id=5, is_boss=False, permissions={ToolPermission.READ})

    result = await executor.execute("calculator", {"expression": "2+2"}, context=guest_ctx)
    assert result.success is False
    assert "Permission denied" in result.error
    assert result.metadata["reason"] == "unauthorized"


@pytest.mark.asyncio
async def test_tool_executor_timeout_protection() -> None:
    """Verify ToolExecutor intercepts execution timeouts cleanly."""
    registry = ToolRegistry()
    registry.register(DummySlowTool())
    executor = ToolExecutor(registry)

    result = await executor.execute("slow_tool", {}, context=ExecutionContext(user_id=1, is_boss=True))
    assert result.success is False
    assert "timed out" in result.error
    assert result.metadata.get("timeout") is True


@pytest.mark.asyncio
async def test_calculator_tool_evaluation() -> None:
    """Verify CalculatorTool computes safe arithmetic and rejects dangerous expressions."""
    calc = CalculatorTool()

    res1 = await calc.execute(expression="(10 * 5) + (100 / 4)")
    assert res1.success is True
    assert res1.output == 75.0

    res2 = await calc.execute(expression="sqrt(144) + round(3.7)")
    assert res2.success is True
    assert res2.output == 16.0

    # Test rejection of forbidden syntax/imports
    res_bad = await calc.execute(expression="__import__('os').system('echo bad')")
    assert res_bad.success is False
    assert "Math evaluation error" in res_bad.error


@pytest.mark.asyncio
async def test_file_reader_tool_security(tmp_path: Path) -> None:
    """Verify FileReaderTool reads allowed files and strictly blocks escape and sensitive files."""
    test_file = tmp_path / "hello.txt"
    test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\n", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=123", encoding="utf-8")

    tool = FileReaderTool(root_dir=tmp_path)

    # 1. Allowed read with offset and limit
    res_read = await tool.execute(action="read", path="hello.txt", offset=2, limit=2)
    assert res_read.success is True
    assert "Line 2" in res_read.output
    assert "Line 3" in res_read.output
    assert "Line 1" not in res_read.output

    # 2. Block sensitive file .env
    res_env = await tool.execute(action="read", path=".env")
    assert res_env.success is False
    assert res_env.metadata.get("security_blocked") is True

    # 3. Block directory traversal escape
    res_escape = await tool.execute(action="read", path="../../windows/system32/cmd.exe")
    assert res_escape.success is False
    assert res_escape.metadata.get("security_blocked") is True


@pytest.mark.asyncio
async def test_memory_tool_integration() -> None:
    """Verify MemoryTool save, search, and recall dispatching."""
    mock_service = MagicMock()
    mock_service.remember = AsyncMock(return_value=42)
    mock_fact = MagicMock()
    mock_fact.id = 42
    mock_fact.key = "boss_food"
    mock_fact.category = "preference"
    mock_fact.content = "Likes biryani"
    mock_service.recall = AsyncMock(return_value=[mock_fact])

    tool = MemoryTool(memory_service=mock_service)

    # Save
    save_res = await tool.execute(action="save", content="Likes biryani", key="boss_food")
    assert save_res.success is True
    assert save_res.metadata["id"] == 42
    mock_service.remember.assert_awaited_once_with(content="Likes biryani", key="boss_food", category="general")

    # Search
    recall_res = await tool.execute(action="recall", query="biryani")
    assert recall_res.success is True
    assert len(recall_res.output) == 1
    assert recall_res.output[0]["content"] == "Likes biryani"


@pytest.mark.asyncio
async def test_web_search_tool() -> None:
    """Verify WebSearchTool executes backend or default mock results."""
    mock_backend = AsyncMock(return_value=[{"title": "Custom Result", "url": "https://example.com", "snippet": "Snippet"}])
    tool = WebSearchTool(backend=mock_backend)

    res = await tool.execute(query="FastAI")
    assert res.success is True
    assert res.metadata["count"] == 1
    assert res.output[0]["title"] == "Custom Result"

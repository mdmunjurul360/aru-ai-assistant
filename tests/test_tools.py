"""Comprehensive test suite for Sprint 4: Unified Tool Registry & MCP Architecture."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.tools.base import (
    BaseTool,
    ExecutionContext,
    ToolPermission,
    ToolResult,
)
from modules.tools.browser_tool import BrowserTool
from modules.tools.file_reader_tool import FileReaderTool
from modules.tools.manager import ToolManager
from modules.tools.memory_tool import MemoryTool
from modules.tools.research_tool import ResearchTool
from modules.tools.task_tool import TaskTool
from modules.commands import handle_tools_command, handle_help_command, handle_status_command
from modules.browser import BrowserAutomation


# ============================================================================
# 1. BaseTool & Permission Tests
# ============================================================================

def test_tool_permission_hierarchy():
    assert ToolPermission.READ.level < ToolPermission.WRITE.level
    assert ToolPermission.WRITE.level < ToolPermission.EXECUTE.level
    assert ToolPermission.EXECUTE.level < ToolPermission.ADMIN.level

    assert ToolPermission.READ.is_authorized_by(ToolPermission.WRITE)
    assert ToolPermission.READ.is_authorized_by(ToolPermission.ADMIN)
    assert not ToolPermission.ADMIN.is_authorized_by(ToolPermission.READ)
    assert not ToolPermission.EXECUTE.is_authorized_by(ToolPermission.WRITE)


def test_execution_context_permissions():
    boss_ctx = ExecutionContext(user_id=1, is_boss=True)
    assert boss_ctx.has_permission(ToolPermission.ADMIN)
    assert boss_ctx.has_permission(ToolPermission.EXECUTE)
    assert boss_ctx.has_permission(ToolPermission.WRITE)
    assert boss_ctx.has_permission(ToolPermission.READ)

    guest_ctx = ExecutionContext(user_id=2, is_boss=False)
    assert not guest_ctx.has_permission(ToolPermission.READ)
    assert not guest_ctx.has_permission(ToolPermission.ADMIN)

    read_ctx = ExecutionContext(user_id=3, is_boss=False, permissions={ToolPermission.READ})
    assert read_ctx.has_permission(ToolPermission.READ)
    assert not read_ctx.has_permission(ToolPermission.WRITE)
    assert not read_ctx.has_permission(ToolPermission.EXECUTE)

    admin_ctx = ExecutionContext(user_id=4, is_boss=False, permissions={ToolPermission.ADMIN})
    assert admin_ctx.has_permission(ToolPermission.READ)
    assert admin_ctx.has_permission(ToolPermission.WRITE)
    assert admin_ctx.has_permission(ToolPermission.EXECUTE)
    assert admin_ctx.has_permission(ToolPermission.ADMIN)


def test_tool_result_formatting():
    res_ok = ToolResult(success=True, output="Operation completed")
    assert res_ok.format_output() == "Operation completed"
    assert res_ok.to_dict()["success"] is True

    res_dict = ToolResult(success=True, output={"status": "ok", "items": 5})
    assert '"status": "ok"' in res_dict.format_output()

    res_err = ToolResult(success=False, error="File missing")
    assert "File missing" in res_err.format_output()
    assert "❌ ত্রুটি" in res_err.format_output()

    res_empty = ToolResult(success=True, output=None)
    assert "কোনো আউটপুট নেই" in res_empty.format_output()


class DummyEchoTool(BaseTool):
    name = "dummy_echo"
    description = "Test dummy tool"
    required_permission = ToolPermission.READ
    timeout = 5.0
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "count": {"type": "integer"},
            "mode": {"type": "string", "enum": ["loud", "quiet"]},
        },
        "required": ["message"],
    }

    async def execute(self, **kwargs):
        msg = kwargs.get("message", "")
        count = kwargs.get("count", 1)
        return ToolResult(success=True, output=msg * count)


def test_base_tool_mcp_schema_and_validation():
    tool = DummyEchoTool()
    schema = tool.to_mcp_schema()
    assert schema["name"] == "dummy_echo"
    assert schema["required_permission"] == "read"
    assert "message" in schema["input_schema"]["properties"]

    # Valid input
    ok, err = tool.validate_input({"message": "hello", "count": 2, "mode": "loud"})
    assert ok is True and err is None

    # Missing required field
    ok, err = tool.validate_input({"count": 2})
    assert ok is False
    assert "Missing required parameter 'message'" in err

    # Wrong type
    ok, err = tool.validate_input({"message": 12345})
    assert ok is False
    assert "must be a string" in err

    # Invalid enum
    ok, err = tool.validate_input({"message": "test", "mode": "invalid_mode"})
    assert ok is False
    assert "not in allowed choices" in err


# ============================================================================
# 2. ToolManager Registration, Discovery & Execution Tests
# ============================================================================

@pytest.mark.asyncio
async def test_tool_manager_registration_and_discovery():
    mgr = ToolManager()
    tool = DummyEchoTool()

    mgr.register_tool(tool)
    assert mgr.has_tool("dummy_echo")
    assert mgr.has_tool("DUMMY_ECHO")
    assert mgr.get_tool("dummy_echo") is tool
    assert "dummy_echo" in mgr.get_tool_names()

    tools_list = mgr.list_tools()
    assert len(tools_list) == 1
    assert tools_list[0]["name"] == "dummy_echo"

    assert mgr.unregister_tool("dummy_echo") is True
    assert not mgr.has_tool("dummy_echo")
    assert mgr.unregister_tool("dummy_echo") is False


def test_tool_manager_invalid_registration():
    mgr = ToolManager()
    with pytest.raises(TypeError):
        mgr.register_tool("not a tool")  # type: ignore

    class BadTool(BaseTool):
        name = ""
        description = "bad"
        parameters = {}
        async def execute(self, **kwargs):
            return ToolResult(success=True)

    with pytest.raises(ValueError):
        mgr.register_tool(BadTool())


@pytest.mark.asyncio
async def test_tool_manager_execution_and_permissions():
    mgr = ToolManager()
    tool = DummyEchoTool()
    mgr.register_tool(tool)

    boss_ctx = ExecutionContext(user_id=1, is_boss=True)
    guest_ctx = ExecutionContext(user_id=2, is_boss=False)

    # Boss execution succeeds
    res = await mgr.execute_tool("dummy_echo", {"message": "hi", "count": 2}, boss_ctx)
    assert res.success is True
    assert res.output == "hihi"
    assert "duration_sec" in res.metadata

    # Guest execution fails with permission denial
    denied = await mgr.execute_tool("dummy_echo", {"message": "hi"}, guest_ctx)
    assert denied.success is False
    assert "Permission denied" in denied.error
    assert denied.metadata["reason"] == "unauthorized"

    # Non-existent tool
    missing = await mgr.execute_tool("nonexistent", {}, boss_ctx)
    assert missing.success is False
    assert "not found" in missing.error


@pytest.mark.asyncio
async def test_tool_manager_timeout_handling():
    mgr = ToolManager()

    class HangingTool(BaseTool):
        name = "hanging"
        description = "Sleeps forever"
        parameters = {"type": "object", "properties": {}}
        required_permission = ToolPermission.READ
        timeout = 0.05

        async def execute(self, **kwargs):
            await asyncio.sleep(1.0)
            return ToolResult(success=True)

    mgr.register_tool(HangingTool())
    boss_ctx = ExecutionContext(user_id=1, is_boss=True)

    res = await mgr.execute_tool("hanging", {}, boss_ctx)
    assert res.success is False
    assert "timed out" in res.error
    assert res.metadata.get("timeout") is True


# ============================================================================
# 3. FileReaderTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_file_reader_tool(tmp_path: Path):
    # Setup test directory
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n", encoding="utf-8")

    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "sub_file.txt").write_text("Nested", encoding="utf-8")

    tool = FileReaderTool(root_dir=tmp_path)

    # 1. Read normal file
    res = await tool.execute(action="read", path="sample.txt", offset=2, limit=2)
    assert res.success is True
    assert "Line 2" in res.output
    assert "Line 3" in res.output
    assert "Line 1" not in res.output
    assert res.metadata["total_lines"] == 5

    # 2. Info action
    info_res = await tool.execute(action="info", path="sample.txt")
    assert info_res.success is True
    assert info_res.output["is_file"] is True
    assert info_res.output["size_bytes"] > 0

    # 3. List action
    list_res = await tool.execute(action="list", path="sub")
    assert list_res.success is True
    assert any(item["name"] == "sub_file.txt" for item in list_res.output)


@pytest.mark.asyncio
async def test_file_reader_security_sandbox(tmp_path: Path):
    secret_env = tmp_path / ".env"
    secret_env.write_text("GROQ_API_KEY=supersecret\n", encoding="utf-8")

    session_file = tmp_path / "bot.session"
    session_file.write_text("session_binary_data", encoding="utf-8")

    tool = FileReaderTool(root_dir=tmp_path)

    # 1. Attempt path traversal outside root
    escape_res = await tool.execute(action="read", path="../../windows/system32/cmd.exe")
    assert escape_res.success is False
    assert "Security violation" in escape_res.error
    assert escape_res.metadata.get("security_blocked") is True

    # 2. Attempt to read .env
    env_res = await tool.execute(action="read", path=".env")
    assert env_res.success is False
    assert "sensitive file" in env_res.error
    assert env_res.metadata.get("security_blocked") is True

    # 3. Attempt to read .session
    sess_res = await tool.execute(action="read", path="bot.session")
    assert sess_res.success is False
    assert "sensitive file" in sess_res.error

    # 4. Non-existent file
    missing_res = await tool.execute(action="read", path="ghost.txt")
    assert missing_res.success is False
    assert "does not exist" in missing_res.error


# ============================================================================
# 4. ResearchTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_research_tool():
    mock_service = MagicMock()
    mock_report = MagicMock()
    mock_report.confidence_score = 0.95
    mock_report.sources = ["https://example.com"]
    mock_report.cached = False
    mock_report.provider_used = "duckduckgo"

    mock_service.research = AsyncMock(return_value=mock_report)
    mock_service.format_report = MagicMock(return_value="🔍 Verified Research Summary")
    mock_service.scrape_url = AsyncMock(return_value={"content": "Scraped body", "title": "Example", "status_code": 200})
    mock_service.cache.get = MagicMock(return_value={"summary": "Cached result", "created_at": "2026-10-11"})

    tool = ResearchTool(research_service=mock_service)

    # 1. Search action
    res_search = await tool.execute(action="search", query="Quantum computing")
    assert res_search.success is True
    assert "Verified Research Summary" in res_search.output
    assert res_search.metadata["confidence"] == 0.95
    mock_service.research.assert_awaited_once_with("Quantum computing", max_results=5)

    # 2. Scrape action
    res_scrape = await tool.execute(action="scrape", url="https://example.com/test")
    assert res_scrape.success is True
    assert res_scrape.output == "Scraped body"

    # 3. Cached search action
    res_cached = await tool.execute(action="cached_search", query="AI facts")
    assert res_cached.success is True
    assert res_cached.output == "Cached result"

    # 4. Missing required query
    res_fail = await tool.execute(action="search", query="")
    assert res_fail.success is False
    assert "query" in res_fail.error


# ============================================================================
# 5. MemoryTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_memory_tool():
    mock_service = MagicMock()
    mock_store = MagicMock()
    mock_service.memory_store = mock_store

    mock_item = MagicMock()
    mock_item.id = 42
    mock_item.title = "Favorite color"
    mock_item.content = "Blue"
    mock_item.category = "preference"
    mock_item.tags = "color"

    mock_service.search_memory.return_value = [mock_item]
    mock_store.format_list.return_value = "1. [preference] Favorite color: Blue"
    mock_store.format_item.return_value = "Memory #42: Favorite color"
    mock_service.store_fact.return_value = mock_item
    mock_store.list_all.return_value = [mock_item]
    mock_store.delete.return_value = True

    tool = MemoryTool(memory_service=mock_service)

    # 1. Search
    res_search = await tool.execute(action="search", query="color")
    assert res_search.success is True
    assert "Favorite color" in res_search.output
    assert res_search.metadata["count"] == 1

    # 2. Save
    res_save = await tool.execute(action="save", content="Blue is favorite color", category="preference")
    assert res_save.success is True
    assert "মেমোরি সংরক্ষিত" in res_save.output

    # 3. List
    res_list = await tool.execute(action="list", category="preference")
    assert res_list.success is True
    assert res_list.metadata["count"] == 1

    # 4. Delete
    res_del = await tool.execute(action="delete", id=42)
    assert res_del.success is True
    assert "মুছে ফেলা হয়েছে" in res_del.output


# ============================================================================
# 6. TaskTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_task_tool():
    mock_mgr = MagicMock()
    mock_task = MagicMock()
    mock_task.id = 101
    mock_task.title = "Write tests"
    mock_task.description = "Full coverage"
    mock_task.status = "in_progress"
    mock_task.priority = "high"
    mock_task.due_date = "2026-10-15"

    mock_mgr.list_tasks.return_value = [mock_task]
    mock_mgr.format_task_list.return_value = "1. [high] Write tests"
    mock_mgr.format_task.return_value = "Task #101: Write tests"
    mock_mgr.add.return_value = mock_task
    mock_mgr.set_status.return_value = mock_task
    mock_mgr.set_priority.return_value = mock_task
    mock_mgr.delete.return_value = True

    tool = TaskTool(task_manager=mock_mgr)

    # 1. List
    res_list = await tool.execute(action="list")
    assert res_list.success is True
    assert res_list.metadata["count"] == 1

    # 2. Add
    res_add = await tool.execute(action="add", title="Write tests", priority="high")
    assert res_add.success is True
    assert "টাস্ক তৈরি হয়েছে" in res_add.output

    # 3. Update status
    res_status = await tool.execute(action="update_status", id=101, status="in_progress")
    assert res_status.success is True
    assert "স্ট্যাটাস আপডেট" in res_status.output

    # 4. Set priority
    res_prio = await tool.execute(action="set_priority", id=101, priority="high")
    assert res_prio.success is True
    assert "প্রায়োরিটি আপডেট" in res_prio.output

    # 5. Delete
    res_del = await tool.execute(action="delete", id=101)
    assert res_del.success is True
    assert "মুছে ফেলা হয়েছে" in res_del.output


# ============================================================================
# 7. BrowserTool Live Playwright Tests
# ============================================================================

@pytest.mark.asyncio
async def test_browser_tool_live():
    tool = BrowserTool(headless=True)

    # 1. Navigate to data URL
    data_url = "data:text/html,<html><head><title>Aru Test</title></head><body><h1>Welcome to Aru</h1><p>Running Playwright headless.</p></body></html>"
    res = await tool.execute(action="navigate", url=data_url)
    assert res.success is True
    assert "Aru Test" in res.output
    assert "Welcome to Aru" in res.output

    # 2. Extract specific selector
    ext_res = await tool.execute(action="extract_text", url=data_url, selector="h1")
    assert ext_res.success is True
    assert "Welcome to Aru" in ext_res.output

    # 3. Selector not found
    missing_res = await tool.execute(action="extract_text", url=data_url, selector=".nonexistent-class")
    assert missing_res.success is False
    assert "not found" in missing_res.error

    # 4. Screenshot capture
    shot_res = await tool.execute(action="screenshot", url=data_url)
    assert shot_res.success is True
    assert "Screenshot captured" in shot_res.output
    assert shot_res.metadata["bytes_len"] > 0

    # 5. Invalid URL
    bad_url = await tool.execute(action="navigate", url="ftp://invalid")
    assert bad_url.success is False
    assert "Invalid URL" in bad_url.error


# ============================================================================
# 8. Slash Command Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_handle_tools_slash_commands():
    mgr = ToolManager()
    mgr.register_tool(DummyEchoTool())
    boss_ctx = ExecutionContext(user_id=1, is_boss=True)

    # 1. /tools list
    tools_help = await handle_tools_command("/tools", mgr, boss_ctx)
    assert tools_help is not None
    assert "Tool Registry" in tools_help
    assert "dummy_echo" in tools_help

    # 2. /tool dummy_echo (schema inspect)
    tool_inspect = await handle_tools_command("/tool dummy_echo", mgr, boss_ctx)
    assert tool_inspect is not None
    assert "Tool: `dummy_echo`" in tool_inspect
    assert "প্যারামিটার স্কিমা" in tool_inspect

    # 3. /tool dummy_echo {"message": "hello", "count": 3}
    exec_res = await handle_tools_command('/tool dummy_echo {"message": "hello", "count": 3}', mgr, boss_ctx)
    assert exec_res is not None
    assert "hellohellohello" in exec_res
    assert "সফল ✅" in exec_res

    # 4. Invalid tool name
    bad_tool = await handle_tools_command("/tool unknown_tool", mgr, boss_ctx)
    assert bad_tool is not None
    assert "পাওয়া যায়নি" in bad_tool

    # 5. Unrelated text returns None
    assert await handle_tools_command("hello there", mgr, boss_ctx) is None


def test_commands_backward_compatibility():
    # Help command includes tools
    help_text = handle_help_command("/help")
    assert help_text is not None
    assert "/tools" in help_text
    assert "Sprint 4" in help_text

    # Status command includes tools count
    status_text = handle_status_command(
        "/status",
        telegram_ok=True,
        groq_ok=True,
        memory_count=10,
        pending_tasks=3,
        tools_count=5,
    )
    assert status_text is not None
    assert "Active Tools (MCP): 5" in status_text


@pytest.mark.asyncio
async def test_browser_automation_backward_compatibility():
    auto = BrowserAutomation()
    assert await auto.start() is True
    data_url = "data:text/html,<h1>Backward Compatibility Test</h1>"
    nav_text = await auto.navigate(data_url)
    assert "Backward Compatibility Test" in nav_text
    shot = await auto.screenshot(data_url)
    assert isinstance(shot, bytes)
    assert len(shot) > 0
    await auto.stop()

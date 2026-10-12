"""Comprehensive test suite for Autonomous Agent (ReAct + Tool Calling)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.agent import (
    AgentResponse,
    AgentStep,
    AgentTrace,
    AruAgent,
)
from modules.commands import handle_agent_command
from modules.tools.base import BaseTool, ExecutionContext, ToolPermission, ToolResult
from modules.tools.manager import ToolManager


# ============================================================================
# 1. AgentStep & AgentTrace Unit Tests
# ============================================================================

def test_agent_step_and_trace_data_structures():
    step = AgentStep(
        step_number=1,
        tool="research",
        tool_input={"action": "search", "query": "Python jobs"},
        observation="Found 3 remote jobs",
        thought="I should search for jobs first.",
        duration_sec=0.45,
        success=True,
    )
    d = step.to_dict()
    assert d["step"] == 1
    assert d["tool"] == "research"
    assert d["success"] is True

    trace = AgentTrace(trace_id="test-trace-123", user_query="Find python jobs")
    trace.steps.append(step)
    trace.final_answer = "Here are the jobs found."
    trace.total_duration_sec = 1.25

    assert trace.total_tool_calls == 1
    assert trace.tools_used == ["research"]

    formatted = trace.format_trace()
    assert "test-tra" in formatted
    assert "Step 1:" in formatted
    assert "research" in formatted
    assert "Found 3 remote jobs" in formatted


# ============================================================================
# 2. Tool Specs Generation
# ============================================================================

def test_agent_tool_specs_generation():
    mgr = ToolManager()

    class ToolA(BaseTool):
        name = "tool_a"
        description = "Description A"
        required_permission = ToolPermission.READ
        parameters = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        async def execute(self, **kwargs):
            return ToolResult(success=True)

    mgr.register_tool(ToolA())
    mock_ai = MagicMock()
    agent = AruAgent(ai=mock_ai, tool_manager=mgr)

    specs = agent.get_tool_specs()
    assert len(specs) == 1
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["name"] == "tool_a"
    assert specs[0]["function"]["parameters"]["properties"]["q"]["type"] == "string"


# ============================================================================
# 3. Autonomous Direct Answer (No Tools Invoked)
# ============================================================================

@pytest.mark.asyncio
async def test_agent_direct_answer_without_tools():
    mgr = ToolManager()
    mock_ai = MagicMock()
    mock_ai.chat_completion_with_tools = AsyncMock(
        return_value=("Hello Boss! I am here to assist you.", None)
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run("Hello Aru", context=ctx)
    assert resp.tool_calls_count == 0
    assert "Hello Boss" in resp.reply
    assert resp.trace.total_tool_calls == 0
    assert not resp.trace.loop_detected


# ============================================================================
# 4. Single Tool Call Execution Cycle
# ============================================================================

@pytest.mark.asyncio
async def test_agent_single_tool_call():
    mgr = ToolManager()

    class SearchTool(BaseTool):
        name = "search_engine"
        description = "Search web"
        parameters = {"type": "object", "properties": {"q": {"type": "string"}}}
        required_permission = ToolPermission.READ
        async def execute(self, **kwargs):
            return ToolResult(success=True, output=f"Results for {kwargs.get('q')}")

    mgr.register_tool(SearchTool())

    mock_ai = MagicMock()
    # Mock tool call object
    mock_tc = MagicMock()
    mock_tc.id = "call_abc123"
    mock_tc.function.name = "search_engine"
    mock_tc.function.arguments = json.dumps({"q": "FastAPI tutorials"})

    # Turn 1: AI requests tool call
    # Turn 2: AI observes result and generates final answer
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            ("Thinking about searching...", [mock_tc]),
            ("Here are the best FastAPI tutorials for you, Boss.", None),
        ]
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run("Find FastAPI tutorials", context=ctx)
    assert resp.tool_calls_count == 1
    assert "FastAPI tutorials for you" in resp.reply
    assert resp.trace.steps[0].tool == "search_engine"
    assert resp.trace.steps[0].tool_input == {"q": "FastAPI tutorials"}
    assert "Results for FastAPI tutorials" in resp.trace.steps[0].observation


# ============================================================================
# 5. Multi-Step Tool Chain (Research -> Memory -> Task)
# ============================================================================

@pytest.mark.asyncio
async def test_agent_multi_step_workflow():
    """
    Scenario:
    'Find Python remote jobs, save the best one into memory and create a task to apply tomorrow.'
    Chain:
    Step 1: research
    Step 2: memory
    Step 3: tasks
    Step 4: final answer
    """
    mgr = ToolManager()

    class FakeResearch(BaseTool):
        name = "research"
        description = "Research web"
        parameters = {"type": "object", "properties": {"query": {"type": "string"}}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="Job Found: Senior Python Dev at TechCorp ($120k)")

    class FakeMemory(BaseTool):
        name = "memory"
        description = "Save memory"
        parameters = {"type": "object", "properties": {"action": {"type": "string"}, "content": {"type": "string"}}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="Memory saved: id=505")

    class FakeTasks(BaseTool):
        name = "tasks"
        description = "Create task"
        parameters = {"type": "object", "properties": {"action": {"type": "string"}, "title": {"type": "string"}}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="Task created: id=777 (Apply to TechCorp)")

    mgr.register_tool(FakeResearch())
    mgr.register_tool(FakeMemory())
    mgr.register_tool(FakeTasks())

    # Build sequence of tool calls
    tc1 = MagicMock()
    tc1.id = "call_1"
    tc1.function.name = "research"
    tc1.function.arguments = json.dumps({"query": "Python remote jobs"})

    tc2 = MagicMock()
    tc2.id = "call_2"
    tc2.function.name = "memory"
    tc2.function.arguments = json.dumps({"action": "save", "content": "Senior Python Dev at TechCorp"})

    tc3 = MagicMock()
    tc3.id = "call_3"
    tc3.function.name = "tasks"
    tc3.function.arguments = json.dumps({"action": "add", "title": "Apply to TechCorp tomorrow"})

    mock_ai = MagicMock()
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            ("Searching for Python jobs...", [tc1]),
            ("Saving best job into memory...", [tc2]),
            ("Creating task for application...", [tc3]),
            ("বস, আমি TechCorp-এর জবটি পেয়েছি, মেমোরিতে সেভ করেছি এবং আগামীকাল অ্যাপ্লাই করার টাস্ক তৈরি করেছি।", None),
        ]
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr, max_iterations=5)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run(
        "Find Python remote jobs, save the best one into memory and create a task to apply tomorrow.",
        context=ctx,
    )

    assert resp.tool_calls_count == 3
    assert resp.trace.tools_used == ["research", "memory", "tasks"]
    assert "TechCorp" in resp.reply
    assert resp.trace.steps[0].tool == "research"
    assert resp.trace.steps[1].tool == "memory"
    assert resp.trace.steps[2].tool == "tasks"


# ============================================================================
# 6. Infinite Loop Defense & Duplicate Call Detection
# ============================================================================

@pytest.mark.asyncio
async def test_agent_infinite_loop_prevention():
    mgr = ToolManager()

    class EchoTool(BaseTool):
        name = "echo"
        description = "Echoes input"
        parameters = {"type": "object", "properties": {"val": {"type": "string"}}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output=kwargs.get("val", ""))

    mgr.register_tool(EchoTool())

    tc = MagicMock()
    tc.id = "call_repeat"
    tc.function.name = "echo"
    tc.function.arguments = json.dumps({"val": "repeat_me"})

    mock_ai = MagicMock()
    # The AI repeats the exact same call endlessly
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            ("Call 1", [tc]),
            ("Call 2", [tc]),
            ("Call 3", [tc]),
            ("Synthesized final response", None),
        ]
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr, max_iterations=6)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run("Loop test", context=ctx)
    assert resp.trace.loop_detected is True
    assert any("Loop prevention triggered" in s.observation for s in resp.trace.steps)


# ============================================================================
# 7. Max Iterations Ceiling
# ============================================================================

@pytest.mark.asyncio
async def test_agent_max_iterations_ceiling():
    mgr = ToolManager()

    class CountTool(BaseTool):
        name = "counter"
        description = "Counts"
        parameters = {"type": "object", "properties": {"n": {"type": "integer"}}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output=f"Count: {kwargs.get('n')}")

    mgr.register_tool(CountTool())

    def make_tc(idx):
        tc = MagicMock()
        tc.id = f"c_{idx}"
        tc.function.name = "counter"
        tc.function.arguments = json.dumps({"n": idx})
        return tc

    mock_ai = MagicMock()
    # Model attempts 5 calls, but max_iterations is capped at 2
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            ("Iter 1", [make_tc(1)]),
            ("Iter 2", [make_tc(2)]),
            ("Final synthesis after cap reached", None),
        ]
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr, max_iterations=2)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run("Run forever", context=ctx)
    assert resp.trace.iteration_count == 2
    assert resp.tool_calls_count == 2
    assert "Final synthesis" in resp.reply


# ============================================================================
# 8. Graceful Tool Failure Recovery
# ============================================================================

@pytest.mark.asyncio
async def test_agent_graceful_tool_failure_recovery():
    mgr = ToolManager()

    class FailingTool(BaseTool):
        name = "flaky_tool"
        description = "Fails intentionally"
        parameters = {"type": "object", "properties": {}}
        async def execute(self, **kwargs):
            return ToolResult(success=False, error="Target service unreachable (503)")

    mgr.register_tool(FailingTool())

    tc = MagicMock()
    tc.id = "call_fail"
    tc.function.name = "flaky_tool"
    tc.function.arguments = "{}"

    mock_ai = MagicMock()
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            ("Calling flaky tool...", [tc]),
            ("I noticed the service is currently unreachable (503), Boss. I have logged this.", None),
        ]
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run("Try flaky tool", context=ctx)
    assert resp.tool_calls_count == 1
    assert resp.trace.steps[0].success is False
    assert "503" in resp.trace.steps[0].observation
    assert "unreachable" in resp.reply


# ============================================================================
# 9. Text-based ReAct Fallback Parsing
# ============================================================================

@pytest.mark.asyncio
async def test_agent_text_react_fallback_parsing():
    mgr = ToolManager()

    class ReaderTool(BaseTool):
        name = "file_reader"
        description = "Reads files"
        parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output=f"Content of {kwargs.get('path')}")

    mgr.register_tool(ReaderTool())

    text_react_output = (
        "Thought: I need to inspect the README file.\n"
        "Action: file_reader\n"
        'Action Input: {"path": "README.md"}'
    )

    mock_ai = MagicMock()
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            (text_react_output, None),
            ("README file describes the project structure.", None),
        ]
    )

    agent = AruAgent(ai=mock_ai, tool_manager=mgr)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    resp = await agent.run("Read README", context=ctx)
    assert resp.tool_calls_count == 1
    assert resp.trace.steps[0].tool == "file_reader"
    assert resp.trace.steps[0].tool_input == {"path": "README.md"}
    assert "README file describes" in resp.reply


# ============================================================================
# 10. Slash Command /agent and --trace Tests
# ============================================================================

@pytest.mark.asyncio
async def test_handle_agent_command():
    mock_agent = MagicMock()
    mock_trace = MagicMock()
    mock_trace.format_trace.return_value = "🧭 **Trace Details**"

    mock_resp = AgentResponse(
        reply="Task accomplished successfully.",
        trace=mock_trace,
        tool_calls_count=2,
    )
    mock_agent.run = AsyncMock(return_value=mock_resp)
    ctx = ExecutionContext(user_id=1, is_boss=True)

    # 1. Standard /agent call
    res_normal = await handle_agent_command("/agent Research quantum AI", mock_agent, ctx)
    assert res_normal == "Task accomplished successfully."
    mock_agent.run.assert_awaited_with("Research quantum AI", context=ctx)

    # 2. /agent with --trace flag
    res_trace = await handle_agent_command("/agent --trace Research quantum AI", mock_agent, ctx)
    assert "Trace Details" in res_trace
    assert "Task accomplished successfully" in res_trace

    # 3. /agent without prompt
    res_empty = await handle_agent_command("/agent", mock_agent, ctx)
    assert "ব্যবহার:" in res_empty

    # 4. Unrelated text returns None
    assert await handle_agent_command("/other_cmd", mock_agent, ctx) is None

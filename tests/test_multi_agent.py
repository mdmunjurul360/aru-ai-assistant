"""Comprehensive test suite for Sprint 6 Multi-Agent Autonomous Automation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.commands import (
    handle_agent_command,
    handle_plan_command,
    handle_status_command,
    handle_workflow_command,
)
from modules.multi_agent import (
    AgentContext,
    AgentEventBus,
    AgentManager,
    AgentMessage,
    BaseSpecializedAgent,
    BaseWorkflow,
    BrowserAgent,
    CancellationToken,
    EventTraceRecord,
    JobMonitoringWorkflow,
    MemoryAgent,
    MemoryConsolidationWorkflow,
    MessageType,
    MorningBriefingWorkflow,
    MultiAgentManager,
    PlanResult,
    PlannerAgent,
    ReminderExecutionWorkflow,
    ResearchAgent,
    ResearchUpdateWorkflow,
    SchedulerAgent,
    SpecializedBrowserAgent,
    SpecializedMemoryAgent,
    SpecializedResearchAgent,
    SpecializedSchedulerAgent,
    SpecializedTaskAgent,
    SubTask,
    TaskAgent,
    TaskFollowUpWorkflow,
)
from modules.tools.base import ExecutionContext, ToolResult
from modules.tools.manager import ToolManager


# ============================================================================
# 1. EventBus & Cancellation Token Tests
# ============================================================================

@pytest.mark.asyncio
async def test_cancellation_token():
    token = CancellationToken()
    assert not token.is_cancelled
    assert token.reason is None

    token.cancel("User aborted operation")
    assert token.is_cancelled
    assert token.reason == "User aborted operation"

    with pytest.raises(asyncio.CancelledError) as exc_info:
        token.throw_if_cancelled()
    assert "User aborted operation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_agent_event_bus_pub_sub():
    bus = AgentEventBus()
    received_messages: list[AgentMessage] = []

    async def sample_handler(msg: AgentMessage):
        received_messages.append(msg)

    bus.subscribe("topic.test", sample_handler)
    msg = AgentMessage.create(
        sender="sender_a",
        recipient="recipient_b",
        msg_type=MessageType.NOTIFICATION,
        payload={"info": "hello"},
        context_id="ctx-1",
    )

    count = await bus.publish("topic.test", msg)
    assert count == 1
    # Allow background asyncio task to execute
    await asyncio.sleep(0.01)
    assert len(received_messages) == 1
    assert received_messages[0].payload["info"] == "hello"

    # Test unsubscribe
    assert bus.unsubscribe("topic.test", sample_handler) is True
    count2 = await bus.publish("topic.test", msg)
    assert count2 == 0

    history = bus.get_event_history()
    assert len(history) >= 1
    assert history[0]["sender"] == "sender_a"

    bus.clear_history()
    assert len(bus.get_event_history()) == 0


@pytest.mark.asyncio
async def test_agent_event_bus_rpc_point_to_point():
    bus = AgentEventBus()

    async def responder_inbox(msg: AgentMessage):
        # Reply to RPC call
        reply = AgentMessage.create(
            sender=msg.recipient,
            recipient=msg.sender,
            msg_type=MessageType.TASK_RESPONSE,
            payload={"computed": 42},
            context_id=msg.context_id,
            reply_to_id=msg.message_id,
        )
        await bus.send_message(reply)

    bus.subscribe("agent.calc", responder_inbox)

    request = AgentMessage.create(
        sender="planner",
        recipient="calc",
        msg_type=MessageType.TASK_REQUEST,
        payload={"query": "compute something"},
        context_id="ctx-rpc",
    )

    response = await bus.send_and_wait_response(request, timeout=2.0)
    assert response.type == MessageType.TASK_RESPONSE
    assert response.payload["computed"] == 42
    assert response.reply_to_id == request.message_id


@pytest.mark.asyncio
async def test_agent_event_bus_rpc_timeout_and_retries():
    bus = AgentEventBus()
    # No subscriber for "agent.dead_agent"
    request = AgentMessage.create(
        sender="planner",
        recipient="dead_agent",
        msg_type=MessageType.TASK_REQUEST,
        payload={},
        context_id="ctx-timeout",
    )

    resp = await bus.send_and_wait_response(request, timeout=0.1, retries=1)
    assert resp.type == MessageType.ERROR
    assert "timed out" in resp.payload.get("error", "")


# ============================================================================
# 2. Message Schemas, Context, and PlanResult Tests
# ============================================================================

def test_agent_message_and_context_structures():
    msg = AgentMessage.create(
        sender="planner",
        recipient="research",
        msg_type=MessageType.SUBTASK_DELEGATION,
        payload={"task": "lookup"},
        context_id="ctx-123",
    )
    d = msg.to_dict()
    assert d["sender"] == "planner"
    assert d["recipient"] == "research"
    assert d["type"] == MessageType.SUBTASK_DELEGATION.value

    ctx = AgentContext(context_id="ctx-shared", user_id=42, is_boss=True)
    ctx.set_shared("key1", "val1")
    assert ctx.get_shared("key1") == "val1"
    assert ctx.get_shared("missing", "default") == "default"


def test_subtask_and_plan_result_formatting():
    st1 = SubTask(
        subtask_id="step_1",
        description="Search AI news",
        assigned_agent="research",
        status="completed",
        result="Found news articles",
        duration_sec=0.2,
    )
    st2 = SubTask(
        subtask_id="step_2",
        description="Save summary to memory",
        assigned_agent="memory",
        status="completed",
        result="Saved successfully",
        duration_sec=0.1,
    )

    plan = PlanResult(
        plan_id="plan-abc",
        goal="Gather AI news and remember",
        subtasks=[st1, st2],
        final_synthesis="News gathered and stored.",
        success=True,
        total_duration_sec=0.35,
    )

    formatted = plan.format_plan()
    assert "plan-abc" in formatted
    assert "Gather AI news and remember" in formatted
    assert "✅ Succeeded" in formatted
    assert "step_1" in formatted
    assert "Found news articles" in formatted
    assert "News gathered and stored." in formatted

    d = plan.to_dict()
    assert d["subtasks_count"] == 2
    assert d["success"] is True


# ============================================================================
# 3. Specialized Agents Tests
# ============================================================================

@pytest.mark.asyncio
async def test_specialized_research_agent():
    bus = AgentEventBus()
    mock_tool = AsyncMock()
    mock_tool.execute.return_value = ToolResult(
        success=True,
        output="Result: Python 3.14 features announced",
        metadata={"sources": ["https://python.org"]},
    )

    agent = SpecializedResearchAgent(bus, research_tool=mock_tool)
    ctx = AgentContext()

    res = await agent.execute_task(
        "Search python updates",
        {"action": "search", "query": "Python 3.14"},
        ctx,
    )
    assert res["success"] is True
    assert "Python 3.14" in res["output"]
    assert "research_Python 3.14" in ctx.artifacts

    # Test scrape action
    mock_tool.execute.return_value = ToolResult(success=True, output="Scraped page text")
    scrape_res = await agent.execute_task(
        "Scrape URL",
        {"action": "scrape", "url": "https://python.org"},
        ctx,
    )
    assert scrape_res["success"] is True
    assert scrape_res["output"] == "Scraped page text"


@pytest.mark.asyncio
async def test_specialized_memory_agent():
    bus = AgentEventBus()
    mock_tool = AsyncMock()
    mock_tool.execute.return_value = ToolResult(success=True, output="Memory saved: ID 10")

    agent = SpecializedMemoryAgent(bus, memory_tool=mock_tool)
    ctx = AgentContext()

    # Save action
    save_res = await agent.execute_task(
        "Save note",
        {"action": "save", "content": "Favorite IDE is VSCode", "category": "preference"},
        ctx,
    )
    assert save_res["success"] is True
    assert "Memory saved" in save_res["output"]

    # Search action
    mock_tool.execute.return_value = ToolResult(success=True, output="Found: Favorite IDE")
    search_res = await agent.execute_task(
        "Search note",
        {"action": "search", "query": "IDE"},
        ctx,
    )
    assert search_res["success"] is True
    assert "Favorite IDE" in search_res["output"]


@pytest.mark.asyncio
async def test_specialized_browser_agent():
    bus = AgentEventBus()
    mock_tool = AsyncMock()
    mock_tool.execute.return_value = ToolResult(success=True, output="Navigated to https://example.com")

    agent = SpecializedBrowserAgent(bus, browser_tool=mock_tool)
    ctx = AgentContext()

    res = await agent.execute_task(
        "Browse example",
        {"action": "navigate", "url": "https://example.com"},
        ctx,
    )
    assert res["success"] is True
    assert "Navigated to" in res["output"]


@pytest.mark.asyncio
async def test_specialized_task_agent():
    bus = AgentEventBus()
    mock_tool = AsyncMock()
    mock_tool.execute.return_value = ToolResult(success=True, output="Task created: ID 5")

    agent = SpecializedTaskAgent(bus, task_tool=mock_tool)
    ctx = AgentContext()

    add_res = await agent.execute_task(
        "Create task",
        {"action": "add", "title": "Submit project proposal", "priority": "high"},
        ctx,
    )
    assert add_res["success"] is True
    assert "Task created" in add_res["output"]

    # List action
    mock_tool.execute.return_value = ToolResult(success=True, output="Pending tasks: 1")
    list_res = await agent.execute_task("List tasks", {"action": "list"}, ctx)
    assert list_res["success"] is True
    assert "Pending tasks" in list_res["output"]


@pytest.mark.asyncio
async def test_specialized_scheduler_agent():
    bus = AgentEventBus()
    mock_scheduler = MagicMock()
    mock_scheduler.schedule_reminder.return_value = True
    mock_scheduler.run_maintenance_now.return_value = "DB optimized, WAL flushed"

    agent = SpecializedSchedulerAgent(bus, scheduler=mock_scheduler)
    ctx = AgentContext()

    # Maintenance action
    maint_res = await agent.execute_task("Run DB maintenance", {"action": "maintenance"}, ctx)
    assert maint_res["success"] is True
    assert "DB optimized" in maint_res["output"]

    # Reminder action
    remind_res = await agent.execute_task(
        "Set alert",
        {"action": "schedule_reminder", "message": "Team standup", "run_at": "2026-10-12T09:00:00"},
        ctx,
    )
    assert remind_res["success"] is True
    assert "Team standup" in remind_res["output"]


@pytest.mark.asyncio
async def test_specialized_agent_lifecycle_and_inbox():
    bus = AgentEventBus()
    mock_tool = AsyncMock()
    mock_tool.execute.return_value = ToolResult(success=True, output="Handled via inbox")

    agent = SpecializedMemoryAgent(bus, memory_tool=mock_tool)
    agent.start()

    # Dispatch a delegation message
    req_msg = AgentMessage.create(
        sender="planner",
        recipient="memory",
        msg_type=MessageType.SUBTASK_DELEGATION,
        payload={"task": "Find item", "input": {"action": "search", "query": "test"}},
        context_id="ctx-agent-test",
    )

    resp = await bus.send_and_wait_response(req_msg, timeout=2.0)
    assert resp.type == MessageType.TASK_RESPONSE
    assert resp.payload["success"] is True
    assert resp.payload["result"]["output"] == "Handled via inbox"

    agent.stop()


# ============================================================================
# 4. PlannerAgent Decomposition & DAG Execution Tests
# ============================================================================

@pytest.mark.asyncio
async def test_planner_agent_decomposition_with_ai():
    bus = AgentEventBus()
    mock_ai = MagicMock()

    json_plan = {
        "subtasks": [
            {
                "id": "step_1",
                "description": "Search remote python jobs",
                "agent": "research",
                "dependencies": [],
                "input": {"action": "search", "query": "remote python jobs"},
            },
            {
                "id": "step_2",
                "description": "Save remote job summary",
                "agent": "memory",
                "dependencies": ["step_1"],
                "input": {"action": "save", "content": "{{step_1.result}}"},
            },
        ]
    }
    mock_ai.chat_completion_with_tools = AsyncMock(
        return_value=(f"```json\n{json.dumps(json_plan)}\n```", None)
    )

    planner = PlannerAgent(bus, ai=mock_ai)
    ctx = AgentContext()

    subtasks = await planner.decompose_goal("Find python jobs and save to memory", ctx)
    assert len(subtasks) == 2
    assert subtasks[0].assigned_agent == "research"
    assert subtasks[1].assigned_agent == "memory"
    assert subtasks[1].dependencies == ["step_1"]


@pytest.mark.asyncio
async def test_planner_agent_heuristic_fallback():
    bus = AgentEventBus()
    mock_ai = MagicMock()
    mock_ai.chat_completion_with_tools = AsyncMock(side_effect=RuntimeError("AI Offline"))

    planner = PlannerAgent(bus, ai=mock_ai)
    ctx = AgentContext()

    subtasks = await planner.decompose_goal("Find remote jobs and save to memory and create task", ctx)
    assert len(subtasks) >= 2
    agents = [s.assigned_agent for s in subtasks]
    assert "research" in agents
    assert "memory" in agents or "task" in agents


@pytest.mark.asyncio
async def test_planner_agent_plan_and_execute_full_workflow():
    bus = AgentEventBus()
    mock_ai = MagicMock()

    # 1. AI decomposition returns 2 steps
    json_plan = {
        "subtasks": [
            {
                "id": "step_1",
                "description": "Search AI tools",
                "agent": "research",
                "dependencies": [],
                "input": {"query": "Top AI tools 2026"},
            },
            {
                "id": "step_2",
                "description": "Create review task",
                "agent": "task",
                "dependencies": ["step_1"],
                "input": {"title": "Review AI tools: {{step_1.result}}"},
            },
        ]
    }

    # First call decomposes, second call synthesizes
    mock_ai.chat_completion_with_tools = AsyncMock(
        side_effect=[
            (json.dumps(json_plan), None),
            ("বস, সব AI টুলস খোঁজা হয়েছে এবং টাস্ক তৈরি করা হয়েছে।", None),
        ]
    )

    # 2. Mock specialized agents responding to delegations
    research_agent = SpecializedResearchAgent(bus, research_tool=AsyncMock(
        execute=AsyncMock(return_value=ToolResult(success=True, output="Tools: Groq, Claude, Aru"))
    ))
    task_agent = SpecializedTaskAgent(bus, task_tool=AsyncMock(
        execute=AsyncMock(return_value=ToolResult(success=True, output="Task ID #99 created"))
    ))
    research_agent.start()
    task_agent.start()

    planner = PlannerAgent(bus, ai=mock_ai)
    planner.start()

    ctx = AgentContext()
    result = await planner.plan_and_execute("Search top AI tools and create review task", context=ctx)

    assert result.success is True
    assert len(result.subtasks) == 2
    assert result.subtasks[0].status == "completed"
    assert result.subtasks[1].status == "completed"
    assert "Tools: Groq, Claude, Aru" in str(result.subtasks[0].result)
    assert "সব AI টুলস" in result.final_synthesis

    research_agent.stop()
    task_agent.stop()
    planner.stop()


# ============================================================================
# 5. Background Autonomous Workflows Tests
# ============================================================================

@pytest.mark.asyncio
async def test_autonomous_workflows_execution():
    mock_ai = MagicMock()
    mock_tm = MagicMock()

    # Tools
    mock_browser = AsyncMock(execute=AsyncMock(return_value=ToolResult(success=True, output="Browser OK")))
    mock_memory = AsyncMock(execute=AsyncMock(return_value=ToolResult(success=True, output="Memory facts", metadata={"count": 5})))
    mock_research = AsyncMock(execute=AsyncMock(return_value=ToolResult(success=True, output="Tech headlines for today")))
    mock_task = AsyncMock(execute=AsyncMock(return_value=ToolResult(success=True, output="Task #12: Finish report")))

    mock_tm.get_tool.side_effect = lambda name: {
        "browser": mock_browser,
        "memory": mock_memory,
        "research": mock_research,
        "tasks": mock_task,
    }.get(name)

    mock_sched = MagicMock()
    mock_sched.run_maintenance_now.return_value = "Maintenance clean"

    manager = MultiAgentManager(
        ai=mock_ai,
        tool_manager=mock_tm,
        scheduler=mock_sched,
    )

    # 1. Morning Briefing Workflow
    mb = await manager.run_workflow("morning_briefing")
    assert mb["success"] is True
    assert "সকালের স্বয়ংক্রিয় ব্রিফিং" in mb["report"]

    # 2. Research Update Workflow
    ru = await manager.run_workflow("research_update")
    assert ru["success"] is True
    assert "topic" in ru

    # 3. Job Monitoring Workflow
    jm = await manager.run_workflow("job_monitoring")
    assert jm["success"] is True
    assert jm["jobs_found"] is True

    # 4. Reminder Execution Workflow
    re = await manager.run_workflow("reminder_execution")
    assert re["success"] is True
    assert "Maintenance clean" in str(re["maintenance"])

    # 5. Task Follow-Up Workflow
    tf = await manager.run_workflow("task_follow_up")
    assert tf["success"] is True
    assert "টাস্ক ফলো-আপ পরামর্শ" in tf["recommendation"]

    # 6. Memory Consolidation Workflow
    mc = await manager.run_workflow("memory_consolidation")
    assert mc["success"] is True
    assert mc["consolidated_items"] == 5

    # Non-existent workflow
    err_wf = await manager.run_workflow("unknown_wf")
    assert err_wf["success"] is False


# ============================================================================
# 6. MultiAgentManager & Command Handlers Tests
# ============================================================================

@pytest.mark.asyncio
async def test_multi_agent_manager_status_and_shutdown():
    mock_ai = MagicMock()
    mock_tm = MagicMock()
    mock_tm.get_tool.return_value = None

    manager = AgentManager(ai=mock_ai, tool_manager=mock_tm)
    status = manager.get_status()
    assert status["agents_count"] == 6
    assert status["workflows_count"] == 6
    assert "planner" in status["agents"]
    assert "research" in status["agents"]

    agents_list = manager.list_agents()
    assert len(agents_list) == 6

    workflows_list = manager.list_workflows()
    assert len(workflows_list) == 6

    manager.shutdown()


@pytest.mark.asyncio
async def test_handle_plan_command():
    mock_manager = AsyncMock()
    mock_manager.execute_goal.return_value = PlanResult(
        plan_id="plan-test-1",
        goal="Automate tasks",
        subtasks=[],
        final_synthesis="Goal achieved",
        success=True,
    )

    # Help output on empty args
    help_out = await handle_plan_command("/plan", mock_manager)
    assert help_out is not None
    assert "PlannerAgent" in help_out

    # Execution output
    exec_out = await handle_plan_command("/plan Automate tasks", mock_manager)
    assert exec_out is not None
    assert "plan-test-1" in exec_out
    assert "Goal achieved" in exec_out


@pytest.mark.asyncio
async def test_handle_workflow_command():
    mock_manager = MagicMock()
    mock_manager.list_workflows.return_value = [
        {"name": "morning_briefing", "description": "Morning briefing description"}
    ]
    mock_manager.run_workflow = AsyncMock(
        return_value={"success": True, "report": "Morning Briefing Done!"}
    )

    # List workflows
    list_out = await handle_workflow_command("/workflows", mock_manager)
    assert list_out is not None
    assert "morning_briefing" in list_out

    # Run workflow
    run_out = await handle_workflow_command("/workflow morning_briefing", mock_manager)
    assert run_out == "Morning Briefing Done!"


@pytest.mark.asyncio
async def test_handle_agent_command_with_plan_flag():
    mock_agent = AsyncMock()
    mock_manager = AsyncMock()
    mock_manager.execute_goal.return_value = PlanResult(
        plan_id="plan-p2",
        goal="Deep multi-step goal",
        subtasks=[],
        final_synthesis="Planner synthesis finished",
        success=True,
    )

    ctx = ExecutionContext(user_id=1, is_boss=True)
    out = await handle_agent_command(
        "/agent --plan Deep multi-step goal",
        mock_agent,
        ctx,
        manager=mock_manager,
    )
    assert out is not None
    assert "plan-p2" in out
    assert "Planner synthesis finished" in out


def test_handle_status_command_with_multi_agent():
    stat = handle_status_command(
        "/status",
        telegram_ok=True,
        groq_ok=True,
        memory_count=10,
        pending_tasks=2,
        voice_ok=True,
        activity_count=25,
        tools_count=5,
        multi_agents_count=6,
        workflows_count=6,
    )
    assert stat is not None
    assert "Specialized Agents: 6" in stat
    assert "Autonomous Workflows: 6" in stat
    assert "Active Tools (MCP): 5" in stat

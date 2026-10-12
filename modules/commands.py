"""Slash-command handlers for memory and help."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from modules.memory import MemoryStore, CATEGORIES
from modules.scheduler import AruScheduler

if TYPE_CHECKING:
    from modules.anti_spam import AntiSpamManager

logger = logging.getLogger("aru.commands")


def handle_memory_command(text: str, memory: MemoryStore) -> str | None:
    """
    /memory save <category> | <title> | <content>
    /memory search <query>
    /memory list [category]
    /memory update <id> | <title> | <content>
    /memory delete <id>
    """
    stripped = text.strip()
    if not stripped.lower().startswith("/memory"):
        return None

    parts = stripped.split(maxsplit=2)
    if len(parts) < 2:
        return _memory_help()

    sub = parts[1].lower()

    if sub == "save":
        if len(parts) < 3 or "|" not in parts[2]:
            return (
                "ব্যবহার:\n"
                "`/memory save <category> | <title> | <content>`\n"
                f"Categories: {', '.join(CATEGORIES)}"
            )
        segments = [s.strip() for s in parts[2].split("|")]
        if len(segments) < 3:
            return "তিনটি অংশ দিন: category | title | content"
        cat, title, content = segments[0], segments[1], "|".join(segments[2:])
        item = memory.save(title, content, category=cat, tags=cat)
        return f"মেমোরি সংরক্ষিত ✅\n\n{memory.format_item(item)}"

    if sub == "search":
        if len(parts) < 3:
            return "ব্যবহার: `/memory search <কীওয়ার্ড>`"
        items = memory.search(parts[2])
        return f"🔍 ফলাফল ({len(items)}):\n\n{memory.format_list(items)}"

    if sub == "list":
        cat = parts[2].strip().lower() if len(parts) > 2 else None
        items = memory.list_all(category=cat)
        return f"📚 মেমোরি ({len(items)}):\n\n{memory.format_list(items)}"

    if sub == "update":
        if len(parts) < 3 or "|" not in parts[2]:
            return "ব্যবহার: `/memory update <id> | <title> | <content>`"
        segments = [s.strip() for s in parts[2].split("|")]
        if len(segments) < 3:
            return "তিনটি অংশ: id | title | content"
        try:
            mem_id = int(segments[0])
        except ValueError:
            return "অবৈধ memory ID।"
        title = segments[1]
        content = "|".join(segments[2:])
        item = memory.update(mem_id, title=title, content=content)
        if not item:
            return f"মেমোরি #{mem_id} পাওয়া যায়নি।"
        return f"আপডেট হয়েছে ✅\n\n{memory.format_item(item)}"

    if sub == "delete":
        if len(parts) < 3:
            return "ব্যবহার: `/memory delete <id>`"
        try:
            mem_id = int(parts[2])
        except ValueError:
            return "অবৈধ memory ID।"
        if memory.delete(mem_id):
            return f"মেমোরি #{mem_id} মুছে ফেলা হয়েছে।"
        return f"মেমোরি #{mem_id} পাওয়া যায়নি।"

    return _memory_help()


def handle_reminder_command(text: str, scheduler: AruScheduler) -> str | None:
    parsed = scheduler.parse_reminder_command(text)
    if parsed is None and text.strip().lower().startswith("/remind"):
        return (
            "ব্যবহার:\n"
            "`/remind YYYY-MM-DD HH:MM your message`"
        )
    if parsed is None:
        return None
    run_at, message = parsed
    rid = f"reminder_{uuid.uuid4().hex[:8]}"
    if scheduler.schedule_reminder(rid, run_at, message):
        return f"রিমাইন্ডার সেট ✅\n{run_at.strftime('%Y-%m-%d %H:%M')}\n{message}"
    return "রিমাইন্ডার সেট করতে পারছি না।"


async def handle_tools_command(
    text: str,
    tool_manager: Any,
    context: Any,
) -> str | None:
    """
    Handle /tools and /tool <name> <args> commands.
    /tools -> List registered tools and capabilities.
    /tool <name> -> Show tool parameters and schema.
    /tool <name> <json_args> -> Execute tool with context and permissions.
    """
    import json

    stripped = text.strip()
    lower = stripped.lower()

    if lower in ("/tools", "/tools list", "/mcp"):
        schemas = tool_manager.list_tools()
        if not schemas:
            return "🛠️ কোনো টুল নিবন্ধিত নেই।"
        lines = [
            "🛠️ **Aru AI Tool Registry (MCP Architecture)**",
            f"মোট টুলস: {len(schemas)}\n",
        ]
        for s in schemas:
            name = s.get("name", "unknown")
            desc = s.get("description", "")
            perm = s.get("required_permission", "read")
            lines.append(f"• `{name}` `[{perm}]` — {desc}")
        lines.append("\n**ব্যবহার:**")
        lines.append("• টুলের বিবরণ: `/tool <নাম>`")
        lines.append("• টুল চালানো: `/tool <নাম> <json_arguments>`")
        lines.append("• উদাহরণ: `/tool file_reader {\"action\": \"read\", \"path\": \"README.md\", \"limit\": 10}`")
        return "\n".join(lines)

    if lower.startswith("/tool"):
        parts = stripped.split(maxsplit=2)
        if len(parts) < 2:
            return "ব্যবহার: `/tool <নাম>` অথবা `/tool <নাম> <json_arguments>`"

        tool_name = parts[1].strip()
        tool = tool_manager.get_tool(tool_name)
        if not tool:
            available = ", ".join(tool_manager.get_tool_names())
            return f"❌ টুল '{tool_name}' পাওয়া যায়নি। উপলব্ধ টুলস: {available}"

        # If no arguments provided, return schema info
        if len(parts) < 3 or not parts[2].strip():
            schema = tool.to_mcp_schema()
            return (
                f"🔧 **Tool: `{tool.name}`**\n\n"
                f"**বর্ণনা:** {tool.description}\n"
                f"**অনুমতি:** `{tool.required_permission.value}`\n"
                f"**টাইমআউট:** {tool.timeout}s\n\n"
                f"**প্যারামিটার স্কিমা:**\n```json\n"
                f"{json.dumps(schema.get('input_schema', {}), indent=2, ensure_ascii=False)}\n```"
            )

        raw_args = parts[2].strip()
        parsed_args: dict[str, Any] = {}
        if raw_args.startswith("{") and raw_args.endswith("}"):
            try:
                parsed_args = json.loads(raw_args)
            except Exception as exc:
                return f"❌ অবৈধ JSON আর্গুমেন্ট: {exc}"
        else:
            # Fallback: parse key=value or assume default primary argument
            for token in raw_args.split():
                if "=" in token:
                    k, v = token.split("=", 1)
                    parsed_args[k.strip()] = v.strip()
            if not parsed_args:
                # If only raw text is passed, map to standard primary keys
                if tool_name == "research":
                    parsed_args = {"action": "search", "query": raw_args}
                elif tool_name == "memory":
                    parsed_args = {"action": "search", "query": raw_args}
                elif tool_name == "file_reader":
                    parsed_args = {"action": "read", "path": raw_args}
                elif tool_name == "browser":
                    parsed_args = {"action": "navigate", "url": raw_args}
                elif tool_name == "tasks":
                    parsed_args = {"action": "list"}
                else:
                    return f"❌ অনুগ্রহ করে JSON ফরম্যাটে আর্গুমেন্ট দিন: `/tool {tool_name} {{\"key\": \"value\"}}`"

        result = await tool_manager.execute_tool(tool_name, parsed_args, context)
        header = f"🛠️ **Tool `{tool_name}` রেজাল্ট** ({'সফল ✅' if result.success else 'ব্যর্থ ❌'}):\n\n"
        return header + result.format_output()

    return None


async def handle_agent_command(
    text: str,
    agent: Any,
    context: Any,
    manager: Any = None,
) -> str | None:
    """
    Handle /agent [flags] <prompt> command.
    Flags:
      --trace : Show full step-by-step ReAct thought/action/observation trace.
      --plan  : Delegate to MultiAgentManager (PlannerAgent DAG decomposition).
    """
    stripped = text.strip()
    if not stripped.lower().startswith("/agent"):
        return None

    parts = stripped.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return (
            "🤖 **Autonomous Agent**\n\n"
            "ব্যবহার: `/agent <আপনার নির্দেশ>`\n"
            "ট্রেস দেখতে: `/agent --trace <আপনার নির্দেশ>`\n"
            "মাল্টি-এজেন্ট প্ল্যান: `/agent --plan <আপনার জটিল লক্ষ্য>`\n\n"
            "উদাহরণ:\n"
            "`/agent Find Python remote jobs, save the best into memory and create a task for tomorrow.`"
        )

    prompt = parts[1].strip()
    if prompt.startswith("--plan"):
        goal = prompt[len("--plan"):].strip()
        if not goal:
            return "❌ অনুগ্রহ করে লক্ষ্যের বিবরণ লিখুন: `/agent --plan <goal>`"
        if manager is not None:
            from modules.multi_agent.messages import AgentContext
            ctx = AgentContext(
                user_id=getattr(context, "user_id", 1),
                is_boss=getattr(context, "is_boss", True),
            )
            res = await manager.execute_goal(goal, context=ctx)
            return res.format_plan()

    show_trace = False
    if prompt.startswith("--trace"):
        show_trace = True
        prompt = prompt[len("--trace"):].strip()

    if not prompt:
        return "❌ অনুগ্রহ করে নির্দেশের বিবরণ লিখুন।"

    resp = await agent.run(prompt, context=context)
    if show_trace:
        return f"{resp.trace.format_trace()}\n\n💬 **চূড়ান্ত উত্তর:**\n{resp.reply}"
    return resp.reply


async def handle_plan_command(
    text: str,
    manager: Any,
    context: Any = None,
) -> str | None:
    """
    Handle /plan <goal> command using PlannerAgent and multi-agent coordination.
    """
    stripped = text.strip()
    if not stripped.lower().startswith("/plan"):
        return None

    parts = stripped.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return (
            "📋 **Multi-Agent Planner (Sprint 6)**\n\n"
            "ব্যবহার: `/plan <আপনার জটিল লক্ষ্য>`\n\n"
            "PlannerAgent আপনার লক্ষ্যকে একাধিক বিশেষায়িত সাবটাস্কে ভাগ করবে "
            "(Research, Memory, Browser, Task, Scheduler) এবং স্বয়ংক্রিয়ভাবে সম্পন্ন করবে।\n\n"
            "উদাহরণ:\n"
            "`/plan Find remote AI jobs, save key requirements to memory, and schedule application task`"
        )

    goal = parts[1].strip()
    from modules.multi_agent.messages import AgentContext
    ctx = AgentContext(
        user_id=getattr(context, "user_id", 1),
        is_boss=getattr(context, "is_boss", True),
    )
    result = await manager.execute_goal(goal, context=ctx)
    return result.format_plan()


async def handle_workflow_command(
    text: str,
    manager: Any,
    context: Any = None,
) -> str | None:
    """
    Handle /workflow [name] or /workflows command for autonomous background workflows.
    """
    stripped = text.strip()
    lower = stripped.lower()
    if not (lower == "/workflows" or lower.startswith("/workflow")):
        return None

    parts = stripped.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip() or lower == "/workflows":
        workflows = manager.list_workflows() if hasattr(manager, "list_workflows") else []
        lines = ["⚡ **স্বয়ংক্রিয় ব্যাকগ্রাউন্ড ওয়ার্কফ্লো (Multi-Agent Workflows)**\n"]
        for wf in workflows:
            lines.append(f"• `/workflow {wf['name']}` — {wf['description']}")
        lines.append("\nব্যবহার: `/workflow <নাম>` চালিয়ে তাৎক্ষণিক রান করুন।")
        return "\n".join(lines)

    wf_name = parts[1].strip().lower()
    from modules.multi_agent.messages import AgentContext
    ctx = AgentContext(
        user_id=getattr(context, "user_id", 1),
        is_boss=getattr(context, "is_boss", True),
    )
    res = await manager.run_workflow(wf_name, context=ctx)
    if not res.get("success", False):
        return f"❌ ওয়ার্কফ্লো রান করতে সমস্যা: {res.get('error', 'অজানা ত্রুটি')}"

    if "report" in res:
        return res["report"]
    if "recommendation" in res:
        return res["recommendation"]
    return (
        f"✅ **ওয়ার্কফ্লো `{wf_name}` সফলভাবে সম্পন্ন হয়েছে!**\n\n"
        + "\n".join(f"• **{k}:** {v}" for k, v in res.items() if k not in ("workflow", "success"))
    )


def handle_help_command(text: str) -> str | None:
    if text.strip().lower() not in ("/help", "/start", "/aru"):
        return None
    return (
        "🤖 **Aru AI v2 — Autonomous Personal AI Assistant**\n\n"
        "**Multi-Agent Coordination (Sprint 6):**\n"
        "`/plan <goal>` · PlannerAgent জটিল লক্ষ্য ভেঙে মাল্টি-এজেন্ট সম্পন্ন করে।\n"
        "`/workflows` · `/workflow <name>` (Morning Briefing, Jobs, Memory Consolidation ইত্যাদি)\n"
        "`/agent [--trace|--plan] <instruction>`\n\n"
        "**Voice:** ভয়েস মেসেজ পাঠান — ট্রান্সক্রাইব করে উত্তর দেব।\n\n"
        "**Memory (v2):**\n"
        "`/remember <fact>` · `/memories` · `/forget <id>`\n"
        "`/searchmemory <q>`\n"
        "`/memory save cat | title | content` (v1 compatible)\n\n"
        "**Smart Tasks:**\n"
        "`/task add <title> [| desc] [| priority]`\n"
        "`/task list` · `/task status <id> <status>`\n"
        "`/task priority <id> <level>` · `/task done <id>`\n\n"
        "**Research:** `/research <topic>`\n\n"
        "**Tools & MCP (Sprint 4):** `/tools` · `/tool <name> [json_args]`\n\n"
        "**Scheduler:** `/remind YYYY-MM-DD HH:MM message`\n\n"
        "**Status & Cooldown:** `/status` · `/cooldown`"
    )


def handle_status_command(
    text: str,
    *,
    telegram_ok: bool,
    groq_ok: bool,
    memory_count: int,
    pending_tasks: int,
    voice_ok: bool = False,
    activity_count: int = 0,
    tools_count: int = 0,
    multi_agents_count: int = 0,
    workflows_count: int = 0,
    llm_status: str | dict[str, Any] | None = None,
) -> str | None:
    if text.strip().lower() != "/status":
        return None
    tools_line = f"Active Tools (MCP): {tools_count}\n" if tools_count > 0 else ""
    agents_line = f"Specialized Agents: {multi_agents_count}\n" if multi_agents_count > 0 else ""
    wf_line = f"Autonomous Workflows: {workflows_count}\n" if workflows_count > 0 else ""

    llm_section = ""
    if llm_status:
        if isinstance(llm_status, dict):
            lines = [f"{k.capitalize()}: {v}" for k, v in llm_status.items()]
            llm_section = f"\n**AI Providers:**\n" + "\n".join(lines) + "\n"
        elif isinstance(llm_status, str):
            llm_section = f"\n**AI Providers:**\n{llm_status}\n"

    return (
        "📊 **Aru AI v2 Status**\n\n"
        f"Telegram: {'✅' if telegram_ok else '❌'}\n"
        f"Groq AI: {'✅' if groq_ok else '❌'}\n"
        f"Voice: {'✅' if voice_ok else '❌'}\n"
        f"Memories: {memory_count}\n"
        f"Pending tasks: {pending_tasks}\n"
        f"{tools_line}"
        f"{agents_line}"
        f"{wf_line}"
        f"{llm_section}"
        f"Activity logs: {activity_count}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )



def handle_cooldown_command(text: str, anti_spam: "AntiSpamManager", user_id: int) -> str | None:
    """Show cooldown status for the requesting user."""
    if text.strip().lower() != "/cooldown":
        return None

    info = anti_spam.get_cooldown_info(user_id)
    if not info:
        return "❌ আপনার কোনো কুলডাউন সক্রিয় নেই।"

    hours_left = anti_spam._hours_until_next_reply(user_id)
    if hours_left <= 0:
        return "✅ কুলডাউন শেষ হয়েছে। আপনি এখন আবার মেসেজ করতে পারেন।"

    return (
        f"⏳ **আপনার Cooldown Status**\n\n"
        f"User ID: `{user_id}`\n"
        f"Last Reply: {info.last_reply_at}\n"
        f"Messages During Cooldown: {info.message_count}/100\n"
        f"Time Remaining: {hours_left} ঘণ্টা"
    )


def _memory_help() -> str:
    return (
        "**Memory commands:**\n"
        "`/memory save category | title | content`\n"
        "`/memory search <query>`\n"
        "`/memory list [category]`\n"
        "`/memory update id | title | content`\n"
        "`/memory delete <id>`"
    )

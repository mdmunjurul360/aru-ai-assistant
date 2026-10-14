"""Prompt templating and system prompt loader for ARU AI V4."""

from __future__ import annotations

import string
from datetime import datetime
from typing import Any
from aru.brain.models import LLMMessage
from aru.core.config.models import AppSettings


class PromptTemplate:
    """A parameterized prompt template with safe placeholder substitution."""

    def __init__(self, template: str) -> None:
        self._template = template

    @property
    def raw_template(self) -> str:
        return self._template

    def render(self, **kwargs: Any) -> str:
        """Safely substitute keyword arguments into template."""
        # Use string.Template for safe substitution avoiding KeyErrors on missing vars
        tmpl = string.Template(self._template)
        # Convert values to strings
        str_kwargs = {k: str(v) for k, v in kwargs.items()}
        return tmpl.safe_substitute(str_kwargs)


class PromptLoader:
    """Manages system personas, few-shot examples, and runtime context injection."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings
        if settings:
            self._base_system_prompt = settings.llm.system_prompt
            self._timezone = settings.scheduler.timezone
        else:
            self._base_system_prompt = (
                "You are Aru, the personal AI assistant of your Boss.\n"
                "You are loyal, intelligent, friendly, witty, helpful and professional.\n"
                "Always answer in the same language used by the Boss (Bangla or English)."
            )
            self._timezone = "Asia/Dhaka"

    def build_system_message(
        self,
        boss_name: str = "Boss",
        relevant_memories: list[str] | None = None,
        extra_directives: list[str] | None = None,
    ) -> LLMMessage:
        """Construct full system prompt with dynamic facts and instructions."""
        sections: list[str] = [self._base_system_prompt]

        # Context details
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sections.append(f"\n[Environment]\nCurrent Time: {now_str} ({self._timezone})\nBoss: {boss_name}")

        if relevant_memories:
            mem_text = "\n".join(f"- {m}" for m in relevant_memories)
            sections.append(f"\n[Relevant Long-Term Memories]\n{mem_text}")

        if extra_directives:
            dir_text = "\n".join(f"- {d}" for d in extra_directives)
            sections.append(f"\n[Active Directives]\n{dir_text}")

        full_content = "\n".join(sections)
        return LLMMessage(role="system", content=full_content)

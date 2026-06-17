"""
Future-ready extension points.

v2 modules (voice, research) are implemented in modules/voice.py and modules/research.py.
Remaining stubs: WhatsApp, Gmail, GitHub.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aru.future")

# v2 re-exports for backward compatibility
from modules.voice import VoiceAssistant as VoiceChatModule  # noqa: E402
from modules.research import ResearchAgent  # noqa: E402


class WhatsAppModule:
    async def send_message(self, to: str, text: str) -> bool:
        raise NotImplementedError("WhatsApp automation coming soon")


class GmailModule:
    async def summarize_inbox(self, limit: int = 10) -> str:
        raise NotImplementedError("Gmail assistant coming soon")


class GitHubModule:
    async def list_prs(self, repo: str) -> list[dict]:
        raise NotImplementedError("GitHub assistant coming soon")


class ResearchAgent:
    async def research(self, query: str) -> str:
        raise NotImplementedError("Research agent coming soon")

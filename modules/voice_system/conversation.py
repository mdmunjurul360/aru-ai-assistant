"""End-to-End Voice Conversations: STT -> Agent reasoning -> TTS."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from modules.voice import VoiceAssistant
from modules.voice_system.tts import TextToSpeechEngine

logger = logging.getLogger("aru.voice_system.conversation")


@dataclass
class VoiceTurnResult:
    """Outcome of a conversational voice interaction turn."""
    transcript: str
    reply_text: str
    audio_reply_bytes: bytes
    success: bool
    error: str | None = None


class VoiceConversationManager:
    """
    Orchestrates full-duplex voice conversations:
      1. Speech-to-Text: Transcribes incoming voice notes via Groq Whisper.
      2. AI Agent Processing: Generates contextual reply.
      3. Text-to-Speech: Synthesizes high-fidelity voice audio reply.
    """

    def __init__(
        self,
        voice_assistant: VoiceAssistant,
        tts_engine: TextToSpeechEngine | None = None,
        ai: Any = None,
    ) -> None:
        self.stt = voice_assistant
        self.tts = tts_engine or TextToSpeechEngine()
        self.ai = ai

    async def process_voice_turn(
        self,
        audio_input: bytes,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> VoiceTurnResult:
        """Execute complete STT -> Reasoning -> TTS cycle."""
        if not audio_input:
            return VoiceTurnResult("", "", b"", False, "Empty audio input")

        # 1. Speech to Text
        transcript = await self.stt.transcribe(audio_input)
        if not transcript:
            return VoiceTurnResult("", "", b"", False, "Speech-to-text transcription yielded empty text")

        # 2. AI Reasoning
        reply_text = ""
        if self.ai and hasattr(self.ai, "chat_completion"):
            messages = list(conversation_history or [])
            messages.append({"role": "user", "content": transcript})
            reply_text = await self.ai.chat_completion(messages)
        else:
            reply_text = f"বস, আপনার কথা শুনেছি: '{transcript}'। নির্দেশ অনুযায়ী কাজ করছি।"

        # 3. Text to Speech
        audio_reply = self.tts.synthesize(reply_text)

        logger.info("Voice turn completed: transcript='%s' reply_len=%d", transcript[:50], len(reply_text))
        return VoiceTurnResult(
            transcript=transcript,
            reply_text=reply_text,
            audio_reply_bytes=audio_reply,
            success=True,
        )

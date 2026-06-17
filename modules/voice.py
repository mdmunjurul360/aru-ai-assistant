"""Voice assistant: Telegram voice messages → Groq transcription → AI reply."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from groq import Groq
from groq import APIConnectionError, APIStatusError, RateLimitError

from modules.config import GROQ_API_KEY, reload_settings

if TYPE_CHECKING:
    from modules.ai import AruAI
    from modules.activity_log import ActivityLogger
    from modules.memory import MemoryStore

logger = logging.getLogger("aru.voice")

WHISPER_MODEL = "whisper-large-v3"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0


class VoiceAssistant:
    """Transcribe Telegram voice notes and route them through Aru AI."""

    def __init__(self, ai: "AruAI", activity: "ActivityLogger | None" = None) -> None:
        self._ai = ai
        self._activity = activity
        self._client: Groq | None = None

    def connect(self) -> bool:
        reload_settings()
        if not GROQ_API_KEY:
            logger.error("GROQ_API_KEY missing — voice transcription unavailable")
            return False
        try:
            self._client = Groq(api_key=GROQ_API_KEY)
            logger.info("Voice assistant ready (model=%s)", WHISPER_MODEL)
            return True
        except Exception as exc:
            logger.exception("Voice assistant init failed: %s", exc)
            return False

    @property
    def is_ready(self) -> bool:
        return self._client is not None

    async def transcribe(self, audio_bytes: bytes, *, filename: str = "voice.ogg") -> str:
        """Convert speech bytes to text via Groq Whisper."""
        if not self._client:
            raise RuntimeError("Voice assistant not connected")

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                text = await asyncio.to_thread(
                    self._transcribe_sync,
                    audio_bytes,
                    filename,
                )
                if self._activity:
                    self._activity.log(
                        "voice",
                        "transcribe",
                        f"chars={len(text)}",
                    )
                logger.info("Voice transcribed | len=%s", len(text))
                return text
            except RateLimitError as exc:
                last_error = exc
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
            except (APIConnectionError, APIStatusError) as exc:
                last_error = exc
                logger.warning("Whisper API error: %s — retry %s/%s", exc, attempt, MAX_RETRIES)
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
            except Exception as exc:
                last_error = exc
                break

        if self._activity:
            self._activity.log_error("voice", "transcribe", last_error or "unknown")
        raise RuntimeError(f"Transcription failed: {last_error}")

    def _transcribe_sync(self, audio_bytes: bytes, filename: str) -> str:
        assert self._client is not None
        suffix = Path(filename).suffix or ".ogg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as audio_file:
                result = self._client.audio.transcriptions.create(
                    file=(filename, audio_file.read()),
                    model=WHISPER_MODEL,
                    response_format="text",
                )
            if isinstance(result, str):
                return result.strip()
            return str(result).strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def process_voice_message(
        self,
        audio_bytes: bytes,
        *,
        memory: "MemoryStore",
        conversation_history: list[dict[str, str]] | None = None,
        filename: str = "voice.ogg",
    ) -> tuple[str, str]:
        """
        Full voice pipeline: transcribe → AI response.
        Returns (transcript, ai_reply).
        """
        transcript = await self.transcribe(audio_bytes, filename=filename)
        if not transcript:
            return "", "ভয়েস বুঝতে পারিনি। আবার স্পষ্টভাবে বলুন বস।"

        memory_ctx = memory.context_for_ai(transcript)
        reply = await self._ai.generate(
            transcript,
            memory_context=memory_ctx,
            conversation_history=conversation_history,
        )

        if self._activity:
            self._activity.log(
                "voice",
                "respond",
                f"transcript_len={len(transcript)} reply_len={len(reply)}",
            )
        return transcript, reply

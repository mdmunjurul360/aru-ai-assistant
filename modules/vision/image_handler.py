"""Telegram image and vision message processing handler for Aru AI."""

from __future__ import annotations

import logging
import struct
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("aru.vision.handler")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
IMAGE_MIME_TYPES = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/gif",
)


def detect_image_format_and_mime(data: bytes) -> tuple[str, str, int, int]:
    """Inspect header magic bytes to detect image format, MIME type, and dimensions."""
    if len(data) < 4:
        return "UNKNOWN", "image/jpeg", 0, 0

    # PNG
    if data.startswith(b"\x89PNG"):
        w, h = struct.unpack(">II", data[16:24]) if len(data) >= 24 else (0, 0)
        return "PNG", "image/png", w, h

    # WebP
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "WEBP", "image/webp", 800, 600

    # JPEG
    if data.startswith(b"\xff\xd8"):
        idx = 2
        w, h = 1920, 1080
        while idx < len(data) - 8:
            if data[idx] == 0xFF:
                marker = data[idx + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[idx + 5 : idx + 9])
                    break
                length = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
                idx += 2 + length
            else:
                idx += 1
        return "JPEG", "image/jpeg", w, h

    # GIF
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10]) if len(data) >= 10 else (0, 0)
        return "GIF", "image/gif", w, h

    return "JPEG", "image/jpeg", 0, 0


def is_image_message(message: Any) -> bool:
    """Determine if a Telethon event message contains a photo or image file."""
    if not message:
        return False

    # 1. Native Telegram Photo
    if getattr(message, "photo", None):
        return True

    # 2. Document sent as photo / screenshot / file
    doc = getattr(message, "document", None)
    if doc:
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime in IMAGE_MIME_TYPES:
            return True

        # Check attributes for file name
        for attr in getattr(doc, "attributes", []):
            fn = getattr(attr, "file_name", "") or ""
            if any(fn.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
                return True

    # 3. Telethon file helper
    f = getattr(message, "file", None)
    if f and getattr(f, "ext", None):
        ext = (f.ext or "").lower()
        if ext in IMAGE_EXTENSIONS:
            return True

    return False


async def process_image_message(
    message: Any,
    user_prompt: str = "",
    provider_manager: Any = None,
) -> str:
    """
    Download incoming image from Telegram and analyze using vision failover chain:
    1. Gemini Vision (primary)
    2. Groq Vision
    3. DeepSeek Multimodal
    4. OpenAI Vision
    """
    start_time = time.perf_counter()
    logger.info("Starting Telegram image processing...")

    # Download media directly as bytes
    try:
        data = await message.download_media(bytes)
    except Exception as exc:
        logger.error("Failed downloading image from Telegram: %s", exc)
        return "দুঃখিত বস, টেলিগ্রাম থেকে ছবিটি ডাউনলোড করতে পারিনি।"

    if not data:
        logger.warning("Empty data received for image message")
        return "দুঃখিত বস, ছবির কোনো ডাটা পাওয়া যায়নি।"

    fmt, mime, width, height = detect_image_format_and_mime(data)
    size_kb = len(data) / 1024
    logger.info(
        "Image downloaded | format=%s mime=%s dimensions=%dx%d size=%.1fKB",
        fmt,
        mime,
        width,
        height,
        size_kb,
    )

    clean_prompt = user_prompt.strip()
    if not clean_prompt:
        clean_prompt = (
            "You are Aru, the loyal and intelligent personal AI assistant of your Boss. "
            "Analyze this image thoroughly and provide a clear, helpful, and detailed description. "
            "If there is any text in the image, transcribe it. "
            "Reply in the same language as Boss (Bangla or English)."
        )
    else:
        clean_prompt = (
            f"You are Aru, the loyal and intelligent personal AI assistant of your Boss. "
            f"Question from Boss about this image: {clean_prompt}\n\n"
            f"Answer the Boss's question accurately based on the visual contents of the image."
        )

    # Use unified Vision failover
    if provider_manager:
        try:
            result = await provider_manager.vision(
                prompt=clean_prompt,
                image_bytes_or_b64=data,
                mime_type=mime,
                max_tokens=1024,
            )
            duration = time.perf_counter() - start_time
            logger.info("Vision analysis succeeded | duration=%.2fs", duration)
            return result
        except Exception as exc:
            logger.error("All vision providers failed for image: %s", exc)

    return "দুঃখিত বস, সমস্ত ভিশন প্রভাইডার এই মুহূর্তে অনুপলব্ধ। কিছুক্ষণ পর আবার চেষ্টা করুন।"

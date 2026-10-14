"""Unit tests for Telegram middleware pipeline in ARU AI V4."""

from __future__ import annotations

from pathlib import Path
import pytest
from pydantic import SecretStr

from aru.core.config.models import AppSettings, SystemSettings, TelegramSettings
from aru.database.connection import DatabaseManager
from aru.database.migrations.runner import MigrationRunner
from aru.database.repositories.anti_spam_repo import AntiSpamRepository
from aru.interfaces.telegram.middleware.anti_spam import AntiSpamMiddleware
from aru.interfaces.telegram.middleware.auth import AuthMiddleware
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext
from aru.interfaces.telegram.middleware.logging import LoggingMiddleware
from aru.interfaces.telegram.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture
async def anti_spam_repo(tmp_path: Path) -> AntiSpamRepository:
    db = DatabaseManager(tmp_path / "test_middleware.db")
    runner = MigrationRunner(db)
    await runner.run()
    repo = AntiSpamRepository(db)
    yield repo
    await db.disconnect()


@pytest.fixture
def test_settings(tmp_path: Path) -> AppSettings:
    sys_settings = SystemSettings.create_default(tmp_path)
    tg_settings = TelegramSettings(
        boss_telegram_id=12345678,
        secret_code=SecretStr("supersecret"),
        unauthorized_reply="Access Denied.",
    )
    return AppSettings(telegram=tg_settings, system=sys_settings)


@pytest.mark.asyncio
async def test_auth_middleware_boss_pass(test_settings: AppSettings, anti_spam_repo: AntiSpamRepository):
    mw = AuthMiddleware(settings=test_settings, anti_spam_repo=anti_spam_repo)
    ctx = TelegramUpdateContext(user_id=12345678, chat_id=12345678, text="Hello")

    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True

    await mw(ctx, next_step)

    assert called is True
    assert ctx.is_boss is True
    assert ctx.is_authorized is True
    assert ctx.is_blocked is False


@pytest.mark.asyncio
async def test_auth_middleware_secret_unlock(test_settings: AppSettings, anti_spam_repo: AntiSpamRepository):
    mw = AuthMiddleware(settings=test_settings, anti_spam_repo=anti_spam_repo)
    ctx = TelegramUpdateContext(user_id=99999, chat_id=99999, text="/unlock supersecret")

    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True

    await mw(ctx, next_step)

    assert called is False  # Handles command directly
    assert ctx.is_authorized is True
    assert "Authentication successful" in (ctx.reply_text or "")
    assert await anti_spam_repo.is_whitelisted(99999) is True


@pytest.mark.asyncio
async def test_auth_middleware_whitelisted(test_settings: AppSettings, anti_spam_repo: AntiSpamRepository):
    await anti_spam_repo.add_to_whitelist(88888, notes="Friend")
    mw = AuthMiddleware(settings=test_settings, anti_spam_repo=anti_spam_repo)
    ctx = TelegramUpdateContext(user_id=88888, chat_id=88888, text="Hey Aru")

    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True

    await mw(ctx, next_step)

    assert called is True
    assert ctx.is_authorized is True
    assert ctx.is_blocked is False


@pytest.mark.asyncio
async def test_auth_middleware_unauthorized_block(test_settings: AppSettings, anti_spam_repo: AntiSpamRepository):
    mw = AuthMiddleware(settings=test_settings, anti_spam_repo=anti_spam_repo)
    ctx = TelegramUpdateContext(user_id=77777, chat_id=77777, text="Who are you?")

    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True

    await mw(ctx, next_step)

    assert called is False
    assert ctx.is_authorized is False
    assert ctx.is_blocked is True
    assert ctx.block_reason == "unauthorized"
    assert ctx.reply_text == "Access Denied."


@pytest.mark.asyncio
async def test_anti_spam_middleware_cooldown(anti_spam_repo: AntiSpamRepository):
    from datetime import datetime, timedelta, timezone

    mw = AntiSpamMiddleware(anti_spam_repo=anti_spam_repo)

    # Set active cooldown
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    await anti_spam_repo.set_cooldown(555, cooldown_until=cooldown_until, reason="Test spam")

    ctx = TelegramUpdateContext(user_id=555, chat_id=555, text="Hello again")
    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True

    await mw(ctx, next_step)

    assert called is False
    assert ctx.is_blocked is True
    assert ctx.block_reason == "cooldown"
    assert "cooldown" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_anti_spam_middleware_boss_bypass(anti_spam_repo: AntiSpamRepository):
    from datetime import datetime, timedelta, timezone

    mw = AntiSpamMiddleware(anti_spam_repo=anti_spam_repo)
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    await anti_spam_repo.set_cooldown(12345678, cooldown_until=cooldown_until, reason="Spam")

    ctx = TelegramUpdateContext(user_id=12345678, chat_id=12345678, text="Hello", is_boss=True)
    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True

    await mw(ctx, next_step)

    assert called is True
    assert ctx.is_blocked is False


@pytest.mark.asyncio
async def test_rate_limit_middleware(anti_spam_repo: AntiSpamRepository):
    mw = RateLimitMiddleware(
        anti_spam_repo=anti_spam_repo,
        max_messages=3,
        time_window_seconds=1.0,
        cooldown_duration_minutes=2,
    )

    ctx1 = TelegramUpdateContext(user_id=444, text="1")
    ctx2 = TelegramUpdateContext(user_id=444, text="2")
    ctx3 = TelegramUpdateContext(user_id=444, text="3")
    ctx4 = TelegramUpdateContext(user_id=444, text="4")

    async def noop(c: TelegramUpdateContext) -> None:
        pass

    await mw(ctx1, noop)
    assert not ctx1.is_blocked

    await mw(ctx2, noop)
    assert not ctx2.is_blocked

    await mw(ctx3, noop)
    assert not ctx3.is_blocked

    # 4th message in immediate sequence exceeds max_messages=3
    await mw(ctx4, noop)
    assert ctx4.is_blocked is True
    assert ctx4.block_reason == "rate_limit_triggered"
    assert await anti_spam_repo.is_cooled_down(444) is True


@pytest.mark.asyncio
async def test_logging_middleware():
    mw = LoggingMiddleware()
    ctx = TelegramUpdateContext(user_id=1, chat_id=2, text="ping")

    called = False

    async def next_step(c: TelegramUpdateContext) -> None:
        nonlocal called
        called = True
        c.handled = True

    await mw(ctx, next_step)
    assert called is True
    assert ctx.handled is True

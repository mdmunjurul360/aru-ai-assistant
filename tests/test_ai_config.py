"""Tests for AI configuration, model selection, and startup validation logic."""

from __future__ import annotations

import os
import pytest

from modules.ai import AruAI
from modules import config
from modules.config import (
    GROQ_MODEL,
    GROQ_MODEL_FALLBACKS,
    reload_settings,
    validate_config,
)
from modules.llm.base_provider import ProviderHealthState
from modules.llm.provider_manager import ProviderManager


@pytest.fixture(autouse=True)
def restore_config():
    import os
    orig_env = dict(os.environ)
    real_env = config.ENV_PATH
    yield
    os.environ.clear()
    os.environ.update(orig_env)
    config.ENV_PATH = real_env
    config.reload_settings()


def test_groq_model_configuration():
    reload_settings()
    assert GROQ_MODEL == "qwen/qwen3.8-27b"
    assert "llama3-70b-8192" not in GROQ_MODEL_FALLBACKS
    assert "qwen/qwen3.8-27b" in GROQ_MODEL_FALLBACKS


def test_ai_models_to_try_ordering():
    ai = AruAI()
    models = ai._models_to_try()
    assert len(models) >= 1
    # First model to try should be active model
    assert models[0] == ai.active_model
    # No duplicate models in list
    assert len(models) == len(set(models))


def test_validate_config_with_valid_env():
    reload_settings()
    problems = validate_config()
    assert len(problems) == 0


def test_validate_config_gemini_only_singular(monkeypatch, tmp_path):
    """Missing Groq/DeepSeek/OpenAI keys must not stop startup when Gemini is configured."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TG_API_ID=123456\n"
        "TG_API_HASH=fakehash123\n"
        "BOSS_TELEGRAM_ID=987654\n"
        "GEMINI_API_KEY=AIzaSyD-valid-gemini-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    config.reload_settings()

    problems = config.validate_config()
    assert problems == []


def test_validate_config_gemini_only_plural_keys(monkeypatch, tmp_path):
    """Plural GEMINI_API_KEYS without any singular variable or Groq key must pass validation."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TG_API_ID=123456\n"
        "TG_API_HASH=fakehash123\n"
        "BOSS_TELEGRAM_ID=987654\n"
        "GEMINI_API_KEYS=gemini_key_1,gemini_key_2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    config.reload_settings()

    problems = config.validate_config()
    assert problems == []


def test_validate_config_deepseek_only(monkeypatch, tmp_path):
    """DeepSeek only configured; all other providers missing keys must pass."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TELEGRAM_API_ID=123456\n"
        "TELEGRAM_API_HASH=fakehash123\n"
        "TELEGRAM_BOT_ID=987654\n"
        "DEEPSEEK_API_KEY=sk-deepseek-valid\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    config.reload_settings()

    problems = config.validate_config()
    assert problems == []


def test_validate_config_openai_only_plural(monkeypatch, tmp_path):
    """OpenAI plural keys only; all other providers missing keys must pass."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TG_API_ID=123456\n"
        "TG_API_HASH=fakehash123\n"
        "BOSS_TELEGRAM_ID=987654\n"
        "OPENAI_API_KEYS=sk-oa-key1;sk-oa-key2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    config.reload_settings()

    problems = config.validate_config()
    assert problems == []


def test_validate_config_fails_when_no_llm_providers_configured(monkeypatch, tmp_path):
    """Startup must fail only when NO LLM provider has any valid API keys."""
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TG_API_ID=123456\n"
        "TG_API_HASH=fakehash123\n"
        "BOSS_TELEGRAM_ID=987654\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    # Ensure env vars are also clear
    for var in list(os.environ.keys()):
        if any(
            var.startswith(p)
            for p in (
                "OPENROUTER_API_KEY",
                "OPENROUTER_API_KEYS",
                "GEMINI_API_KEY",
                "GROQ_API_KEY",
                "OPENAI_API_KEY",
                "DEEPSEEK_API_KEY",
                "CLOUDFLARE_ACCOUNT_ID",
                "CLOUDFLARE_API_KEY",
                "CLOUDFLARE_ACCOUNTS",
            )
        ):
            monkeypatch.delenv(var, raising=False)

    config.reload_settings()

    problems = config.validate_config()
    assert len(problems) == 1
    assert "No LLM provider configured" in problems[0]


def test_providers_without_keys_are_disabled_and_skipped(monkeypatch, tmp_path):
    """Providers without keys must be marked disabled and skipped by ProviderManager."""
    import os

    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TG_API_ID=123456\n"
        "TG_API_HASH=fakehash123\n"
        "BOSS_TELEGRAM_ID=987654\n"
        "GEMINI_API_KEY=AIzaSyD-gemini-only\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    for var in list(os.environ.keys()):
        if any(
            var.startswith(p)
            for p in (
                "OPENROUTER_API_KEY",
                "OPENROUTER_API_KEYS",
                "GEMINI_API_KEYS",
                "GROQ_API_KEY",
                "OPENAI_API_KEY",
                "DEEPSEEK_API_KEY",
                "CLOUDFLARE_ACCOUNT_ID",
                "CLOUDFLARE_API_KEY",
                "CLOUDFLARE_ACCOUNTS",
            )
        ):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyD-gemini-only")

    config.reload_settings()
    manager = ProviderManager(auto_load=True)

    gemini = manager.get_provider("gemini")
    groq = manager.get_provider("groq")
    deepseek = manager.get_provider("deepseek")
    openrouter = manager.get_provider("openrouter")
    openai = manager.get_provider("openai")
    cloudflare = manager.get_provider("cloudflare")

    assert gemini.is_enabled is True
    assert gemini.health.status == ProviderHealthState.HEALTHY
    assert gemini.key_pool.total_keys == 1

    assert groq.is_enabled is False
    assert groq.health.status == ProviderHealthState.DISABLED
    assert groq.key_pool.total_keys == 0

    assert deepseek.is_enabled is False
    assert deepseek.health.status == ProviderHealthState.DISABLED
    assert deepseek.key_pool.total_keys == 0

    assert openrouter.is_enabled is False
    assert openrouter.health.status == ProviderHealthState.DISABLED
    assert openrouter.key_pool.total_keys == 0

    assert openai.is_enabled is False
    assert openai.health.status == ProviderHealthState.DISABLED
    assert openai.key_pool.total_keys == 0

    assert cloudflare.is_enabled is False
    assert cloudflare.health.status == ProviderHealthState.DISABLED
    assert cloudflare.key_pool.total_keys == 0

    assert manager.get_enabled_providers() == ["gemini"]
    assert manager.get_active_provider_name() == "gemini"

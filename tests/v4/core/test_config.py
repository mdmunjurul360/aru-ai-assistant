"""Unit tests for Phase 2: Configuration System."""

from __future__ import annotations

from pathlib import Path
import pytest
from pydantic import ValidationError

from aru.core.config import (
    AppSettings,
    build_settings_from_mapping,
    get_settings,
    load_settings,
    reset_settings,
)
from aru.core.config.parser import parse_api_keys, parse_cloudflare_credentials


def test_parse_api_keys_deduplication_and_delimiters() -> None:
    """Verify parse_api_keys handles comma, semicolon, newline, quotes, and preserves order."""
    singular = "key_primary"
    plural = "key2, 'key3'; \"key4\"\nkey_primary, key5"

    result = parse_api_keys(plural_val=plural, singular_val=singular)
    assert result == ["key_primary", "key2", "key3", "key4", "key5"]


def test_parse_cloudflare_credentials_variations() -> None:
    """Verify parsing single, numbered, and delimited cloudflare accounts."""
    env = {
        "CLOUDFLARE_ACCOUNT_ID": "acc_primary",
        "CLOUDFLARE_API_KEY": "key_primary",
        "CLOUDFLARE_ACCOUNT_ID_2": "acc_two",
        "CLOUDFLARE_API_KEY_2": "key_two",
        "CLOUDFLARE_ACCOUNTS": "acc_three:key_three,acc_four:key_four",
    }
    accounts = parse_cloudflare_credentials(env)
    assert len(accounts) == 4
    assert accounts[0] == {"account_id": "acc_primary", "api_key": "key_primary"}
    assert accounts[1] == {"account_id": "acc_two", "api_key": "key_two"}
    assert accounts[2] == {"account_id": "acc_three", "api_key": "key_three"}
    assert accounts[3] == {"account_id": "acc_four", "api_key": "key_four"}


def test_build_settings_v3_compatibility(tmp_path: Path) -> None:
    """Verify V3 env variable naming maps directly to V4 AppSettings."""
    env_map = {
        "TG_API_ID": "123456",
        "TG_API_HASH": "super_secret_hash_value",
        "BOSS_TELEGRAM_ID": "987654321",
        "GROQ_API_KEY": "gsk_test123",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
        "SCHEDULER_TIMEZONE": "Asia/Dhaka",
        "SEARCH_PROVIDER": "duckduckgo",
        "AGENT_MAX_ITERATIONS": "7",
    }
    settings = build_settings_from_mapping(env_map, root_dir=tmp_path)

    assert settings.telegram.api_id == 123456
    assert settings.telegram.boss_telegram_id == 987654321
    assert settings.telegram.is_configured is True
    assert settings.telegram.api_hash.get_secret_value() == "super_secret_hash_value"

    assert len(settings.llm.groq_api_keys) == 1
    assert settings.llm.groq_api_keys[0].get_secret_value() == "gsk_test123"
    assert settings.llm.groq_model == "llama-3.3-70b-versatile"
    assert settings.scheduler.timezone == "Asia/Dhaka"
    assert settings.agent.max_iterations == 7
    assert settings.research.search_provider == "duckduckgo"


def test_secret_masking(tmp_path: Path) -> None:
    """Verify that sensitive secrets are masked in str and repr representations."""
    env_map = {
        "TG_API_ID": "123456",
        "TG_API_HASH": "ultra_secret_hash_never_leak",
        "GROQ_API_KEY": "gsk_sensitive_token_here",
        "BOSS_TELEGRAM_ID": "12345",
    }
    settings = build_settings_from_mapping(env_map, root_dir=tmp_path)

    repr_str = repr(settings)
    assert "ultra_secret_hash_never_leak" not in repr_str
    assert "gsk_sensitive_token_here" not in repr_str

    tg_repr = repr(settings.telegram)
    assert "ultra_secret_hash_never_leak" not in tg_repr
    assert "**********" in tg_repr or "SecretStr('**********')" in tg_repr or "SecretStr" in tg_repr


def test_settings_validation_errors() -> None:
    """Verify invalid bounds raise validation errors."""
    with pytest.raises(ValidationError):
        # Invalid hour (> 23)
        AppSettings(
            system=None,  # type: ignore[arg-type]
            scheduler={"morning_report_hour": 25},  # type: ignore[arg-type]
        )


def test_get_and_reset_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_settings returns singleton and reset_settings clears cache."""
    reset_settings()
    monkeypatch.setenv("TG_API_ID", "999")
    s1 = get_settings()
    assert s1.telegram.api_id == 999

    s2 = get_settings()
    assert s1 is s2

    reset_settings()
    monkeypatch.setenv("TG_API_ID", "888")
    s3 = get_settings()
    assert s3.telegram.api_id == 888
    reset_settings()

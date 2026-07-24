from __future__ import annotations

import pytest

from open_dota_mcp.config import Settings


def test_defaults_are_bounded_and_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENDOTA_API_KEY", raising=False)
    settings = Settings.from_env()
    assert settings.api_key is None
    assert settings.max_attempts == 3
    assert settings.retry_delay_budget == 10
    assert settings.snapshot_ttl_seconds == 1800
    assert settings.snapshot_capacity == 32


def test_environment_overrides_and_secret_safe_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDOTA_API_KEY", "super-secret")
    monkeypatch.setenv("OPENDOTA_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("OPENDOTA_READ_TIMEOUT", "3.5")
    settings = Settings.from_env()
    assert settings.api_key == "super-secret"
    assert settings.max_attempts == 2
    assert settings.read_timeout == 3.5
    assert "super-secret" not in repr(settings)


def test_invalid_limits_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        Settings(read_timeout=0).validate()

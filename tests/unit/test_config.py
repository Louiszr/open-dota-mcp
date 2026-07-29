from __future__ import annotations

from pathlib import Path

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


def test_cache_environment_defaults_and_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENDOTA_CACHE_DIR", raising=False)
    monkeypatch.delenv("OPENDOTA_CACHE_MAX_BYTES", raising=False)
    defaults = Settings.from_env()
    assert defaults.cache_dir.is_absolute()
    assert defaults.cache_dir.name == "open-dota-mcp"
    assert defaults.cache_max_bytes == 1_073_741_824
    override = tmp_path / "private"
    monkeypatch.setenv("OPENDOTA_CACHE_DIR", str(override))
    monkeypatch.setenv("OPENDOTA_CACHE_MAX_BYTES", "131072")
    configured = Settings.from_env()
    assert configured.cache_dir == override
    assert configured.cache_max_bytes == 131_072
    assert configured.max_attempts == 3
    assert configured.snapshot_capacity == 32


@pytest.mark.parametrize("value", [0, -1, 65_535])
def test_cache_capacity_validation_is_secret_free(value: int) -> None:
    with pytest.raises(ValueError) as caught:
        Settings(api_key="never-display", cache_max_bytes=value).validate()
    assert "cache_max_bytes" in str(caught.value)
    assert "never-display" not in str(caught.value)

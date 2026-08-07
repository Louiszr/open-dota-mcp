from __future__ import annotations

from math import nan
from pathlib import Path

import pytest

from open_dota_mcp.config import Settings


def test_defaults_are_bounded_and_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENDOTA_API_KEY", raising=False)
    settings = Settings.from_env()
    assert settings.api_key is None
    assert settings.max_attempts == 6
    assert settings.retry_base_delays == (2, 4, 8, 16, 32)
    assert settings.retry_jitter_ratio == 0.2
    assert settings.retry_delay_cap == 40
    assert settings.retry_delay_budget == 75
    assert settings.retry_elapsed_budget == 90
    assert settings.request_rate_per_second is None
    assert settings.snapshot_ttl_seconds == 1800
    assert settings.snapshot_capacity == 32


def test_environment_overrides_and_secret_safe_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDOTA_API_KEY", "super-secret")
    monkeypatch.setenv("OPENDOTA_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("OPENDOTA_READ_TIMEOUT", "3.5")
    monkeypatch.setenv("OPENDOTA_RETRY_BASE_DELAYS", "3,6")
    monkeypatch.setenv("OPENDOTA_RETRY_JITTER_RATIO", "0.1")
    monkeypatch.setenv("OPENDOTA_RETRY_ELAPSED_BUDGET", "45")
    monkeypatch.setenv("OPENDOTA_REQUESTS_PER_SECOND", "2.5")
    settings = Settings.from_env()
    assert settings.api_key == "super-secret"
    assert settings.max_attempts == 2
    assert settings.read_timeout == 3.5
    assert settings.retry_base_delays == (3, 6)
    assert settings.retry_jitter_ratio == 0.1
    assert settings.retry_elapsed_budget == 45
    assert settings.request_rate_per_second == 2.5
    assert "super-secret" not in repr(settings)


def test_invalid_limits_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        Settings(read_timeout=0).validate()


@pytest.mark.parametrize("value", ["not-a-number", "0", "-1", "nan", "inf"])
def test_invalid_request_rate_environment_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("OPENDOTA_REQUESTS_PER_SECOND", value)
    with pytest.raises(ValueError):
        Settings.from_env()


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
    assert configured.max_attempts == 6
    assert configured.snapshot_capacity == 32


@pytest.mark.parametrize("value", [0, -1, 65_535])
def test_cache_capacity_validation_is_secret_free(value: int) -> None:
    with pytest.raises(ValueError) as caught:
        Settings(api_key="never-display", cache_max_bytes=value).validate()
    assert "cache_max_bytes" in str(caught.value)
    assert "never-display" not in str(caught.value)


@pytest.mark.parametrize(
    "settings",
    [
        Settings(retry_base_delays=(2, float("inf"), 8, 16, 32)),
        Settings(retry_jitter_ratio=nan),
        Settings(retry_jitter_ratio=1.1),
        Settings(retry_elapsed_budget=float("inf")),
        Settings(request_rate_per_second=0),
        Settings(request_rate_per_second=float("inf")),
        Settings(max_attempts=7),
    ],
)
def test_retry_policy_rejects_nonfinite_and_incomplete_bounds(settings: Settings) -> None:
    with pytest.raises(ValueError):
        settings.validate()

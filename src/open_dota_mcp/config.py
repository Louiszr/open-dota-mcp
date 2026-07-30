"""Environment-backed runtime configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for OpenDota access and local traversal state.

    Secret values are accepted from the environment but excluded from representations.
    """

    base_url: str = "https://api.opendota.com/api"
    api_key: str | None = field(default=None, repr=False)
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    max_attempts: int = 6
    retry_base_delays: tuple[float, ...] = (2.0, 4.0, 8.0, 16.0, 32.0)
    retry_jitter_ratio: float = 0.2
    retry_delay_cap: float = 40.0
    retry_delay_budget: float = 75.0
    retry_elapsed_budget: float = 90.0
    snapshot_ttl_seconds: float = 1800.0
    snapshot_capacity: int = 32
    cache_dir: Path = field(default_factory=lambda: _default_cache_dir())
    cache_max_bytes: int = 1_073_741_824

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from documented environment variables.

        Returns:
            Validated runtime settings.

        Raises:
            ValueError: If a numeric setting is outside its supported range.
        """
        defaults = cls()
        settings = cls(
            base_url=os.getenv("OPENDOTA_BASE_URL", defaults.base_url).rstrip("/"),
            api_key=os.getenv("OPENDOTA_API_KEY") or None,
            connect_timeout=float(os.getenv("OPENDOTA_CONNECT_TIMEOUT", defaults.connect_timeout)),
            read_timeout=float(os.getenv("OPENDOTA_READ_TIMEOUT", defaults.read_timeout)),
            max_attempts=int(os.getenv("OPENDOTA_MAX_ATTEMPTS", defaults.max_attempts)),
            retry_base_delays=_float_tuple(
                os.getenv(
                    "OPENDOTA_RETRY_BASE_DELAYS",
                    ",".join(str(value) for value in defaults.retry_base_delays),
                )
            ),
            retry_jitter_ratio=float(
                os.getenv("OPENDOTA_RETRY_JITTER_RATIO", defaults.retry_jitter_ratio)
            ),
            retry_delay_budget=float(
                os.getenv("OPENDOTA_RETRY_DELAY_BUDGET", defaults.retry_delay_budget)
            ),
            retry_delay_cap=float(os.getenv("OPENDOTA_RETRY_DELAY_CAP", defaults.retry_delay_cap)),
            retry_elapsed_budget=float(
                os.getenv("OPENDOTA_RETRY_ELAPSED_BUDGET", defaults.retry_elapsed_budget)
            ),
            snapshot_ttl_seconds=float(
                os.getenv("OPENDOTA_SNAPSHOT_TTL_SECONDS", defaults.snapshot_ttl_seconds)
            ),
            snapshot_capacity=int(
                os.getenv("OPENDOTA_SNAPSHOT_CAPACITY", defaults.snapshot_capacity)
            ),
            cache_dir=Path(os.getenv("OPENDOTA_CACHE_DIR", str(defaults.cache_dir))).expanduser(),
            cache_max_bytes=int(os.getenv("OPENDOTA_CACHE_MAX_BYTES", defaults.cache_max_bytes)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate finite retry, timeout, and traversal limits.

        Raises:
            ValueError: If any limit is nonpositive or fewer than two attempts are configured.
        """
        positive = {
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "retry_delay_budget": self.retry_delay_budget,
            "retry_delay_cap": self.retry_delay_cap,
            "retry_elapsed_budget": self.retry_elapsed_budget,
            "snapshot_ttl_seconds": self.snapshot_ttl_seconds,
            "snapshot_capacity": self.snapshot_capacity,
            "cache_max_bytes": self.cache_max_bytes,
        }
        if invalid := [
            name
            for name, value in positive.items()
            if value <= 0 or isinstance(value, float) and not isfinite(value)
        ]:
            raise ValueError(f"Settings must be positive: {', '.join(invalid)}")
        if not 1 <= self.max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if len(self.retry_base_delays) < max(0, self.max_attempts - 1):
            raise ValueError("retry_base_delays must cover every configured retry")
        if any(not isfinite(value) or value <= 0 for value in self.retry_base_delays):
            raise ValueError("retry_base_delays must contain positive finite values")
        if not isfinite(self.retry_jitter_ratio) or not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("retry_jitter_ratio must be finite and between 0 and 1")
        if self.cache_max_bytes < 65_536:
            raise ValueError("cache_max_bytes is too small for initialized storage")
        if not str(self.cache_dir):
            raise ValueError("cache_dir must not be empty")


def _default_cache_dir() -> Path:
    """Return the platform-specific per-user cache directory."""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "open-dota-mcp"


def _float_tuple(raw: str) -> tuple[float, ...]:
    """Parse a comma-separated finite retry base sequence."""
    try:
        return tuple(float(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ValueError("OPENDOTA_RETRY_BASE_DELAYS must contain numbers") from exc

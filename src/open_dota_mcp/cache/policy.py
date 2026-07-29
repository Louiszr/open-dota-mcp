"""Fixed OpenDota cache freshness policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Freshness:
    """Resolved immutable freshness category and lifetime."""

    category: Literal["short", "long"]
    ttl_seconds: int


def classify_freshness(operation: str, payload: Any) -> Freshness:
    """Classify a completed upstream result using the reviewed fixed policy."""
    parsed_match = (
        operation == "get_match"
        and isinstance(payload, dict)
        and isinstance(payload.get("version"), int)
        and not isinstance(payload.get("version"), bool)
        and payload["version"] > 0
    )
    if operation in {"get_heroes", "get_patches"} or parsed_match:
        return Freshness("long", 86_400)
    return Freshness("short", 900)

"""Canonical, credential-free cache identities."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

API_CONTRACT = "opendota-public-api-v1"
EXCLUDED_QUERY_PARAMETERS = frozenset({"api_key"})


@dataclass(frozen=True, slots=True)
class CacheIdentity:
    """A stable cache key and bounded operator-safe description."""

    digest: str
    canonical_json: str
    operation: str
    safe_description: str


def build_identity(
    *,
    source: str,
    operation: str,
    path_inputs: dict[str, Any] | None = None,
    query_inputs: dict[str, Any] | None = None,
) -> CacheIdentity:
    """Build a typed SHA-256 identity for one OpenDota GET operation.

    Args:
        source: Configured OpenDota base URL without credentials.
        operation: Stable typed-client operation name.
        path_inputs: Public values used to construct the URL path.
        query_inputs: Complete structured query mapping.

    Returns:
        Canonical identity metadata.

    Raises:
        ValueError: If a value is unsupported, non-finite, or source has credentials.
    """
    normalized_source = _normalize_source(source)
    paths = _normalize(path_inputs or {})
    queries = _normalize(
        {
            key: value
            for key, value in (query_inputs or {}).items()
            if key not in EXCLUDED_QUERY_PARAMETERS
        }
    )
    document = {
        "api_contract": API_CONTRACT,
        "method": "GET",
        "operation": operation,
        "path_inputs": paths,
        "query_inputs": queries,
        "source": normalized_source,
    }
    canonical = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    selectors = {
        **(path_inputs or {}),
        **({"page": queries["page"]} if "page" in queries else {}),
    }
    rendered = ", ".join(f"{key}={value!r}" for key, value in sorted(selectors.items()))
    description = f"{operation}({rendered})" if rendered else f"{operation}()"
    return CacheIdentity(
        digest=hashlib.sha256(canonical.encode()).hexdigest(),
        canonical_json=canonical,
        operation=operation,
        safe_description=description[:200],
    )


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Cache identity values must be finite")
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Cache identity mapping keys must be strings")
        return {key: _normalize(item) for key, item in sorted(value.items())}
    raise ValueError(f"Unsupported cache identity value type: {type(value).__name__}")


def _normalize_source(source: str) -> str:
    parsed = urlsplit(source)
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Cache source must be an absolute credential-free URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Cache source must not contain a query or fragment")
    host = parsed.hostname.lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (
        parsed.scheme.lower() == "http" and port == 80
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = "/" + parsed.path.strip("/") if parsed.path.strip("/") else ""
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))

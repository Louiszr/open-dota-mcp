"""Typed asynchronous access to the documented OpenDota GET surface."""

from __future__ import annotations

import asyncio
import email.utils
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError

type JsonObject = dict[str, Any]
type JsonList = list[JsonObject]

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class OpenDotaClient:
    """Finite-retry client for the documented OpenDota endpoints."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        """Initialize a reusable asynchronous client.

        Args:
            settings: Runtime limits and optional API key.
            transport: Optional offline or custom HTTP transport.
            sleeper: Injectable retry sleeper.
            clock: Injectable monotonic clock.
            jitter: Injectable jitter function accepting an upper bound.
        """
        self.settings = settings or Settings.from_env()
        self.settings.validate()
        headers = {"Accept": "application/json", "User-Agent": "open-dota-mcp/0.1"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        timeout = httpx.Timeout(
            connect=self.settings.connect_timeout,
            read=self.settings.read_timeout,
            write=self.settings.read_timeout,
            pool=self.settings.connect_timeout,
        )
        self._http = httpx.AsyncClient(
            base_url=self.settings.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self._sleep = sleeper
        self._clock = clock
        self._jitter = jitter or (lambda upper: upper * 0.5)

    async def __aenter__(self) -> OpenDotaClient:
        """Enter an asynchronous client context."""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """Close network resources on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def get_match(self, match_id: int) -> JsonObject:
        """Fetch one parsed match by stable match ID."""
        return await self._get_object(f"/matches/{match_id}")

    async def get_heroes(self) -> JsonList:
        """Fetch hero constants as a normalized list."""
        payload = await self._get("/heroes")
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            return payload
        if isinstance(payload, dict) and all(isinstance(item, dict) for item in payload.values()):
            return list(payload.values())
        raise self._contract_error("heroes response must be an object collection")

    async def get_patches(self) -> JsonList:
        """Fetch patch constants."""
        return await self._get_list("/constants/patch")

    async def get_leagues(self) -> JsonList:
        """Fetch the league catalog."""
        return await self._get_list("/leagues")

    async def get_league_matches(self, league_id: int) -> JsonList:
        """Fetch all documented professional matches for a league."""
        return await self._get_list(f"/leagues/{league_id}/matches")

    async def get_teams_page(self, page: int) -> JsonList:
        """Fetch one zero-indexed team catalog page."""
        return await self._get_list("/teams", params={"page": page})

    async def get_team(self, team_id: int) -> JsonObject:
        """Fetch one team identity."""
        return await self._get_object(f"/teams/{team_id}")

    async def get_team_matches(self, team_id: int) -> JsonList:
        """Fetch the selected team's available professional match history."""
        return await self._get_list(f"/teams/{team_id}/matches")

    async def get_pro_players(self) -> JsonList:
        """Fetch professional player identities."""
        return await self._get_list("/proPlayers")

    async def _get_object(self, path: str) -> JsonObject:
        payload = await self._get(path)
        if not isinstance(payload, dict):
            raise self._contract_error("OpenDota returned an unexpected top-level shape")
        return payload

    async def _get_list(
        self, path: str, *, params: Mapping[str, int | str] | None = None
    ) -> JsonList:
        payload = await self._get(path, params=params)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise self._contract_error("OpenDota returned an unexpected top-level shape")
        return payload

    async def _get(self, path: str, *, params: Mapping[str, int | str] | None = None) -> Any:
        started = self._clock()
        delay_spent = 0.0
        last_error: UpstreamError | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                response = await self._http.get(path, params=params)
                if response.status_code not in _RETRYABLE_STATUS:
                    if response.is_error:
                        raise UpstreamError(
                            "upstream_rejected",
                            f"OpenDota rejected the request with HTTP {response.status_code}",
                            retryable_later=response.status_code in {409, 425},
                            status_code=response.status_code,
                        )
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise self._contract_error("OpenDota returned malformed JSON") from exc
                last_error = self._status_error(response.status_code, exhausted=False)
                requested_delay = self._retry_after(response.headers.get("Retry-After"))
            except asyncio.CancelledError:
                raise
            except UpstreamError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                code = (
                    "upstream_timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "upstream_unavailable"
                )
                last_error = UpstreamError(
                    code, "OpenDota could not be reached", retryable_later=True
                )
                requested_delay = None

            if attempt == self.settings.max_attempts:
                break
            delay = requested_delay if requested_delay is not None else self._backoff(attempt)
            elapsed = self._clock() - started
            if (
                delay < 0
                or delay_spent + delay > self.settings.retry_delay_budget
                or elapsed + delay > self.settings.retry_delay_budget + self.settings.read_timeout
            ):
                break
            await self._sleep(delay)
            delay_spent += delay

        assert last_error is not None
        raise UpstreamError(
            last_error.code,
            str(last_error),
            retry_exhausted=True,
            retryable_later=True,
            status_code=last_error.status_code,
        )

    def _backoff(self, attempt: int) -> float:
        base = min(
            self.settings.retry_base_delay * (2 ** (attempt - 1)), self.settings.retry_delay_cap
        )
        return min(base + max(0.0, self._jitter(base)), self.settings.retry_delay_cap)

    @staticmethod
    def _retry_after(raw: str | None) -> float | None:
        if not raw:
            return None
        try:
            return max(0.0, float(raw.strip()))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, (parsed - datetime.now(UTC)).total_seconds())

    @staticmethod
    def _status_error(status_code: int, *, exhausted: bool) -> UpstreamError:
        if status_code == 429:
            code, message = "upstream_rate_limited", "OpenDota rate limit was reached"
        elif status_code == 408:
            code, message = "upstream_timeout", "OpenDota timed out"
        else:
            code, message = "upstream_unavailable", "OpenDota is temporarily unavailable"
        return UpstreamError(
            code,
            message,
            retry_exhausted=exhausted,
            retryable_later=True,
            status_code=status_code,
        )

    @staticmethod
    def _contract_error(message: str) -> UpstreamError:
        return UpstreamError("upstream_contract", message, retryable_later=True)

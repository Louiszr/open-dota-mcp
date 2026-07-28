"""Typed asynchronous access to the documented OpenDota GET surface."""

from __future__ import annotations

import asyncio
import email.utils
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from open_dota_mcp.cache.identity import CacheIdentity, build_identity
from open_dota_mcp.cache.policy import classify_freshness
from open_dota_mcp.cache.store import CacheStore, PopulationLease
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError

type JsonObject = dict[str, Any]
type JsonList = list[JsonObject]

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
logger = logging.getLogger(__name__)


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
        cache_store: CacheStore | None = None,
        population_sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        lease_renewal_interval: float = 10.0,
    ) -> None:
        """Initialize a reusable asynchronous client.

        Args:
            settings: Runtime limits and optional API key.
            transport: Optional offline or custom HTTP transport.
            sleeper: Injectable retry sleeper.
            clock: Injectable monotonic clock.
            jitter: Injectable jitter function accepting an upper bound.
            cache_store: Optional preconfigured persistent response store.
            population_sleeper: Injectable short cache-coordination sleeper.
            lease_renewal_interval: Injectable population renewal cadence.
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
        self._population_sleep = population_sleeper
        self._lease_renewal_interval = lease_renewal_interval
        self._cache = cache_store
        if self._cache is None and transport is None:
            try:
                self._cache = CacheStore(self.settings.cache_dir, self.settings.cache_max_bytes)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                logger.warning(
                    "Shared response cache unavailable; using OpenDota directly: %s", exc
                )
                self._cache = None

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
        return await self._get_object(
            f"/matches/{match_id}", operation="get_match", path_inputs={"match_id": match_id}
        )

    async def get_heroes(self) -> JsonList:
        """Fetch hero constants as a normalized list."""
        payload = await self._get("/heroes", operation="get_heroes")
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            return payload
        if isinstance(payload, dict) and all(isinstance(item, dict) for item in payload.values()):
            return list(payload.values())
        raise self._contract_error("heroes response must be an object collection")

    async def get_patches(self) -> JsonList:
        """Fetch patch constants."""
        return await self._get_list("/constants/patch", operation="get_patches")

    async def get_leagues(self) -> JsonList:
        """Fetch the league catalog."""
        return await self._get_list("/leagues", operation="get_leagues")

    async def get_league_matches(self, league_id: int) -> JsonList:
        """Fetch all documented professional matches for a league."""
        return await self._get_list(
            f"/leagues/{league_id}/matches",
            operation="get_league_matches",
            path_inputs={"league_id": league_id},
        )

    async def get_teams_page(self, page: int) -> JsonList:
        """Fetch one zero-indexed team catalog page."""
        return await self._get_list("/teams", operation="get_teams_page", params={"page": page})

    async def get_team(self, team_id: int) -> JsonObject:
        """Fetch one team identity."""
        return await self._get_object(
            f"/teams/{team_id}", operation="get_team", path_inputs={"team_id": team_id}
        )

    async def get_team_matches(self, team_id: int) -> JsonList:
        """Fetch the selected team's available professional match history."""
        return await self._get_list(
            f"/teams/{team_id}/matches",
            operation="get_team_matches",
            path_inputs={"team_id": team_id},
        )

    async def get_pro_players(self) -> JsonList:
        """Fetch professional player identities."""
        return await self._get_list("/proPlayers", operation="get_pro_players")

    async def _get_object(
        self,
        path: str,
        *,
        operation: str,
        path_inputs: dict[str, Any] | None = None,
    ) -> JsonObject:
        payload = await self._get(path, operation=operation, path_inputs=path_inputs)
        if not isinstance(payload, dict):
            raise self._contract_error("OpenDota returned an unexpected top-level shape")
        return payload

    async def _get_list(
        self,
        path: str,
        *,
        operation: str,
        path_inputs: dict[str, Any] | None = None,
        params: Mapping[str, int | str] | None = None,
    ) -> JsonList:
        payload = await self._get(path, operation=operation, path_inputs=path_inputs, params=params)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise self._contract_error("OpenDota returned an unexpected top-level shape")
        return payload

    async def _get(
        self,
        path: str,
        *,
        operation: str,
        path_inputs: dict[str, Any] | None = None,
        params: Mapping[str, int | str] | None = None,
    ) -> Any:
        identity: CacheIdentity | None = None
        lease = None
        if self._cache is not None:
            try:
                identity = build_identity(
                    source=self.settings.base_url,
                    operation=operation,
                    path_inputs=path_inputs,
                    query_inputs=dict(params or {}),
                )
                hit = await asyncio.to_thread(self._cache.lookup, identity)
                if hit is not None:
                    return hit
                lease = await asyncio.to_thread(self._cache.acquire_population, identity)
                if not lease.owned:
                    while not lease.owned:
                        await self._population_sleep(0.05)
                        failure = await asyncio.to_thread(
                            self._cache.population_failure, lease.attempt_id
                        )
                        if failure is not None:
                            raise UpstreamError(
                                failure.code,
                                failure.message,
                                status_code=failure.status_code,
                                retry_exhausted=failure.retry_exhausted,
                                retryable_later=failure.retryable_later,
                            )
                        hit = await asyncio.to_thread(self._cache.lookup, identity)
                        if hit is not None:
                            return hit
                        next_lease = await asyncio.to_thread(
                            self._cache.acquire_population, identity, attached=lease
                        )
                        if next_lease.owned:
                            lease = next_lease
                            break
            except asyncio.CancelledError:
                raise
            except UpstreamError:
                raise
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self._cache.record_bypass()
                logger.warning("Shared response cache bypassed: %s", exc)
                identity = None
                lease = None
        renewer: asyncio.Task[None] | None = None
        if self._cache is not None and identity is not None and lease is not None and lease.owned:
            renewer = asyncio.create_task(self._renew_population(identity, lease))
        try:
            payload = await self._fetch(path, params=params)
        except UpstreamError as exc:
            if (
                self._cache is not None
                and identity is not None
                and lease is not None
                and lease.owned
            ):
                try:
                    await asyncio.to_thread(
                        self._cache.complete_failure,
                        identity,
                        lease,
                        code=exc.code,
                        message=str(exc),
                        status_code=exc.status_code,
                        retry_exhausted=exc.retry_exhausted,
                        retryable_later=exc.retryable_later,
                    )
                except (OSError, RuntimeError, sqlite3.Error):
                    await asyncio.to_thread(self._cache.release_population, identity, lease)
            await self._stop_renewer(renewer)
            raise
        except BaseException:
            if (
                self._cache is not None
                and identity is not None
                and lease is not None
                and lease.owned
            ):
                await asyncio.to_thread(self._cache.release_population, identity, lease)
            await self._stop_renewer(renewer)
            raise
        if self._cache is not None and identity is not None and lease is not None and lease.owned:
            try:
                self._validate_cacheable_payload(operation, payload)
                freshness = classify_freshness(operation, payload)
                await asyncio.to_thread(
                    self._cache.store,
                    identity,
                    payload,
                    freshness,
                    generation=lease.generation,
                    attempt_id=lease.attempt_id,
                )
            except UpstreamError:
                await asyncio.to_thread(self._cache.release_population, identity, lease)
                await self._stop_renewer(renewer)
                raise
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self._cache.record_bypass()
                logger.warning("Fresh OpenDota response could not be cached: %s", exc)
                await asyncio.to_thread(self._cache.release_population, identity, lease)
        await self._stop_renewer(renewer)
        return payload

    async def _fetch(self, path: str, *, params: Mapping[str, int | str] | None = None) -> Any:
        """Execute the existing finite-retry HTTP behavior without cache I/O."""
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

    async def _renew_population(self, identity: CacheIdentity, lease: PopulationLease) -> None:
        """Keep an owned population attempt alive during bounded upstream work."""
        assert self._cache is not None
        while True:
            await asyncio.sleep(self._lease_renewal_interval)
            try:
                renewed = await asyncio.to_thread(self._cache.renew_population, identity, lease)
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                self._cache.record_bypass()
                logger.warning("Shared response cache lease renewal failed: %s", exc)
                return
            if not renewed:
                return

    @staticmethod
    async def _stop_renewer(renewer: asyncio.Task[None] | None) -> None:
        if renewer is None:
            return
        renewer.cancel()
        try:
            await renewer
        except asyncio.CancelledError:
            pass
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            logger.warning("Shared response cache renewal ended safely: %s", exc)

    def _backoff(self, attempt: int) -> float:
        base = min(
            self.settings.retry_base_delay * (2 ** (attempt - 1)), self.settings.retry_delay_cap
        )
        return min(base + max(0.0, self._jitter(base)), self.settings.retry_delay_cap)

    def _validate_cacheable_payload(self, operation: str, payload: Any) -> None:
        """Reject successful HTTP bodies that fail the operation's top-level contract."""
        if operation in {"get_match", "get_team"}:
            if not isinstance(payload, dict):
                raise self._contract_error("OpenDota returned an unexpected top-level shape")
            return
        if operation == "get_heroes":
            valid = (
                isinstance(payload, list) and all(isinstance(item, dict) for item in payload)
            ) or (
                isinstance(payload, dict)
                and all(isinstance(item, dict) for item in payload.values())
            )
            if not valid:
                raise self._contract_error("heroes response must be an object collection")
            return
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise self._contract_error("OpenDota returned an unexpected top-level shape")

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

# Phase 0 Research: Professional Draft Analysis MCP

## Official OpenDota surface

**Decision**: Build against OpenDota's generated OpenAPI 3.0.3 contract at `https://api.opendota.com/api`, verified against the official `odota/core` sources on 2026-07-23, and isolate all upstream shapes in one typed asynchronous client.

**Rationale**: The official contract documents unauthenticated operation with an optional API key, plus the exact read endpoints needed by the feature. Public no-key requests are therefore the default. OpenDota's official generated specification defines the optional key as the `api_key` query parameter and explicitly permits the equivalent `Authorization: Bearer YOUR-API-KEY` header; the server middleware accepts the Bearer header before the query parameter. This project uses the documented Bearer form only when `OPENDOTA_API_KEY` is configured so the credential does not enter request URLs, and sends no authentication header or parameter otherwise. The contract evidence was verified on 2026-07-23 in OpenDota's official `odota/core` sources: `svc/api/spec.ts` (`securitySchemes.api_key`) and `svc/web.ts` (API-key/rate-limit middleware). `GET /matches/{match_id}` exposes draft actions (`picks_bans`), draft timing, players, teams, league, patch, scores, duration, and parse version. `/leagues` and `/leagues/{league_id}/matches` support professional tournament resolution/discovery; `/teams?page=N` (zero-indexed, up to 1,000 entries per page), `/teams/{team_id}`, and `/teams/{team_id}/matches` support team resolution/discovery. `/heroes`, `/constants/patch`, and `/proPlayers` provide authoritative labels. The league/team match endpoints document no caller pagination inputs, so MCP pagination cannot be delegated upstream.

**Alternatives considered**: Supplying `api_key` in the query string is officially supported but was rejected because URLs are more likely to appear in diagnostics and intermediary logs. Requiring a key was rejected because official public access works without one and the feature requires that default. `/proMatches` was rejected as the primary tournament source because it is a global recent feed and cannot guarantee complete traversal of an arbitrary league. `/leagues/{id}/matchIds` was rejected because it includes amateur leagues and lacks the compact discovery context. OpenDota Explorer/SQL was rejected as overly broad and outside the documented feature surface.

## Consumed endpoint shape verification

**Decision**: Treat each OpenDota route as a distinct projection, even when two routes
describe the same match. Map only fields confirmed by both the official server source and a
live response sampled on 2026-07-23. Keep the automated suite offline by retaining these
verified projections as explicit fixtures.

**Rationale**: OpenDota's generated schema is not sufficient by itself for every projection.
In particular, the generated `/leagues/{league_id}/matches` response references
`MatchObjectResponse`, whose label properties are `radiant_name` and `dire_name`, while the
route's SQL and live payload use `radiant_team_name` and `dire_team_name`. The team-match route
is a different, team-relative projection: it returns `radiant` for the selected team's side and
`opposing_team_id`/`opposing_team_name`, not two full team sides. The implementation therefore
uses route-specific field mappings and retains narrowly scoped compatibility fallbacks only for
previously accepted fixture/full-match shapes.

The verification used the official [`odota/core` generated route source](https://github.com/odota/core/blob/master/svc/api/spec.ts),
the official [`MatchResponse` definition](https://github.com/odota/core/blob/master/svc/api/responses/MatchResponse.ts),
and unauthenticated responses from the public deployment. The exact consumed contracts are:

| Endpoint | Verified top level and consumed fields | Mapping conclusion |
|---|---|---|
| [`GET /matches/{match_id}`](https://api.opendota.com/api/matches/8896486914) | Object. Sample `8896486914` contained `match_id`, `start_time`, `patch`, `leagueid`, `league.name`, `radiant_team_id`, `radiant_name`, `dire_team_id`, `dire_name`, `radiant_win`, both scores, `duration`, `series_id`, `series_type`, `version`, `match_seq_num`, `picks_bans[]`, `draft_timings[]`, and `players[]`. Draft actions use `is_pick`, `hero_id`, `team`, and `order`; timing records use `order`, `extra_time`, and `total_time_taken`; player identity/side uses `account_id`, `name`, `personaname`, `hero_id`, `player_slot`, and optionally `isRadiant`. | The full-match mapping is correct. `name` is the professional name and `personaname` remains deliberately excluded. |
| [`GET /heroes`](https://api.opendota.com/api/heroes) | Array of objects with `id` and `localized_name` (plus ignored descriptive fields). | Build the hero-label index from `id` to `localized_name`. The client's object-collection fallback is compatibility-only. |
| [`GET /constants/patch`](https://api.opendota.com/api/constants/patch) | Array of objects with `id`, `name`, and `date`. The live catalog included `{id: 0, name: "6.70"}` and `{id: 60, name: "7.41"}`. | Build the patch-label index from `id` to `name` without truthiness checks, because zero is valid. `patch`/`patch_name` remain compatibility fallbacks. |
| [`GET /leagues`](https://api.opendota.com/api/leagues) | Array of objects with `leagueid`, `name`, `tier`, `ticket`, and `banner`. | Resolution and eligibility correctly consume `leagueid`, `name`, and `tier`; the other fields are ignored. |
| [`GET /leagues/{league_id}/matches`](https://api.opendota.com/api/leagues/19785/matches) | Array. Sample league `19785` returned `match_id`, `start_time`, `duration`, `leagueid`, `radiant_win`, both scores, `radiant_team_id`, `radiant_team_name`, `dire_team_id`, `dire_team_name`, `series_id`, and `series_type`. It does not provide `league_name`. | Tournament records must use `radiant_team_name`/`dire_team_name` and obtain the league label/tier from `/leagues`. This endpoint also remains the professional-membership check because the official route excludes amateur leagues. |
| [`GET /teams?page=N`](https://api.opendota.com/api/teams?page=0) | Array of at most 1,000 objects per zero-indexed page. Records contain `team_id`, `name`, `tag`, `last_match_time`, rating/results fields, and logo metadata. | Catalog traversal and identity ranking correctly consume `team_id`, `name`, `tag`, and `last_match_time`; an empty page terminates traversal. |
| [`GET /teams/{team_id}`](https://api.opendota.com/api/teams/2163) | One object with the same team identity/rating fields as a catalog item. | Stable-ID lookup correctly consumes `team_id`, `name`, and `tag`. |
| [`GET /teams/{team_id}/matches`](https://api.opendota.com/api/teams/2163/matches) | Array. Sample team `2163` returned `match_id`, `radiant_win`, both scores, boolean `radiant`, `duration`, `start_time`, `leagueid`, `league_name`, `cluster`, `opposing_team_id`, `opposing_team_name`, and `opposing_team_logo`. | Side is `radiant ? radiant : dire` relative to the selected team; the opponent comes directly from `opposing_team_id`/`opposing_team_name`. Do not infer either from absent `radiant_team_id`/`dire_team_id`. |
| [`GET /proPlayers`](https://api.opendota.com/api/proPlayers) | Array. Records contain `account_id`, professional `name`, Steam `personaname`, and team/profile metadata. | Build the fallback professional-name index from `account_id` to `name`; never substitute `personaname`. |

The live samples also confirmed that all collection endpoints above return JSON arrays and that
the two identity endpoints return JSON objects. Unknown fields remain intentionally ignored.
Regression tests now use the compact team-match projection, the league-specific team-name
properties, and patch ID zero so a future mapping change cannot silently reintroduce these
shape assumptions.

**Alternatives considered**: Reusing one generic match projection across full-match, league,
and team routes was rejected because the official queries intentionally return different
columns. Trusting only the generated component reference was rejected because its league-match
team-label names disagree with both the route query and public response. Live-network tests in
the default suite were rejected because they would make CI nondeterministic and consume public
rate limits; dated live verification plus endpoint-faithful offline fixtures provides a stable
contract gate.

## Framework and structured MCP responses

**Decision**: Use current FastMCP typed async tools, Pydantic response models, generated output schemas, the in-memory FastMCP client for most protocol tests, and stdio as the runtime/default subprocess integration transport.

**Rationale**: FastMCP derives complete tool schemas from annotated signatures, supports async I/O, emits standard structured content from typed object results, and provides in-memory and stdio clients for compatibility tests. Domain results use typed sparse unions whose diagnostics carry stable non-OK status and codes so agents can branch without routine success markers; unexpected failures use masked MCP errors. The server reserves stdout for protocol messages and uses framework logging/stderr for diagnostics.

**Alternatives considered**: Hand-writing JSON-RPC/MCP transport was rejected because it duplicates standards work. Returning only JSON text was rejected because it loses output-schema validation and structured-content ergonomics. HTTP transport was rejected because the feature is local, single-user, and explicitly compatible with stdio clients.

## HTTP client and retry policy

**Decision**: Use one `httpx.AsyncClient`; retry safe GET requests for HTTP 429, 408, 500, 502, 503, and 504 plus eligible connect/read timeout and connection failures. Permit three total attempts, at most 10 seconds of cumulative retry delay, and exponential delay starting at 250 ms with jitter and a 5-second per-delay cap. Parse both delta-seconds and HTTP-date `Retry-After`; honor it only when valid and within the remaining retry and request budget. Propagate cancellation immediately.

**Rationale**: Every operation is read-only and repeatable. Finite attempt, delay, and timeout budgets satisfy the constitution while preventing retry storms. `asyncio.CancelledError` must never be wrapped or retried, allowing MCP client cancellation/deadline enforcement to stop HTTP work and pending delays. Tests inject a sleeper, clock, and deterministic jitter source so recovery and exhaustion have no real delay.

**Alternatives considered**: A third-party retry package was rejected because the policy is small and domain-specific. Unbounded `Retry-After` sleeping and retrying all 4xx responses were rejected as unsafe. Fixed delays were rejected because bounded exponential jitter reduces synchronized retry pressure.

## Deterministic snapshot pagination

**Decision**: Materialize each first-page tournament/team result set into a 30-minute process-local traversal snapshot and issue rotating opaque random continuation tokens. Store only normalized match summaries, the canonical query fingerprint, page size, and offset; discard state at the terminal page or expiry.

**Rationale**: The upstream league/team endpoints expose no continuation contract, while the feature requires no repeated/skipped match and excludes newly completed games from an active traversal. A short-lived server-side snapshot provides those semantics without persistent storage and keeps tokens concise. Thirty minutes is sufficient for a local agent to traverse pages but bounded enough to clean abandoned state. Expired or post-restart tokens fail explicitly with restart guidance.

**Alternatives considered**: Offset pagination over refetched upstream results can skip/repeat records after mutation. A stateless keyset token excludes newer matches but cannot preserve a true snapshot if older records are inserted or corrected. Embedding every match ID in a signed token makes tokens grow without bound. Persistent storage conflicts with the feature's local, no-persistence scope.

## Draft ordering and player association

**Decision**: Treat a draft of `n` actions as authoritative only when its order values are exactly `0..n-1`; otherwise preserve upstream array sequence and expose `source_index`, nullable supplied `order`, and `ordering_quality: degraded`. Associate a pick only to a unique same-side player with the same hero ID. Prefer the match player professional `name`, then the pro-player catalog `name`, then an explicit Steam32 account-ID fallback; never read `personaname` for display. Confirm a requested draft is professional by membership in `/leagues/{league_id}/matches`, whose documented purpose excludes amateur leagues.

**Rationale**: The official match schema describes each pick/ban's `is_pick`, `hero_id`, `team`, and `order`, and player records contain `hero_id`, side/slot, `account_id`, professional `name`, and Steam `personaname`. Unique same-side hero matching is deterministic. Exact zero-based coverage detects missing leading, internal, duplicate, and out-of-range order values. Professional-league membership uses an explicit documented OpenDota classification rather than a local heuristic.

**Alternatives considered**: Sorting partially valid order values could silently manufacture chronology. Matching by hero without side can produce ambiguity. Using Steam persona names violates the requested professional identity semantics. Inferring identities or missing actions from other matches was rejected as unauthoritative.

## Name resolution

**Decision**: Normalize by Unicode case folding, converting punctuation/spacing runs to one separator, and comparing normalized league names or team names/tags. Return a unique exact match; otherwise rank normalized substring matches deterministically and return at most 10 candidates.

**Rationale**: This handles harmless case, punctuation, and spacing variation while remaining explainable. Stable numeric IDs remain authoritative, and team candidates include tag and last-match recency to distinguish renamed/reused labels.

**Alternatives considered**: Typo-tolerant edit-distance/fuzzy matching was rejected because the spec explicitly excludes it. Automatically choosing the highest-ranked substring was rejected because ambiguous selection must remain caller-controlled.

## Agent-context protection

**Decision**: Keep discovery records as a fixed slim domain projection and page them at 20 by default/100 maximum. Keep the required draft core always present and expose only `competition`, `result`, `draft_timing`, and `provenance` as validated additive groups.

**Rationale**: Discovery records are already the minimum information needed to choose a match, so another field selector would add complexity without material savings. Draft timing and provenance can be verbose and are separable from the primary ordered-draft scenario. Unknown upstream fields are ignored.

**Alternatives considered**: Returning raw OpenDota records was rejected as unstable and context-heavy. Arbitrary field selection was rejected because it weakens compatibility and validation. Pagination for draft actions was rejected because the 10-match request bound and naturally small professional draft make the cohesive per-match record more usable.

## Sparse diagnostics and duplicate inputs

**Decision**: Silently collapse duplicate requested match IDs at their first occurrence and expose no `duplicates_omitted` field or equivalent diagnostic. Successful responses and records omit generic `status`, empty `warnings`, and absent `error` fields. Every emitted warning or error is non-empty and carries the machine-actionable non-OK `status` inside the diagnostic object; ambiguity uses a warning with `status: needs_selection`, while failures put their outcome status inside `error`.

**Rationale**: Duplicate inputs do not change the requested domain result and therefore do not justify response noise. Sparse diagnostics reduce routine payload size and let the presence of `warnings` or `error` signal that attention is required. Nesting non-OK status with its code and explanation keeps the state and cause inseparable while retaining structured branching for agents. Domain state such as `completeness`, `ordering_quality`, and pagination `terminal` remains explicit because it is not a generic success diagnostic.

**Alternatives considered**: Retaining `status: ok`, empty arrays, null errors, and `duplicates_omitted: []` was rejected as repetitive context overhead. A top-level non-OK status plus a separate diagnostic was rejected because it duplicates state and can become inconsistent. Omitting all status values was rejected because ambiguity and failure callers still need a stable machine-readable outcome.

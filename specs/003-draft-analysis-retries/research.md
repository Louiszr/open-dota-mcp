# Research: Reliable Retries and Team Drafting Report

## Official contract surface

**Decision**: Build the report only from documented read-only OpenDota operations: team identity
and history (`GET /teams/{team_id}`, `GET /teams/{team_id}/matches`), parsed match detail
(`GET /matches/{match_id}`), league catalog (`GET /leagues`), patch constants
(`GET /constants/patch`), hero identities (`GET /heroes`), and professional-player identities
(`GET /proPlayers`). Keep authentication optional through the existing bearer/query-key contract.

**Rationale**: The [official OpenDota OpenAPI document](https://api.opendota.com/api) identifies
these endpoints and describes API keys as optional with increased limits. It documents match IDs,
team IDs, time/result fields, league `tier`, match `patch`, `picks_bans`, players, time series,
`objectives`, and parsed `version`. The existing client already wraps all required endpoints and
caches successful raw JSON before response shaping.

**Alternatives considered**: Explorer SQL was rejected because it is a broad, costly query surface
and not needed for the bounded team workflow. `/proMatches` was rejected because the team endpoint
already supplies the authoritative team history window. Scraping the OpenDota UI or adding a
second data provider was rejected as outside scope and less contract-stable.

## Team lookback and detail retrieval

**Decision**: Sort completed team-history records newest-first by start time and match ID, take the
requested 1-100 quota once, then retrieve details for only those IDs with concurrency 5. Every
quota item contributes to internal selection and aggregate coverage even when detail retrieval,
parsing, or filtering fails; only eligible parsed matches are projected publicly.

**Rationale**: The official team-history endpoint takes only the team ID and exposes no server-side
patch/tier/scenario parameters. Match detail is therefore necessary for patch ID, league tier,
parse version, draft chronology, lanes, and telemetry. Taking the quota before detail/filter work
implements the requested sampling semantics and prevents selection bias from scanning backward for
replacement matches. Existing raw response caching and cross-process population leases keep
repeat analyses from multiplying identical reads.

**Alternatives considered**: Fetching until 100 eligible parsed games were found violates the
lookback definition. Filtering the compact team list alone lacks required metadata. Unbounded
parallel match fetches would aggravate minute limits; fully serial retrieval is safe but
unnecessarily slow for cache hits and healthy upstream service.

## Patch catalog and expression safety

**Decision**: Parse patch catalog entries only when they contain a nonblank human label, a usable
ID, and a valid release date; choose the greatest release date (then stable ID as a deterministic
tie-break) for the default exact label. When a version expression is supplied, compile it before
team detail retrieval with the `regex` package, enforce 64 characters, apply timeout-bounded
`fullmatch` to catalog labels, and convert syntax/timeout failures to actionable validation errors.

**Rationale**: The official constants endpoint mirrors dotaconstants resources and the match schema
defines `patch` as a dotaconstants ID. Catalog position and numeric ID do not constitute a stated
recency guarantee, so a dated selection is required. Python's standard `re` API provides no
evaluation timeout; length alone does not prevent pathological backtracking. Timeout-bounded
full-string evaluation directly satisfies the safety and semantics requirements while retaining
normal regex expressiveness such as `7[.]4[01]`.

**Alternatives considered**: Using the last catalog element or highest patch ID was rejected as an
undocumented recency inference. A hand-written regex safety linter is easy to get wrong. Glob or
literal-list syntax would not implement the specified regular-expression contract. Running
untrusted stdlib regex in the event loop was rejected because cancellation cannot reliably bound a
catastrophic match.

## Tournament tiers

**Decision**: Use the league `tier` string from match detail when present, otherwise the matching
`/leagues` catalog entry internally. Accept distinct non-empty subsets of `premium`, `professional`,
and `amateur`, or the single value `all`; default to `[premium]` and describe it as Tier 1 only.
Unknown or missing tiers fail a named-tier filter without exposing provenance or filter evaluation.

**Rationale**: The OpenAPI `LeagueObjectResponse` exposes `tier` as a string, and current OpenDota
data uses the named labels. The contract does not define numeric Tier 2/Tier 3 mappings. Retaining
the raw value supports auditability and avoids inventing a classification.

**Alternatives considered**: Mapping `professional` and `amateur` to numeric tiers was rejected as
unsupported. Treating unknown values as `all` matches was rejected because it would turn missing
metadata into positive evidence. Accepting `all` alongside named values was rejected as
contradictory input.

## Retry state machine

**Decision**: Use one explicit monotonic retry state machine for safe GETs. Defaults are six total
attempts, fallback bases 2/4/8/16/32 seconds, independently sampled additive 0-20% jitter, 40
seconds per delay, 75 seconds cumulative delay, and 90 seconds total elapsed from immediately
before attempt one. Test attempts, per-delay, cumulative-delay, elapsed, caller-deadline, and
cancellation gates independently before each sleep/attempt.

**Rationale**: OpenDota's API description says an API key increases limits but does not promise a
`Retry-After` header. The feature's source review records a fixed minute bucket and missing guidance
as an expected 429 case, so subsecond defaults are too aggressive. Monotonic elapsed time is immune
to wall-clock adjustment. The full maximum-jitter fallback sum is 74.4 seconds, which fits the
75-second delay budget; the separate 90-second elapsed budget leaves bounded time for requests.

**Alternatives considered**: Unbounded library defaults, immediate retry, and fixed delay were
rejected for storm risk. Reusing cumulative delay as the total elapsed limit ignores request time.
Counting only completed attempts can issue one request after a deadline. Retrying unsafe methods or
all 4xx responses was rejected.

## `Retry-After` interpretation

**Decision**: Accept only a positive finite delay-seconds value or an HTTP date strictly later than
an injected current UTC wall clock. For usable guidance, require the wait to be at least both the
guidance and the jittered safe fallback for the retry number. Invalid/zero/negative/expired/
non-finite values use fallback. If the required wait cannot fit every active budget, stop before
sleeping and expose a sanitized advised-delay number when applicable.

**Rationale**: [RFC 9110 section 10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3)
defines `Retry-After` as delay-seconds or HTTP-date. A positive but repeatedly short value must not defeat safe
backoff. Preserving the larger upstream value respects the service; refusing an over-budget sleep
preserves the caller contract.

**Alternatives considered**: The existing `max(0, float(value))` accepts non-finite numbers and
turns expired dates into zero, allowing immediate retries. Always preferring the header lets a
server-provided `1` create a loop. Silently capping long upstream guidance would retry earlier than
requested and was rejected.

## Retryable failure classes, diagnostics, and cache coordination

**Decision**: Retry HTTP 408, 429, 500, 502, 503, and 504 plus eligible httpx timeout/network
failures, only for repeatable GET operations. Propagate `asyncio.CancelledError` unchanged. Log a
sanitized failure class, attempt number, selected delay source/value, and final reason; return only
a concise public code/message, actionable exhaustion reason, and optional safe retry delay. Keep
retries inside the existing cache population owner.

**Rationale**: This preserves the existing safe status set while making its bounds explicit.
Keeping the state machine below the cache ensures a cache hit has no retry and equivalent misses
have one owner; attached waiters observe the same stored payload or shared failure. Diagnostics are
enough to debug rate-limit behavior without API keys, authorization headers, URLs with secrets, or
full bodies.

**Alternatives considered**: Per-tool retries would duplicate attempts and policy. Letting cache
waiters fall back to independent requests while a live owner sleeps defeats coordination. Logging
raw headers/bodies was rejected as noisy and potentially sensitive.

## Parse status and compact coverage

**Decision**: Treat a positive integer OpenDota `version` as the primary parsed marker. Validate
each evidence family separately rather than treating `version` as proof every field exists.
Unparsed and failed-detail items consume quota and contribute to aggregate coverage but do not
become public outcomes. Only failures preventing construction of report context are request-wide
errors.

**Rationale**: The official match schema calls `version` the parse version and makes many detailed
fields optional or nullable in practice. Parsed records can still be incomplete. Aggregate parsed
and unparsed counts make sampling bias visible without serializing per-match diagnostic records.

**Alternatives considered**: Defining parsed as “has picks_bans” confuses basic draft availability
with replay parsing. Omitting coverage entirely hides bias. Returning every unparsed/filtered item
with statuses, reasons, and filter stages was rejected as response bloat. Failing the full report
on one bad match makes a 100-match workflow fragile.

## Draft chronology, players, and matchup knowledge

**Decision**: Preserve source array order and use integer action order when present. Associate picks
with exactly one same-side player sharing the hero ID, using match professional name then pro-player
catalog name for the public player string. Treat `is_pick` as the phase (`pick` or `ban`). Reconstruct
rounds from the API-supplied type/team/order fields: for each team independently, take its globally
ordered action subsequence, group consecutive equal types, and number pick runs and ban runs
independently from 1. Assess matchup knowledge only with authoritative chronology, unique
player/hero/lane joins, and a complete opposing final lane.

**Rationale**: The official match schema documents `picks_bans` fields (`is_pick`, `hero_id`,
`team`, `order`) and player fields (`hero_id`, `account_id`, slot/side, `name`, `lane_role`). It does
not provide a named stage, but the requested round definition depends only on transitions between
the supplied pick/ban types in each team's own subsequence. It therefore needs no patch-specific
Captains Mode schedule. Both teams naturally receive their own pick round 1 and ban round 1.

**Alternatives considered**: Sorting partial/duplicate order values manufactures chronology.
Matching hero without side or choosing among duplicate player candidates guesses identity.
Using one global round counter would make one team's numbering depend on the other team's action
cadence. A patch-specific Captains Mode schedule remains unnecessary for this run-based definition.

## Supported lane and checkpoint observations

**Decision**: Use `lane_role` 1/2/3 as safe/mid/off. For aligned player series, select the greatest
`times[i] <= checkpoint` internally. `xp_t` and `lh_t` supply 10-minute lane differences; `gold_t`
supplies accurately named per-hero total gold; and top-level `radiant_gold_adv` supplies team gold
advantage with sign inversion for the analyzed-team perspective. Do not label `gold_t` as exact net
worth.

**Rationale**: The [official match response schema](https://api.opendota.com/api) describes
`times` as corresponding to the other time arrays, `gold_t` as total gold over time, `xp_t` as
experience, `lh_t` as last hits, and `radiant_gold_adv` as Radiant gold advantage at each minute.
The [official parser](https://github.com/odota/parser/blob/master/src/main/java/opendota/Parse.java)
reads both `m_iNetWorth` and `m_iTotalEarnedGold` but writes the latter to `gold_t`. OpenDota's
[player graph](https://github.com/odota/web/blob/master/src/components/Visualizations/Graph/MatchGraph.tsx)
is titled Gold and reads `${type}_t`; another story component informally calls summed `gold_t` a
net-worth difference, but that UI copy does not override the parser/API field semantics.

**Alternatives considered**: Calling `gold_t` exact net worth was rejected because the parser keeps
the source concepts separate. Returning an unavailable placeholder was rejected as schema bloat.
Using the final value for a missing checkpoint misstates time; interpolation invents precision.

## Structures and objectives

**Decision**: Build structure ledgers only from timestamped destruction events with recognized
building keys that identify owning side, lane, tier, and barracks type. Use final structure
bitmasks only as an internal validation signal. For objectives, establish Roshan times from
`CHAT_MESSAGE_ROSHAN_KILL` and Tormentor times from `CHAT_MESSAGE_MINIBOSS_KILL`, each with an
explicit recognized team. Omit unattributed events. Return an empty list only when zero is
established and `null` otherwise. Use the catalog release date of Valve's
[7.33 patch](https://www.dota2.com/patches/7.33) as the Tormentor applicability boundary.

**Rationale**: The OpenAPI match schema leaves objective item shape open, but OpenDota's official
parser explicitly stores `CHAT_MESSAGE_MINIBOSS_KILL` in `objectives` with time, player slot, and
team, and the [official web client](https://github.com/odota/web/blob/master/src/components/Match/MatchLog.tsx)
renders that event as “destroyed the Tormentor.” Five sampled current parsed professional matches
returned the same time/team shape. The same parser stores
timestamped `building_kill` and Roshan events. These first-party implementations plus live payloads
are sufficient to support the narrowly recognized event types.

**Alternatives considered**: Inferring checkpoint destruction from final bitmasks was rejected
because final state contains no timestamp. Assigning an objective from map location or selected
team side guesses ownership. Treating an absent objectives array as zero conflates missing parse
evidence with no event.

## Live parsed-match schema audit

**Decision**: Keep a proposed public field only when it is directly present in a current parsed
payload, resolvable through a documented OpenDota constants/reference endpoint, or deterministically
derived from those fields without external game knowledge.

The audit used `GET /proMatches` to select parsed match `8918785800`, then
`GET /matches/8918785800`, and sampled four adjacent parsed professional matches for objective and
timeline consistency.

| Public information | OpenDota evidence | Decision |
|---|---|---|
| Match/date/duration/team/opponent/side/result | match identity, team objects/IDs, `start_time`, `duration`, `radiant_win` | Keep |
| Tournament name/tier | live `league.name` and `league.tier` | Keep |
| Patch label | match `patch` joined to `/constants/patch` | Keep label only |
| Parse coverage | match `version` | Keep aggregate counts only |
| Ban order | ordered `picks_bans` with `is_pick` and `team` | Keep |
| Draft hero/team/order | `picks_bans`; hero name joined through `/heroes` | Keep |
| Draft type and per-team round | `picks_bans.is_pick`, `team`, and global `order`; round is the 1-based run number for that type in the team's subsequence | Keep |
| Picked player | unique same-side player with final `hero_id`; name/pro-player references | Keep optional name |
| Lane participants | player `lane`/`lane_role`, team side, and hero | Keep |
| 10-minute XP/last hits | aligned `times`, `xp_t`, and `lh_t` | Keep |
| Hero 10/20 exact net worth | only final `net_worth`; interval parser stores total earned gold in `gold_t` | Drop exact-net-worth claim |
| Hero 10/20 total gold | aligned `times` and `gold_t` | Keep as gold |
| Team 10/20 gold difference | `radiant_gold_adv`, equal to summed `gold_t` difference in the sample | Keep |
| Structures through 10/20 | timestamped `building_kill` objective entries with owning-side keys | Keep recognized keys |
| Roshan through 25 | `CHAT_MESSAGE_ROSHAN_KILL` time/team | Keep |
| Tormentor through 25 | `CHAT_MESSAGE_MINIBOSS_KILL` time/team; official UI maps it to Tormentor | Keep |

**Rationale**: The live payload contained 10 aligned player `times`/`gold_t`/`xp_t`/`lh_t` series,
24 ordered draft actions, league tier/name, timestamped building/Roshan/Tormentor events, and all
core match identities. Summed hero `gold_t` exactly matched `radiant_gold_adv` at minutes 10 and 20.

**Alternatives considered**: A single payload without source validation was insufficient. Conversely,
requiring every objective property to be detailed in the generated OpenAPI schema would discard a
field that the official parser and UI intentionally produce and consume.

## Response shaping and immutable pagination

**Decision**: Add one tool, `analyze_pro_team_drafts`, with a lean eligible-match core and additive
`draft`, `lanes`, `economy`, `structures`, and `objectives` groups. Materialize eligible matches and
aggregate coverage before slicing; store them in the existing 30-minute, 32-snapshot registry.
Page 10 by default and 25 maximum using rotating opaque, request-bound cursors. Repeat only team,
applied filters, and compact coverage on each page.

**Rationale**: Team/match IDs remain where follow-up calls use them; team tags, patch/hero/league/
account IDs, filter evaluations, provenance, sources, completeness, warning/reason wrappers, and
request/page echoes do not. Each optional group is cohesive and independently selectable. Cursor
continuation avoids re-fetching upstream data or requiring external JSON processing.

**Alternatives considered**: Returning raw match JSON, arbitrary field names, or all groups by
default was rejected for context size and schema instability. Recomputing each page can change
coverage and match order. Stateless cursors cannot preserve corrected/mutating match records. A
new persistent report database is unnecessary.

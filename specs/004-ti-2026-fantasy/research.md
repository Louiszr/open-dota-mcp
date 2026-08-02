# Research: TI 2026 Fantasy Analysis

## Official OpenDota surface

**Decision**: Use the official OpenDota contract and source at revision
`2d67379fbba90b2fd015c6f0f4080d394a5741e9` (opendota github commit). Resolve professionals through `GET /proPlayers`,
discover player-specific match IDs through the documented player-match history operation, and
hydrate every candidate through `GET /matches/{match_id}`. Load `/constants/patch`, league, hero,
and team references through existing cached operations. Verify that each returned record is a
completed professional map containing the selected account. Professional eligibility is proven
independently of player identity: require a positive match `leagueid` that resolves in authoritative
league metadata and reject missing, zero, unknown, or contradictory provenance. This gate is
unconditional and precedes all caller filters; tier `all` ranges only over the verified league set.

**Rationale**: `/proPlayers` supplies stable Steam32 `account_id` values and professional names.
Player history is the focused way to seed IDs, while match detail supplies parsed player rows,
league/tier, series, teams, score, patch, and richer statistics. The existing client already owns
safe GET retry, optional authentication, cache coordination, and response validation. Player
history can mix public and league records, so treating `/proPlayers` membership or participation as
professional evidence would leak a pro player's pub games. Positive, resolvable, consistent league
provenance gives the implementation a fail-closed discriminator without inventing an OpenDota
parameter or relying on a caller-controlled toggle.

**Alternatives considered**: Global `/proMatches` paging is authoritative and useful as a fallback
but inefficient for one player's sparse appearances. Player history alone mixes record classes and
does not promise professional context. Professional-player identity, parsed status, or team IDs do
not distinguish pubs. Treating absent provenance as eligible would violate the no-pub guarantee.
Explorer SQL is broad and brittle. UI scraping and a second match provider are outside scope.

Primary sources: [API specification](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/spec.ts),
[player response](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/responses/PlayerObjectResponse.ts),
[match response](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/responses/MatchResponse.ts),
and [match builder](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/util/buildMatch.ts).

## Bounded post-filter collection

**Decision**: Traverse player history newest-first in finite source pages, hydrate with concurrency
5, and stop when the requested 1-100 eligible maps are established, history is exhausted, or a
finite request/history budget is reached. Filter cheap authoritative values before hydration, but
apply the public `match_count` only after completed/pro/player-row, patch, inclusive-date, and tier
filters. Return coverage and a truncation warning whenever the scan cannot prove exhaustion.

**Rationale**: Fixed overfetch cannot guarantee the newest N post-filter maps. Unlimited scanning
can violate caller deadlines and OpenDota operational limits. Explicit bounded coverage preserves
both semantics and safety without adding public pagination to a finite result.

**Alternatives considered**: Taking N before filters violates FR-003. Silently scanning a fixed
multiple can claim false completeness. Caller cursors are unnecessary because the public result is
already bounded and the requested workflow expects one evidence call.

## Team lineup source and position inference

**Decision**: Add a focused team-to-player tool using existing `GET /teams/{team_id}/matches`,
`GET /matches/{match_id}`, `GET /teams/{team_id}/players`, and `GET /proPlayers` reads. Inspect the
newest completed match first and at most four older completed records only when parsing or lineup
evidence is inconclusive. A candidate match must be parsed, identify the requested team's side, and
contain exactly five distinct positive account IDs. Before returning it, require exact set equality
with exactly five team-player records explicitly marked `is_current_team_member=true`. A mismatch
returns `lineup_mismatch` immediately because it may represent a stand-in or roster change; an older
match cannot safely repair that freshness conflict.

Infer positions only from a clean 2-1-2 distribution in the selected match. The unique midlane
player is position 2. Rank the two safelane players by distinct last-hit samples at or before 10:00
as positions 1 then 5, and the two offlane players as positions 3 then 4. Missing/tied samples,
roaming, or another lane distribution leaves unsupported positions null. Return the source match,
lane/farm evidence, coverage, and inference status; describe the result as a latest observed lineup,
not an authoritative current roster.

**Rationale**: The official team-player endpoint returns historical participants with
`is_current_team_member`, but no position. The pro-player catalog documents `fantasy_role` only as
core/support, while live values include values outside that documented range, so it cannot support
positions 1-5. Parsed match rows expose stable account IDs, side, `lane_role`, and time-series last
hits. Combining current-member equality with conservative match evidence detects likely stand-ins
or roster changes and gives the fantasy tool stable IDs without requiring an agent to inspect a
large drafting report.

**Alternatives considered**: Extending `analyze_pro_team_drafts` would bind a focused identity
lookup to patch/tier filters, pagination, and a much larger report. Returning the team-player
endpoint alone has no positions and includes historical members. Treating `fantasy_role`, player
slot, final farm, hero archetype, or historical frequency as positions overstates upstream
semantics. Continuing to older matches after a current-member mismatch can hide the exact
stand-in/roster-change condition the cross-check is intended to surface.

Primary sources: [team-player operation and query](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/spec.ts#L2306-L2340),
[team-player response](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/responses/TeamPlayersResponse.ts),
[professional-player response](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/responses/PlayerObjectResponse.ts),
and [parsed match response](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/responses/MatchResponse.ts).

## Patch, tournament, and series semantics

**Decision**: Resolve `match.patch` through the dated patch catalog; choose the latest dated label
when no expression is supplied. Reuse the draft-analysis full-string, 64-character, 50 ms regex
contract. Preserve the raw league tier and accept distinct named subsets of `premium`,
`professional`, and `amateur`, or only `all`; default `[premium]`. Preserve only trustworthy
upstream `series_id`; missing or conflicting series identity is null.

**Rationale**: OpenDota computes patch as a dotaconstants array index, not a display label. League
tier is unconstrained upstream text. Neither time proximity, opponent, series type, nor match ID is
a sound substitute for series identity.

**Alternatives considered**: Highest patch ID/last catalog entry is undocumented recency. Numeric
tournament-tier remapping and inferred series groups fabricate meaning.

Primary sources: [patch computation](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/util/compute.ts#L290-L304),
[constants contract](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/spec.ts#L2618-L2682),
and [league schema](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/sql/create_tables.sql#L264-L292).

## Raw fantasy-stat availability

**Decision**: Directly consume compatible parsed fields for kills, deaths, assists, last hits,
denies, GPM, `obs_placed`, `camps_stacked`, `rune_pickups`, and fractional `stuns`. Consume explicit
parsed tower/Roshan/courier kill counts and `item_uses.smoke_of_deceit` only when present. Derive an
individual Tormentor last-hit count from `CHAT_MESSAGE_MINIBOSS_KILL` objective events when each
event has an expanded `player_slot` that uniquely maps to a match player and its team agrees with
that player's side. Compute teamfight participation locally from kills, assists, and verified team
score. Keep Madstones, Watchers, and lotuses null. Treat First Blood as nullable unless parsed
evidence establishes the credited player or reliably establishes another player.

**Rationale**: The current public MatchResponse/DB contract exposes the direct fields but not
dedicated columns for the newer fantasy concepts. Tormentor is the exception: OpenDota's official
parser maps `CHAT_MESSAGE_MINIBOSS_KILL.player1` to `slot`, expands it through the parser's
slot-to-player-slot map, retains the killing `team`, and stores the event in the public `objectives`
array. A live parsed professional match (`8918785800`, checked 2026-08-02) returned
`team=2`, `slot=0`, and `player_slot=0`, which uniquely joined to account `81581812` on hero ID 9.
This supports individual/hero credit even though feature 003 intentionally projects only team event
times. If an applicable match has a complete objective array and every Tormentor event is
attributed, absence for the selected player is a verified zero; otherwise the individual count is
null. Purchases are not Smoke uses; generic wards are not observer wards; OpenDota `stuns` has
narrower documented hero-disable semantics than the spec's broadest meaning, so it must be caveated
and rejected where semantic compatibility cannot be established.

**Alternatives considered**: Using only the Tormentor event's team would not establish the player
who received fantasy credit. Using raw `slot` as `player_slot`, array position, hero proximity, or
team membership would guess attribution. Zero-filling a missing or partly unattributed objective
ledger would erase the required unavailable distinction.

### Re-audit of Madstones, Watchers, and lotuses

The pinned OpenDota core and parser contain no selected/exported sendprop named
`n_mMadstonesCollected` (or a matching Madstone collection field), no Watcher objective processor,
and no per-player lotus pickup processor. Core's generated GC protobuf does define fantasy-player
fields for Watchers, lotuses, Tormentors, couriers, title stats, and Madstones, but that GC message
is not part of the public `MatchResponse` or parser output. A replay may contain a runtime sendprop
that is absent as a source-code literal; consuming it would still require a new upstream/custom
replay parser and is outside this feature's OpenDota API contract.

The public 2026 calculator at `bydoodle.github.io/dota-fantasy-2026` provides useful proxy leads,
not scoring-compatible replacements. Its GitHub link currently resolves to the archived 2025
implementation, which maps `item_uses.madstone_bundle` to Madstones and
`ability_uses.ability_lamp_use` to Watchers. A live parsed 2026 professional match confirms both
counters can occur in OpenDota player rows. However, bundle uses are not collection events, while
lamp uses combine neutral and enemy Watcher captures without target/state evidence. The calculator
author likewise labels Watchers inaccurate and Madstones/lotuses unavailable in the current 2026
update. No compatible per-player lotus collection signal was found; lotus item use would describe
consumption instead of pickup. Therefore all three fields remain null and each gets one focused,
deduplicated root warning.

Primary sources: [MatchResponse player fields](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/api/responses/MatchResponse.ts#L230-L810),
[computed statistics](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/util/compute.ts#L100-L149),
[database player columns](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/sql/create_tables.sql#L49-L147),
[Tormentor event construction](https://github.com/odota/parser/blob/84a102cdbed848ec514a586ae1e1ada802fdc79e/processors/processExpand.mjs#L473-L488),
and [objective persistence](https://github.com/odota/parser/blob/84a102cdbed848ec514a586ae1e1ada802fdc79e/processors/populate.mjs#L17-L29),
[GC fantasy-player protobuf](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/proto/dota_gcmessages_common.proto#L1107-L1135),
[legacy calculator mappings](https://github.com/bydoodle/dota2fantasy/blob/973d3f98860f94c842af70ef9539595db90a4f5d/main.py#L491-L512),
and the [2026 calculator update](https://www.reddit.com/r/DotA2/comments/1vcpcvr/update_fantasy_league_2026_calculator/).

## Null, zero, false, and formula evaluation

**Decision**: Required raw keys always serialize. Missing or incompatible evidence is null;
legitimate numeric zero remains zero; First Blood false is emitted only from reliable attribution.
Computed points are null when required input is null. Deaths applies its floor, First Blood false
scores zero, participation is null for a zero denominator, and fractional stun points remain
fractional. Canonical formula operations are typed data rather than evaluated text.

**Rationale**: This gives clients deterministic arithmetic without turning missing evidence into
plausible scores. Typed operations keep the service and resource in parity and avoid unsafe formula
parsing.

**Alternatives considered**: Truthiness-based mapping confuses false/zero/null. A free-form
expression evaluator adds security and drift risk. Repeating full formula prose per match bloats
the optional group.

## Player identity resolution

**Decision**: A positive account ID is authoritative but must resolve in `/proPlayers`. For names,
reuse NFKD/casefold/punctuation/space normalization and auto-select only when exactly one normalized
exact professional `name` matches. Exact collisions or substring matches return at most 10 stable
candidates; blank/no-match inputs return structured errors. Current team data is candidate context,
not historical truth.

**Rationale**: Professional names change and can be reused. Stable IDs make the evidence request
unambiguous and preserve the two-call disambiguation workflow.

**Alternatives considered**: Persona names, fuzzy edit distance, or unique substring auto-selection
can silently choose the wrong player.

## MCP tool and resource shape

**Decision**: Add `get_pro_player_fantasy` with only `fantasy_scoring` as a cohesive additive group.
Expose a fixed JSON resource at `opendota://fantasy/ti-2026/scoring` using FastMCP's resource
decorator, explicit MIME type, and read-only/idempotent annotations. Load package data with
`importlib.resources`; keep edition and sources in the content.

**Rationale**: The slim core already contains the raw evidence requested for every analysis. Raw
score projection is the only optional per-map expansion. A static resource is discoverable,
offline, deterministic, and independently versioned without inflating every tool call.

**Alternatives considered**: Markdown-only rules are brittle for calculation. Live web retrieval is
not deterministic. An HTTPS or file URI misrepresents server-local content. A URI template and
arbitrary raw-field selectors are YAGNI.

Primary sources: [MCP resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
and [FastMCP resources](https://gofastmcp.com/servers/resources).

## TI 2026 rule provenance and aggregation

**Decision**: Treat FR-015's 18 formulas and FR-018's multipliers as the supplied baseline edition.
Every fact in the resource has `official`, `community_verified`, or `unknown` evidence status,
source references, and a caveat; no unverified numeric trait/title effect is filled in. Define stage
aggregation over confirmed series only: take up to two highest maps per series, sum them, then take
the player's best confirmed series. Unknown-series maps remain ungrouped evidence. Document paired
Core and paired Support banner contribution with its evidence status.

Freeze the complete known trait/title name inventory and all supportable effect, prerequisite,
stacking, and ordering claims during planning, before `/speckit-tasks`. Implementation is limited to
serializing that evidence into the installed resource and enforcing schema/source/formula parity.
Facts whose names are known but whose exact behavior is not verified are still collected now with
null numeric values and `unknown` status; they are not left for implementation-time research.

The planning inventory is five traits (`Fractal`, `Friendly`, `Vampiric`, `Unique`, `Benevolent`),
eight prefixes (`Otherworldly`, `Emerald`, `Golden`, `Heroic`, `Cerulean`, `Royal`, `Crimson`,
`Elemental`), and eight suffixes (`the Tormented`, `the Flayed Twins Acolyte`, `the Patient`,
`the Underdog`, `the Decisive`, `the Clutch`, `the Lucky`, `the Cruel`). The guide's `Unique +30%`
and `the Underdog +6%` claims are retained as community-verified values with caveats. Prefix
percentages shown beside players are observed eligibility frequencies rather than title modifier
amounts and cannot be copied into `numeric_effect`. Other exact numeric effects and incomplete
mechanics remain null/`unknown` in the initial edition.

**Rationale**: No accessible Valve page was found that publishes the full exact 2026 numeric table.
The status model preserves useful supplied/community rules without overstating authority. Series
non-inference follows the match contract.

**Alternatives considered**: Calling all supplied facts official or guessing missing effects would
violate provenance requirements. Server-side lineup optimization is outside scope.

Supporting sources: [Valve 2025 fantasy announcement](https://store.steampowered.com/news/posts/?appids=570&enddate=1758062559&feed=steam_community_announcements),
[Steam Support scoring note](https://help.steampowered.com/en/faqs/view/28CE-C791-6C99-06D5),
and [TI 2026 community guide](https://www.reddit.com/r/DotA2/comments/1vble84/fantasy_league_2026_guide/).

## Authentication, retry, and caching

**Decision**: Preserve public no-key access and optional secret API key. Reuse the existing safe-GET
policy for eligible transport/408/429/5xx failures, honoring proxy `Retry-After`, finite jittered
backoff, caller cancellation/deadline, and actionable exhaustion. Cache/deduplicate catalogs,
history, and match details; limit hydration concurrency to 5.

**Rationale**: Current OpenDota defaults are 60 requests/minute and 3000/day without a key and 300
requests/minute with a key, but deployments can vary and current core does not send `Retry-After`.
Fan-out therefore needs bounded concurrency and caching, not hard-coded assumptions that guidance
will exist.

**Alternatives considered**: Retrying all 4xx errors, immediate retry, unbounded fan-out, or logging
the API key are unsafe.

Primary sources: [OpenDota request handling](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/svc/web.ts#L413-L510)
and [configuration defaults](https://github.com/odota/core/blob/2d67379fbba90b2fd015c6f0f4080d394a5741e9/config.ts#L58-L64).

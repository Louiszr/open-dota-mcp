# Implementation Plan: TI 2026 Fantasy Analysis

**Branch**: `004-ti-2026-fantasy` | **Date**: 2026-08-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-ti-2026-fantasy/spec.md`

## Summary

Add `get_pro_team_roster`, a focused read-only bridge from a professional team to the five account
IDs in its newest usable parsed lineup, with conservative lane/ten-minute-farm position inference.
Add `get_pro_player_fantasy`, which resolves a professional player, scans a
bounded newest-first player-match history, verifies completed professional maps through OpenDota
match detail plus authoritative league evidence, rejects public or unverified matches with no
caller override, applies patch/date/tier filters, and returns compact player-relative context plus all
18 nullable raw fantasy inputs. One additive `fantasy_scoring` group computes pre-modifier points.
Add a package-static JSON MCP resource at `opendota://fantasy/ti-2026/scoring` for formulas, quality
tiers, aggregation, traits, titles, evidence status, and sources. No fantasy loadouts are inferred.

## Technical Context

**Language/Version**: Python 3.13+

**Primary Dependencies**: FastMCP, httpx, Pydantic, `regex`, and Python standard-library asyncio,
datetime, decimal/number handling, enum, JSON, and `importlib.resources`

**Storage**: Existing per-user SQLite upstream-response cache; one immutable package JSON resource.
No new mutable or user-domain storage.

**Testing**: pytest and pytest-asyncio with `httpx.MockTransport`, explicit OpenDota fixtures,
in-memory FastMCP tool/resource contract tests, temporary cache stores, and stdio integration tests

**Target Platform**: Local macOS or Linux process launched by Codex or another MCP client over stdio

**Project Type**: Single Python package providing a local read-only MCP server and cache CLI

**Performance Goals**: Resolve a lineup from at most five completed team-history records and return
exactly five compact players; return at most 100 fantasy maps (20 default); process newest history in bounded
pages; hydrate details with concurrency 5; stop once enough eligible maps are established or the
bounded history/execution budget is exhausted; issue no network request when reading scoring rules

**Constraints**: Latest observed lineup, not authoritative current roster; positions inferred only
from a clean parsed 2-1-2 lane distribution and distinct ten-minute side-lane farm; the match's
five IDs must equal the team endpoint's five explicit current members; mismatches cannot infer; ambiguous
positions are null; post-filter newest-first fantasy limit; inclusive UTC dates; timeout-bounded 64-character
patch expressions; Tier 1 defaults to `premium`; no caller pagination; explicit null/zero/false
semantics; professional-league provenance is mandatory before all caller filters and `all` never
includes pubs; no public-match input; no series or modifier inference; finite existing retry/deadline policy; protocol-only
stdout; deterministic offline tests

**Scale/Scope**: Two new tools and one static resource, one five-player lineup from a fixed
five-record scan plus one current-member cross-check, 18 raw statistics/formulas, five quality tiers, one optional response group, at
most 10 identity candidates, and a bounded professional-match history traversal per fantasy call

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

- **Scope — PASS**: One lineup bridge, one evidence tool, and one rules resource directly serve the scenarios. Existing
  caches, retry policy, identity normalization, filters, and mapping patterns are reused. There is
  no optimizer, persisted roster state, write operation, OAuth, replay parser, or speculative loadout store.
- **OpenDota contract — PASS**: [research.md](research.md) pins the official OpenDota source revision
  and verifies professional identities, team-player membership, history/detail operations,
  lane/time-series evidence, patch/tier/series fields, authentication, limits, and raw-stat availability.
  Safe GETs retain finite retry, `Retry-After`,
  cancellation/deadline, caching, deduplication, and concurrency behavior.
- **Testing — PASS**: Every new public model/helper, tool, and resource has planned pytest coverage.
  Risk tests cover all formulas, nullable evidence, strict booleans, individual Tormentor event
  attribution, lineup team-side validation, clean/ambiguous position inference, player ambiguity,
  post-filter limits, chronology, history bounds, partial failures, series non-inference, reference parity,
  and mixed professional/public histories under every tier selection including `all`.
- **Quality — PASS**: Public signatures remain fully typed and Google-documented. Rule identifiers
  are canonical constants/data, resource JSON is schema-validated, and Ruff check/format remain
  zero-warning gates.
- **Independent QA — PASS (implementation gate)**: `/speckit-implement` must use a separate
  non-implementing QA sub-agent to audit coverage and run Ruff check, Ruff format, and all pytest.
- **Interoperability — PASS**: The design uses standard FastMCP tool and resource contracts,
  explicit `application/json`, read-only/idempotent annotations, protocol-only stdout, and both
  in-memory and Codex-compatible stdio validation.
- **Agent ergonomics — PASS**: Team-to-player resolution is one bounded call returning five IDs;
  no draft report or large upstream roster requires post-processing. The fantasy default response
  is a bounded compact map collection. The sole
  cohesive opt-in group is `fantasy_scoring`; arbitrary upstream fields are excluded. Caller
  pagination is inapplicable because `match_count` is a finite 1-100 post-filter collection bound;
  the tool reports history coverage/truncation rather than silently claiming exhaustive results.

### Post-design re-check

Phase 1 preserves every gate. The contract keeps all 18 raw-stat keys explicit so unavailable is
not confused with omission, emits one warning per unavailable scoring statistic, and references canonical formulas
instead of copying prose into every map. The static resource is installed with the package and
requires no live web access. Unknown trait/title facts remain nonnumeric and source-labeled. No
constitution exception is required. Professional eligibility is fail-closed, precedes every
caller-controlled filter, and has no schema escape hatch, so response shaping cannot admit pubs.
The lineup contract exposes inference evidence and source
match identity, bounds scanning at five completed records, rejects membership mismatches, and
nulls ambiguous positions rather than
presenting a latest observed lineup as current roster truth.

## Project Structure

### Documentation (this feature)

```text
specs/004-ti-2026-fantasy/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── mcp-tool.md
│   ├── roster-tool.md
│   └── scoring-resource.md
└── tasks.md                    # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
README.md
src/open_dota_mcp/
├── clients/opendota.py         # Player history and team-player operations; safe retry/cache boundary
├── cache/
│   ├── policy.py               # Player-history and team-player freshness classification
│   └── store.py                # Allowlisted cached operation
├── models/
│   ├── fantasy.py              # Typed request, identity, context, raw stats, scores, response
│   └── roster.py               # Latest-lineup request, player inference, coverage, response
├── resources/
│   ├── __init__.py
│   └── ti_2026_fantasy.json    # Installed canonical reference data
├── fantasy_rules.py            # Typed rule keys/formula operations and parity validation
├── services/
│   ├── fantasy.py              # Resolution, collection, filtering, mapping, score projection
│   ├── identity.py             # Professional-player and team name resolution
│   └── roster.py               # Team resolution, bounded latest-lineup scan, position inference
└── server.py                   # Register fifth/sixth tools and scoring resource
tests/
├── fixtures/opendota/fantasy.json
├── unit/
│   ├── test_fantasy_mapping.py
│   ├── test_fantasy_models.py
│   ├── test_roster_mapping.py
│   ├── test_identity_resolution.py
│   ├── test_opendota_client.py
│   ├── test_cache_identity.py
│   └── test_cache_policy.py
├── contract/
│   ├── test_fantasy_tool.py
│   └── test_roster_tool.py
└── integration/
    ├── test_fantasy_journey.py
    ├── test_roster_to_fantasy.py
    └── test_stdio.py
```

**Structure Decision**: Keep the existing single `src`-layout package. A dedicated fantasy model
and service avoid coupling player evidence to team draft analysis. Canonical rule operations are
shared by the scorer and package resource validation so formula identifiers cannot drift. A small
roster service reuses existing team history/detail/catalog client operations without expanding the
draft-analysis response or coupling lineup lookup to its patch/tier/report pagination contract.

## Implementation Design

### Latest observed lineup and position inference

1. Validate exactly one team selector. Reuse existing normalized team identity resolution and
   bounded ambiguity candidates; a stable team ID avoids a preliminary discovery call.
2. In parallel, read the team's documented match history and `/teams/{team_id}/players`. Require
   exactly five distinct positive IDs explicitly marked `is_current_team_member=true`; otherwise
   return `current_roster_unavailable` without position inference.
3. Normalize completed records newest first, take at most five, and hydrate details sequentially
   newest first. Stop at the first usable parsed match whose
   requested-team side is unambiguous and contains exactly five distinct positive account IDs.
   Advance to an older record only when the newer record is unparsed or inconclusive.
4. Compare the selected match's five-ID set with the current-member set. If they differ, return
   `lineup_mismatch` with the source match and coverage, infer no players or positions, and do not
   search older matches; a mismatch may be a stand-in or roster change that older evidence cannot
   safely resolve.
5. Return those five IDs when the sets match, even when some positions cannot be determined. Resolve professional names
   from `/proPlayers`; a missing catalog name remains null and never changes lineup membership.
6. Infer positions only for a clean match-derived 2-1-2 distribution. The unique mid player is
   position 2. Within safelane, distinct last-hit samples at or before 10:00 rank the higher player
   as position 1 and lower as position 5; within offlane they rank as positions 3 and 4. Missing,
   tied, malformed, roaming, or unexpected distribution evidence produces null for unsupported
   positions and one focused warning.
7. Include source match ID/start time, examined/parsed coverage, lane and ten-minute-last-hit
   evidence, and `inferred`/`ambiguous` status. Do not use `fantasy_role`, player-slot ordering,
   final farm, or historical frequency as position evidence, and do not call the result current.
8. If all five records are unusable, return `lineup_unavailable` with bounded coverage. Reuse the
   existing finite retry/cache/cancellation boundary; malformed individual records do not expand
   the fixed scan.

### Collection and filtering pipeline

1. Validate exactly one player selector, count, dates, tier values, include values, and the
   timeout-bounded patch expression before detail reads. Load the professional, patch, league,
   hero, and team reference catalogs through the existing cache boundary.
2. Resolve a stable account ID directly against `/proPlayers`, or normalize a professional name
   and auto-select only one exact normalized match. Otherwise return at most 10 deterministic
   candidates and require the account ID.
3. Traverse the verified player-specific match history newest-first with `limit`/`offset` in bounded source
   pages, deduplicate IDs, and cheaply reject authoritative date mismatches. Hydrate candidate
   `/matches/{match_id}` records with concurrency 5 until the requested post-filter count is met,
   history ends, or the documented execution/history ceiling is reached.
4. Apply an unconditional professional-provenance gate before caller filters: require the hydrated
   match to carry a positive league ID that resolves to authoritative league metadata, with no
   contradictory match/league evidence. A resolved professional player, parsed detail, or team IDs
   do not establish this. Exclude public matchmaking and missing/zero/unknown/contradictory league
   provenance; expose no override, and interpret tier `all` only as all tiers within this verified
   set. Then retain completed maps containing the selected player row. Resolve patch labels
   by catalog date/ID, tournament raw tier from verified match/league evidence, team/opponent/result from
   player slot and radiant/dire context, and series only from trustworthy upstream `series_id`.
   Missing optional context remains null unless an active filter requires it.
5. Apply patch/date/tier filters only after the professional gate. Sort eligible maps by UTC start
   time then match ID newest-first and apply `match_count` last.
   Return sparse record warnings and explicit examined/exhausted coverage. If a finite source cap or
   partial upstream failure prevents exhaustive proof, return only established maps with a focused
   truncation warning; never relabel that result as complete.

### Raw statistics and score projection

- Map direct compatible fields for kills, deaths, assists, last hits, denies, GPM, observer wards,
  camps, runes, fractional stuns, and parsed tower/Roshan/courier last-hits. Map Smoke uses only from
  explicit `item_uses.smoke_of_deceit` evidence. Derive individual Tormentor last-hits from
  `CHAT_MESSAGE_MINIBOSS_KILL` objective events whose expanded `player_slot` uniquely matches the
  selected player row and whose team agrees with that player's side.
- Compute participation from player kills/assists and the player team's verified score only when
  the denominator is positive. A zero denominator produces null plus one focused map warning.
- Preserve `0` and reliable `false`; use null for missing or semantically narrower evidence.
  Madstones, Watchers, and lotuses remain null under the current public OpenDota contract.
  `item_uses.madstone_bundle` is a use-event proxy, `ability_uses.ability_lamp_use` combines neutral
  and enemy Watcher captures, and lotus item-use counters measure consumption rather than pickup;
  emit one root warning for each unavailable scoring statistic represented in the result.
  The audited `dota2-fantasy-optimizer-2026` repository does not improve this contract: it embeds
  precomputed community-table scores and contains no match-ingestion implementation or per-value
  provenance. Its likely upstream legacy calculator reads both proxy counters from OpenDota, not
  STRATZ, but also labels Madstones and Watchers inaccurate. Do not import either aggregate table
  or proxy as raw per-map fantasy evidence.
  Tormentor last-hits are zero only for an applicable, complete, fully attributed objective ledger;
  a missing ledger or any unattributed Tormentor event keeps the value null. First Blood is false
  only when another player is reliably credited.
- `fantasy_scoring` emits one entry for each emblem with key, color, required inputs, and raw points.
  Any missing input gives null; Deaths and First Blood retain their defined floor/boolean behavior.
  Quality, trait, and title modifiers are intentionally not applied to historical maps.

### Scoring resource

- Register `opendota://fantasy/ti-2026/scoring` with explicit JSON MIME type, edition metadata, and
  read-only/idempotent annotations. Load it with `importlib.resources`, independent of cwd.
- Store all 18 stable keys, colors, typed formula operations/parameters, human formula labels,
  input semantics, five multipliers, aggregation rules, trait/title records, evidence status,
  caveats, retrieval/effective dates, and direct source links.
- Complete the trait/title name inventory and classify every supportable rule claim during Phase 0,
  before `/speckit-tasks`. Implementation only transcribes this frozen evidence into installed JSON
  and adds schema, source-resolution, and scorer-parity validation; it does not discover rules.
- Treat FR-015 formulas as the supplied baseline rule set. Do not label an effect official without
  a direct official artifact; unverified numeric effects remain null with status `unknown`.

## Complexity Tracking

No constitution violations require justification.

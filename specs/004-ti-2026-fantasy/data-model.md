# Data Model: TI 2026 Fantasy Analysis

Public tool models are typed Pydantic models. Every raw-stat field is present even when null;
optional groups and match-bound modifier data use sparse serialization.

## Latest observed lineup

### `TeamRosterRequest`

Exactly one selector: positive `team_id` or nonblank `team_name`. Team-name/tag normalization and
at-most-10 ambiguity candidates reuse existing team discovery behavior. The match scan has no
public lookback parameter: it is fixed at the five newest completed records.

### `LatestObservedLineupResponse`

| Field | Type | Meaning |
|---|---|---|
| `team` | team identity? | Resolved positive team ID and name |
| `source_match` | `LineupSourceMatch`? | Selected match ID and UTC start time |
| `coverage` | `LineupCoverage`? | Completed records examined and usable parsed records found |
| `players` | list[`LineupPlayer`]? | Exactly five only after membership sets match |
| `candidates` | list[team candidate]? | Selection-required outcome only, at most 10 |
| `warnings` | list[data warning]? | Sparse ambiguity diagnostics |
| `error` | structured error? | Validation, identity, unavailable, mismatch, or upstream failure |

### `LineupSourceMatch`

Fields: positive `match_id` and UTC `start_time`. It identifies evidence provenance and does not
claim roster effective dates.

### `LineupCoverage`

Fields: `completed_records_considered` (0-5), `details_requested` (0-5), and `parsed_usable`
(0-1). On `lineup_mismatch`, coverage stops at the newest usable parsed match; the service does not
search for a matching older roster.

### `LineupPlayer`

| Field | Type | Rule |
|---|---|---|
| `account_id` | positive integer | Present in both selected-match and current-member sets |
| `pro_name` | nonblank string? | `/proPlayers` name only; absence remains null |
| `position` | integer 1-5? | Match-derived inference only |
| `lane` | `safelane`/`midlane`/`offlane`? | Mapped from valid match `lane_role` |
| `last_hits_at_10` | nonnegative integer? | Latest valid `lh_t` sample at or before 600 seconds |
| `inference_status` | `inferred`/`ambiguous` | Whether `position` is supported |

Membership validation occurs before this model is returned. `/teams/{team_id}/players` must yield
exactly five distinct positive IDs whose `is_current_team_member` is strictly true, and the set
must equal the selected match's five team-side IDs. Null/false membership is not current. A mismatch
returns `lineup_mismatch` with no `players`; an invalid current-member set returns
`current_roster_unavailable`.

Position inference requires exactly two safelane, one midlane, and two offlane players. Position 2
comes from the unique midlane row. Distinct ten-minute last hits rank safelane as 1/5 and offlane as
3/4. A missing/tied sample or invalid distribution makes each unsupported `position` null; IDs are
still returned after membership validation.

## Request and identity

### `PlayerFantasyRequest`

| Field | Type | Default / validation |
|---|---|---|
| `account_id` | positive integer? | Exactly one selector with `player_name` |
| `player_name` | nonblank string? | Normalized exact name preferred; otherwise selection required |
| `match_count` | integer | Default 20; 1-100; applied after filters |
| `version_pattern` | string? | Max 64; timeout-bounded full match; omitted means latest patch |
| `start_date` | UTC date? | Inclusive `YYYY-MM-DD` |
| `end_date` | UTC date? | Inclusive and not before start |
| `tournament_tiers` | list[enum] | Default `premium`; named subset or only `all` |
| `include` | list[enum] | Distinct subset containing only `fantasy_scoring` |

There is deliberately no public-match, lobby-type, or provenance-bypass input. `tournament_tiers`
is evaluated only after mandatory professional-league verification; `all` means every eligible
league tier and cannot include public matchmaking.

### `ProfessionalPlayerReference`

Fields: positive `account_id`, nonblank `pro_name`, and optional current `team_id`/`team_name`.
Team fields aid selection only and do not describe historical map membership.

### `ProfessionalPlayerCandidate`

Same compact identity fields as the reference. At most 10 are returned in deterministic order.

## Response envelope

### `PlayerFantasyResponse`

| Field | Type | Meaning |
|---|---|---|
| `player` | `ProfessionalPlayerReference`? | Resolved identity on success |
| `candidates` | list[`ProfessionalPlayerCandidate`]? | Selection-required outcome only |
| `filters` | `FantasyAppliedFilters`? | Effective patch/date/tier filters |
| `coverage` | `FantasyCoverage`? | Bounded collection accounting |
| `returned_count` | integer? | Length of `matches` |
| `reference_uri` | URI? | Present when scoring group is requested |
| `matches` | list[`FantasyMatchEvidence`] | Newest eligible maps, at most 100 |
| `warnings` | list[`DataWarning`] | Sparse root warnings; one deduplicated warning per unavailable statistic |
| `error` | structured error? | Validation, identity, or exhausted upstream failure |

### `FantasyAppliedFilters`

Fields: `patch`, optional inclusive `start_date`/`end_date`, and `tournament_tiers`. It contains no
catalog IDs, regex engine details, or per-map filter dispositions.

### `FantasyCoverage`

Fields: nonnegative `history_records_examined`, `details_requested`, `details_usable`, and boolean
`history_exhausted`. Optional `truncated=true` means the bounded operation stopped without proving
source exhaustion; a corresponding warning is required.

## Match evidence

### `FantasyMatchEvidence`

Fields: `context`, `raw_stats`, optional `fantasy_scoring`, and sparse map warnings.

### `FantasyMatchContext`

| Field | Type |
|---|---|
| `match_id` | positive integer |
| `start_time` | UTC datetime |
| `patch` | string? |
| `tournament_name` | string? |
| `tournament_tier` | raw string? |
| `series_id` | positive integer? |
| `player` | `ProfessionalPlayerReference` |
| `team` | team ID/name reference with nullable members |
| `opponent` | team ID/name reference with nullable members |
| `hero` | hero ID/name reference with nullable members |
| `result` | `win`/`loss`? |
| `duration_seconds` | nonnegative integer? |
| `team_kills` | nonnegative integer? |
| `opponent_kills` | nonnegative integer? |

Missing optional context does not drop a map unless an active filter cannot be evaluated, except
professional provenance is never optional: the hydrated match must have a positive league ID that
resolves to authoritative league metadata without contradiction. Missing, zero, unknown, or
contradictory league provenance always drops the candidate. Series identity is never inferred.
Professional provenance, completed status, and a selected-player row are internal eligibility
conditions, not public status fields.

### `FantasyRawStats`

All fields are required keys and nullable values:

| Field | Type / special rule |
|---|---|
| `kills`, `deaths`, `assists`, `last_hits`, `denies` | nonnegative integer? |
| `gold_per_minute` | nonnegative integer? |
| `madstones_collected` | nonnegative integer?; currently null; bundle-use count is not collection |
| `tower_last_hits`, `observer_wards_placed`, `camps_stacked` | nonnegative integer? |
| `runes_picked_up_or_bottled` | nonnegative integer?; only compatible evidence |
| `watchers_captured` | nonnegative integer?; currently null; lamp-use count cannot distinguish neutral/enemy captures |
| `lotuses_taken` | nonnegative integer?; currently null; item consumption is not collection |
| `smoke_of_deceit_uses` | nonnegative integer?; parsed item uses only |
| `roshan_last_hits` | nonnegative integer? |
| `teamfight_participation` | number 0-1?; null for zero/missing denominator |
| `stun_duration_seconds` | nonnegative number?; fractional allowed |
| `tormentor_last_hits` | nonnegative integer?; attributed Tormentor objective-event count |
| `courier_last_hits` | nonnegative integer? |
| `first_blood` | boolean?; false only when another credit is reliable |

`tormentor_last_hits` counts applicable-patch `CHAT_MESSAGE_MINIBOSS_KILL` events whose expanded
`player_slot` uniquely equals the selected player's match row and whose team is consistent with the
player's side. It is `0` only when the objective ledger is present and every Tormentor event is
individually attributable; a missing ledger, pre-7.33 patch, invalid slot mapping, or any
unattributed/conflicting Tormentor event yields null.

## Scoring group and canonical rules

### `FantasyScoring`

Field: `emblems`, exactly 18 `RawEmblemScore` entries in canonical order.

### `RawEmblemScore`

Fields: stable `key`, color (`red`/`blue`/`green`), `inputs` mapping of raw field names to their
actual nullable values, and nullable numeric `raw_points`. Formula prose, sources, quality, traits,
and titles remain in the referenced resource.

### Formula operations

- `multiply(input, factor)` for ordinary counts/durations/GPM/ratio.
- `death_floor(deaths, maximum=1950, penalty=195, floor=0)`.
- `boolean_award(first_blood, award=1934)` where false is zero and null remains null.
- `sum_multiply(last_hits, denies, factor=3)` for Creep Score.

The scorer rejects nonfinite or invalid typed inputs; it never executes formula strings.

## Scoring reference

### `FantasyScoringReference`

Top-level fields: `edition`, `competition`, `effective_date` (nullable), `retrieved_at`,
`raw_score_definition`, 18 `emblems`, five `quality_tiers`, `traits`, `titles`, `aggregation`,
`sources`, and `caveats`.

Each rule fact contains a stable ID, scope, prerequisites/order/stacking where applicable, nullable
numeric effect, `official`/`community_verified`/`unknown` status, source IDs, and caveat. Unknown
effects cannot carry a numeric modifier. Title facts additionally identify `component` as `prefix`
or `suffix`.

Rule discovery and evidence classification are planning inputs, not implementation-time research.
Implementation transcribes the frozen inventory into package JSON and validates schema, source
references, and scorer parity. A known but unverified trait/title fact remains present with null
numeric effect and `unknown` status rather than being deferred or guessed.

## Relationships and states

```text
TeamRosterRequest -> resolved team | candidates | error
resolved team -> five-record scan + current-member set -> equal | cannot infer
equal -> LatestObservedLineup -> five LineupPlayer records -> player fantasy requests
PlayerFantasyRequest -> resolved player | candidates | error
resolved player -> bounded history -> verified details -> eligible maps -> post-filter slice
FantasyMatchEvidence -> FantasyMatchContext + FantasyRawStats + FantasyScoring?
FantasyScoring -> 18 RawEmblemScore
FantasyScoringReference -> emblems + quality tiers + traits + titles + aggregation + sources
```

Collector state:

```text
validating -> resolving -> collecting -> hydrating -> filtering -> complete
                  |             |             |          -> complete_truncated
                  |             |             -> partial_warning
                  |             -> retry_exhausted
                  -> needs_selection / not_found
any active state -> cancelled
```

Lineup resolver state:

```text
validating -> resolving -> loading current members/history -> scanning (maximum five)
                  |                    |                       -> lineup_unavailable
                  |                    -> current_roster_unavailable
                  -> needs_selection / not_found
scanning -> membership_check -> complete | lineup_mismatch
any active state -> cancelled / retry_exhausted
```

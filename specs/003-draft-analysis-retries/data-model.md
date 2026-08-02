# Data Model: Reliable Retries and Lean Team Drafting Report

Public report models are typed Pydantic models with sparse serialization. Internal normalization,
filter evaluation, provenance, and diagnostic state are implementation details and are not fields
in the MCP response.

## Retry entities

### `RetryPolicy`

Immutable runtime policy used by safe OpenDota GET operations.

| Field | Type | Default | Validation |
|---|---|---:|---|
| `max_attempts` | integer | 6 | 1-20; includes the initial attempt |
| `base_delays_seconds` | tuple[number, ...] | 2,4,8,16,32 | positive finite values |
| `jitter_ratio_max` | number | 0.20 | finite, 0-1 |
| `individual_delay_limit_seconds` | number | 40 | positive finite |
| `accumulated_delay_limit_seconds` | number | 75 | positive finite |
| `elapsed_limit_seconds` | number | 90 | positive finite |

Retry observations and decisions remain internal. A public exhausted error carries only a stable
error code, a concise message, an actionable exhaustion reason, and an optional safe retry delay.
Detailed attempts, clocks, selected-delay sources, and budgets belong in structured logs.

### Retry state transitions

```text
ready -> attempting -> succeeded
                    -> nonretryable_failed
                    -> retryable_observed -> waiting -> attempting
                                          -> exhausted
any active state -> cancelled
```

Cache hits finish before `ready`; cache waiters share the population owner's terminal result.

## Request model

### `DraftingReportRequest`

| Field | Type | Default/validation |
|---|---|---|
| `team_id` | integer | required positive stable ID |
| `lookback_count` | integer | default 25; 1-100 |
| `version_pattern` | string? | at most 64 chars; timeout-bounded full match |
| `tournament_tiers` | list[enum] | default `premium`; distinct named values or only `all` |
| `side` | `radiant`/`dire`? | omitted means either |
| `result` | `win`/`loss`? | omitted means either |
| `first_ban` | `yes`/`no`? | omitted means either |
| `include` | list[enum] | distinct subset of five groups; default empty |
| `page_size` | integer | default 10; 1-25 |

`continuation_cursor` is traversal state. A continuation resolves to an immutable saved request;
repeated request fields must have the same normalized fingerprint.

## Public report envelope

### `DraftingReport`

| Field | Type | Meaning |
|---|---|---|
| `team` | `TeamReference` | selected team ID and name; no tag |
| `filters` | `AppliedFilters` | resolved patch label/pattern, tiers, and supplied scenario filters |
| `coverage` | `LookbackCoverage` | examined, parsed, and unparsed counts |
| `matches` | list[`MatchComparison`] | current page of eligible matches |
| `next_cursor` | string? | present only when another page exists |

There is no request echo, patch/tier selection object, percentage, per-stage coverage, exclusion
map, unknown map, returned count, terminal flag, snapshot expiry, generic status, completeness, or
warnings collection. `matches=[]` is a successful empty result.

### `TeamReference`

Fields: `team_id`, `name`. Team ID is retained because it is a supported lookup key. Team tag is
not returned.

### `AppliedFilters`

Fields: `patch` (resolved exact label or caller pattern), `tournament_tiers`, and optional `side`,
`result`, and `first_ban`. It contains no catalog IDs, release dates, sources, valid-value lists, or
evaluation results.

### `LookbackCoverage`

Fields: `examined`, `parsed`, and `unparsed`.

Validation: all values are nonnegative, `examined <= 100`, and `parsed + unparsed == examined`.
No requested/eligible echoes, intermediate filter-stage counts, or per-match explanations are public.

## Core eligible match

### `MatchComparison`

| Field | Type | Meaning |
|---|---|---|
| `match_id` | positive integer | follow-up lookup key |
| `start_time` | UTC datetime | game start |
| `duration_seconds` | nonnegative integer | game duration |
| `tournament` | `TournamentReference` | name and upstream tier only |
| `patch` | string | human-readable patch label |
| `analyzed_team` | string | match-time team name |
| `opponent` | `TeamReference` | opponent ID/name for follow-up lookup |
| `side` | `radiant`/`dire` | analyzed-team side |
| `result` | `win`/`loss` | analyzed-team result |
| `ban_order` | `first`/`second`/null | null when unknown |
| group fields | optional models | emitted only when requested |

The core contains no team tag, league ID, patch ID, parse/analysis status, filter evaluation or
disposition, provenance/source, quality, availability, completeness, reason, or warning fields.
Unparsed, filtered, malformed, and failed-detail items contribute to coverage but are not expanded
into match objects.

### `TournamentReference`

Fields: `name`, `tier`. No league ID or tier source is returned.

## Optional evidence groups

### `DraftEvidence`

Field: `actions`, a chronological list of `DraftAction`.

`DraftAction` fields:

- `order`: one public action-order value;
- `type`: `pick` or `ban`;
- `round`: 1-based run number for this action type within the acting team's ordered subsequence;
- `team`: analyzed-team or opponent name;
- `hero`: localized hero name string;
- optional `player` professional-name string for a uniquely mapped pick;
- optional `matchup` with `known`, `lane`, and `opposing_heroes` name strings.

`type` is the phase, so no separate phase field is emitted. Round is omitted when global action
order cannot be established unambiguously. Hero IDs, source indexes, duplicate source-order fields,
account IDs, identity structs, chronology quality, evidence quality, and reasons are excluded.

### `LaneEvidence`

Field: `lanes`, containing one entry for each available safelane, midlane, and offlane comparison.

Each entry has `lane`, `analyzed_team_heroes`, `opponent_heroes`, and nullable analyzed-team
`experience_difference_10` and `last_hit_difference_10`. Heroes are name strings.

### `EconomyEvidence`

Fields: nullable `gold_difference_10`, `gold_difference_20`, `experience_difference_10`, and
`experience_difference_20` from the analyzed-team perspective. Team differences come from
`radiant_gold_adv` and `radiant_xp_adv` with side-aware sign handling.

The evidence also contains both teams' `hero_total_gold` records from `gold_t` and
`hero_experience` records from `xp_t` when verified aligned player series exist. Each hero record
has `hero`, optional `player`, `team`, and nullable `at_10`/`at_20` values.

Requested checkpoint and sample timestamps are not repeated in each value.

### `StructureEvidence`

Fields: `analyzed_team_lost` and `opponent_lost`, each with nullable `by_10` and `by_20` lists of
compact structure keys such as `top_t1`, `mid_melee_barracks`, or `tier4`.

Lists are cumulative. A verified empty list means no losses; `null` means the checkpoint cannot be
established. Zero-filled counter trees, totals, unattributed-event lists, and diagnostic wrappers
are excluded.

### `ObjectiveEvidence`

Fields: `analyzed_team` and `opponent`, each containing nullable `roshan_by_25` and
`tormentor_by_25` event-time lists in game-clock seconds.

A verified empty list means zero attributable takes; `null` means unavailable or not applicable.
Counts and first-take values are omitted because callers can derive them from the event times.

## Relationships

```text
DraftingReportRequest -> DraftingReport
DraftingReport -> TeamReference
DraftingReport -> LookbackCoverage
DraftingReport -> MatchComparison *
MatchComparison -> requested evidence groups 0..5
```

The immutable pagination snapshot may retain richer internal records needed to continue traversal,
but only this public projection is serialized.
